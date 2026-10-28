"""Integration service layer: connect, tokens, sync and disconnect."""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.audit_logs.services import log_event
from apps.notifications.services import notify

from .crypto import decrypt, encrypt
from .models import Integration, OAuthCredential
from .providers import (
    IntegrationError,
    IntegrationNotConfigured,
    fetch_facebook_profile,
    fetch_github_profile,
    fetch_github_repositories,
    fetch_gmail_metadata,
    fetch_google_profile,
    fetch_linkedin_profile,
    get_provider_spec,
    refresh_access_token,
)

logger = logging.getLogger("nexamind.integrations")


def get_or_create_integration(user, provider):
    integration, _ = Integration.objects.get_or_create(user=user, provider=provider)
    return integration


def start_authorization(request, provider):
    """Return the provider authorize URL and stash OAuth state in the session."""
    spec = get_provider_spec(provider)
    state = secrets.token_urlsafe(24)
    request.session[f"oauth_state_{provider}"] = state
    from django.urls import reverse
    redirect_uri = request.build_absolute_uri(reverse("integrations:callback", args=[provider]))
    from .providers import build_authorize_url
    url = build_authorize_url(spec, redirect_uri, state)
    return url, state


def validate_state(request, provider, state):
    expected = request.session.pop(f"oauth_state_{provider}", None)
    return bool(expected) and secrets.compare_digest(str(expected), str(state or ""))


@transaction.atomic
def complete_authorization(request, provider, code):
    spec = get_provider_spec(provider)
    from django.urls import reverse
    redirect_uri = request.build_absolute_uri(reverse("integrations:callback", args=[provider]))
    token_data = _exchange(spec, code, redirect_uri)

    integration = get_or_create_integration(request.user, provider)
    integration.status = Integration.Status.CONNECTED
    integration.scopes = spec.scopes
    integration.last_error = ""
    integration.save(update_fields=["status", "scopes", "last_error", "updated_at"])

    credential, _ = OAuthCredential.objects.get_or_create(integration=integration)
    credential.access_token_encrypted = encrypt(token_data.get("access_token", ""))
    credential.refresh_token_encrypted = encrypt(token_data.get("refresh_token", ""))
    credential.token_type = token_data.get("token_type", "Bearer")
    credential.scope = token_data.get("scope", " ".join(spec.scopes))
    expires_in = token_data.get("expires_in")
    credential.expires_at = (
        timezone.now() + timedelta(seconds=int(expires_in)) if expires_in else None
    )
    credential.save()

    # Try to record an account identifier (read-only metadata).
    try:
        info = _profile_for(provider, token_data.get("access_token", ""))
        integration.external_account = info
        integration.last_synced_at = timezone.now()
        integration.save(update_fields=["external_account", "last_synced_at"])
    except IntegrationError as exc:
        logger.info("Could not fetch profile for %s: %s", provider, exc)

    log_event(actor=request.user, action="integration.connected",
              resource_type="integration", resource_id=integration.pk,
              request=request, metadata={"provider": provider})
    notify(request.user, type="integration_error", level="success",
           title=f"{spec.label} connected", message="Your account is now linked.",
           url="/integrations/")
    return integration


def _exchange(spec, code, redirect_uri):
    from .providers import exchange_code_for_token
    return exchange_code_for_token(spec, code, redirect_uri)


def _profile_for(provider, access_token):
    if provider == "github":
        profile = fetch_github_profile(access_token)
        return profile.get("login", "")
    if provider in {"gmail", "google_calendar"}:
        profile = fetch_google_profile(access_token)
        return profile.get("email", "")
    if provider == "linkedin":
        profile = fetch_linkedin_profile(access_token)
        return profile.get("email", "") or profile.get("name", "")
    if provider == "facebook":
        profile = fetch_facebook_profile(access_token)
        return profile.get("email", "") or profile.get("name", "")
    return ""


def get_valid_access_token(integration):
    """Return a usable access token, refreshing if expired. May raise."""
    credential = getattr(integration, "credential", None)
    if credential is None:
        raise IntegrationError("No stored credential for this integration.")
    if credential.expires_at and credential.expires_at <= timezone.now():
        refresh = decrypt(credential.refresh_token_encrypted)
        if not refresh:
            integration.status = Integration.Status.ERROR
            integration.last_error = "Authorization expired; please reconnect."
            integration.save(update_fields=["status", "last_error"])
            raise IntegrationError("Authorization expired; please reconnect.")
        spec = get_provider_spec(integration.provider)
        data = refresh_access_token(spec, refresh)
        credential.access_token_encrypted = encrypt(data.get("access_token", ""))
        if data.get("expires_in"):
            credential.expires_at = timezone.now() + timedelta(seconds=int(data["expires_in"]))
        credential.save(update_fields=["access_token_encrypted", "expires_at"])
    return decrypt(credential.access_token_encrypted)


def sync_integration(request, integration):
    """Pull read-only metadata for an integration. Returns a summary dict."""
    try:
        token = "" if integration.provider == "whatsapp" else get_valid_access_token(integration)
        result = {}
        if integration.provider == "github":
            result["repositories"] = fetch_github_repositories(token)
        elif integration.provider == "gmail":
            result["messages"] = fetch_gmail_metadata(token)
        elif integration.provider == "google_calendar":
            result["events"] = []  # calendar sync handled via the calendar module
        elif integration.provider == "linkedin":
            result["profile"] = fetch_linkedin_profile(token)
        elif integration.provider == "facebook":
            result["profile"] = fetch_facebook_profile(token)
        elif integration.provider == "whatsapp":
            result["messages"] = list(
                integration.whatsapp_messages.values("direction", "wa_id", "body")[:10]
            )
        integration.status = Integration.Status.CONNECTED
        integration.last_synced_at = timezone.now()
        integration.last_error = ""
        integration.save(update_fields=["status", "last_synced_at", "last_error"])
        log_event(actor=request.user, action="integration.synced",
                  resource_type="integration", resource_id=integration.pk, request=request)
        return {"ok": True, "data": result}
    except (IntegrationError, IntegrationNotConfigured) as exc:
        integration.status = Integration.Status.ERROR
        integration.last_error = str(exc)[:300]
        integration.save(update_fields=["status", "last_error"])
        notify(integration.user, type="integration_error", level="danger",
               title=f"{integration.get_provider_display()} sync failed",
               message=str(exc)[:200], url="/integrations/")
        return {"ok": False, "error": str(exc)}


def disconnect_integration(request, integration):
    log_event(actor=request.user, action="integration.disconnected",
              resource_type="integration", resource_id=integration.pk, request=request)
    integration.delete()


def connect_whatsapp(request, number=""):
    """Enable WhatsApp messaging for this user (server-side Cloud API token)."""
    from . import whatsapp

    integration = get_or_create_integration(request.user, "whatsapp")
    integration.status = Integration.Status.CONNECTED
    integration.external_account = number or whatsapp.display_number()
    integration.scopes = ["messages"]
    integration.last_error = ""
    integration.last_synced_at = timezone.now()
    integration.save(update_fields=["status", "external_account", "scopes",
                                    "last_error", "last_synced_at", "updated_at"])
    log_event(actor=request.user, action="integration.connected",
              resource_type="integration", resource_id=integration.pk, request=request,
              metadata={"provider": "whatsapp"})
    notify(request.user, type="integration_error", level="success",
           title="WhatsApp connected",
           message="You can now message contacts from NexaMind.", url="/integrations/")
    return integration
