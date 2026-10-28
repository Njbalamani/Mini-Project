"""Integration center views. All state changes are server-side and audited."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.audit_logs.services import log_event

from . import credentials, security, whatsapp
from .models import Integration, WhatsAppMessage
from .providers import IntegrationError, IntegrationNotConfigured, get_provider_spec
from .services import (
    complete_authorization,
    connect_whatsapp,
    disconnect_integration,
    get_or_create_integration,
    start_authorization,
    sync_integration,
    validate_state,
)

PROVIDERS = ["gmail", "google_calendar", "github", "whatsapp", "linkedin", "facebook"]


@login_required
def integration_center(request):
    existing = {i.provider: i for i in Integration.objects.filter(user=request.user)}
    cards = []
    for key in PROVIDERS:
        if key == "whatsapp":
            card = {"provider": key, "label": "WhatsApp", "scopes": ["messages"],
                    "configured": whatsapp.is_configured()}
        else:
            spec = get_provider_spec(key)
            card = {"provider": key, "label": spec.label, "scopes": spec.scopes,
                    "configured": spec.configured}
        card["integration"] = existing.get(key)
        card["status"] = existing[key].status if key in existing else "disconnected"
        cards.append(card)
    return render(request, "integrations/center.html", {"cards": cards})


@login_required
def step_up(request):
    """Fresh identity check required before connecting/disconnecting accounts."""
    if security.is_verified(request):
        return redirect(security.pop_next(request))
    if request.method == "POST":
        ok, error = security.verify_challenge(
            request,
            password=request.POST.get("password", ""),
            code=request.POST.get("code", ""),
        )
        if ok:
            security.mark_verified(request)
            log_event(actor=request.user, action="integration.step_up_passed", request=request)
            messages.success(request, "Identity confirmed.")
            return redirect(security.pop_next(request))
        log_event(actor=request.user, action="integration.step_up_failed",
                  outcome="failure", request=request)
        messages.error(request, error)
    from apps.accounts.models import UserProfile
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return render(request, "integrations/step_up.html", {"profile": profile})


@login_required
def connect(request, provider):
    if provider not in PROVIDERS:
        messages.error(request, "Unknown integration.")
        return redirect("integrations:center")
    gate = security.require_verified(request, request.get_full_path())
    if gate:
        return gate
    if provider == "whatsapp":
        return redirect("integrations:whatsapp_connect")
    try:
        url, _state = start_authorization(request, provider)
    except IntegrationNotConfigured as exc:
        messages.warning(request, str(exc))
        return redirect("integrations:center")
    except IntegrationError as exc:
        messages.error(request, str(exc))
        return redirect("integrations:center")
    return redirect(url)


@login_required
def callback(request, provider):
    if provider not in PROVIDERS:
        messages.error(request, "Unknown integration.")
        return redirect("integrations:center")
    error = request.GET.get("error")
    if error:
        log_event(actor=request.user, action="integration.oauth_denied",
                  resource_type="integration", outcome="denied", request=request,
                  metadata={"provider": provider, "error": error})
        messages.error(request, f"Authorization was not granted ({error}).")
        return redirect("integrations:center")

    state = request.GET.get("state")
    code = request.GET.get("code")
    if not validate_state(request, provider, state):
        log_event(actor=request.user, action="integration.oauth_invalid_state",
                  resource_type="integration", outcome="denied", request=request,
                  metadata={"provider": provider})
        messages.error(request, "Invalid OAuth state. The request was rejected for your safety.")
        return redirect("integrations:center")
    if not code:
        messages.error(request, "Authorization code missing.")
        return redirect("integrations:center")

    try:
        complete_authorization(request, provider, code)
    except (IntegrationError, IntegrationNotConfigured) as exc:
        messages.error(request, str(exc))
        return redirect("integrations:center")
    messages.success(request, "Integration connected.")
    return redirect("integrations:center")


@login_required
@require_POST
def sync(request, provider):
    integration = get_or_create_integration(request.user, provider)
    if integration.status != Integration.Status.CONNECTED:
        messages.warning(request, "Connect the integration before syncing.")
        return redirect("integrations:center")
    result = sync_integration(request, integration)
    if result["ok"]:
        messages.success(request, "Synchronization complete.")
    else:
        messages.error(request, result["error"])
    return redirect("integrations:center")


@login_required
@require_POST
def disconnect(request, provider):
    gate = security.require_verified(request, reverse("integrations:center"))
    if gate:
        return gate
    integration = Integration.objects.filter(user=request.user, provider=provider).first()
    if integration:
        disconnect_integration(request, integration)
    messages.success(request, "Integration disconnected and credentials removed.")
    return redirect("integrations:center")


@login_required
def integration_detail(request, provider):
    if provider == "whatsapp":
        return redirect("integrations:whatsapp_panel")
    integration = Integration.objects.filter(user=request.user, provider=provider).first()
    return render(request, "integrations/detail.html", {
        "provider": provider, "integration": integration,
        "spec": get_provider_spec(provider) if provider in PROVIDERS else None,
    })


@login_required
def whatsapp_connect(request):
    """Enable the WhatsApp integration for this user (credentials are server-side)."""
    gate = security.require_verified(request, request.get_full_path())
    if gate:
        return gate
    if request.method == "POST":
        number = (request.POST.get("number") or "").strip()
        if not whatsapp.is_configured():
            messages.error(request, whatsapp.not_configured_message())
            return redirect("integrations:center")
        connect_whatsapp(request, number)
        messages.success(request, "WhatsApp connected.")
        return redirect("integrations:whatsapp_panel")
    if whatsapp.bridge_configured():
        return render(request, "integrations/whatsapp_qr.html", {
            "bridge_configured": True,
        })
    return render(request, "integrations/whatsapp_connect.html", {
        "configured": whatsapp.is_configured(),
        "configured_number": whatsapp.display_number(),
    })


@login_required
def whatsapp_qr_status(request):
    """Proxy the bridge pairing state to the browser (JSON)."""
    if not whatsapp.bridge_configured():
        return JsonResponse({"status": "unconfigured", "qr": None, "me": None})
    return JsonResponse(whatsapp.bridge_status() or {"status": "offline", "qr": None})


@login_required
@require_POST
def whatsapp_pair(request):
    """Request a WhatsApp pairing code for the given number (JSON)."""
    gate = security.require_verified(request, request.get_full_path())
    if gate:
        return JsonResponse({"error": "step_up_required",
                             "redirect": reverse("integrations:step_up")}, status=403)
    if not whatsapp.bridge_configured():
        return JsonResponse({"error": "The QR bridge is not configured."}, status=400)
    try:
        code = whatsapp.request_pairing(request.POST.get("number", ""))
    except whatsapp.WhatsAppError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    log_event(actor=request.user, action="whatsapp.pairing_code_requested",
              request=request, metadata={"number": request.POST.get("number", "")})
    return JsonResponse({"code": code})


@login_required
def whatsapp_panel(request):
    integration = Integration.objects.filter(user=request.user, provider="whatsapp",
                                            status=Integration.Status.CONNECTED).first()
    if not integration:
        messages.warning(request, "Connect WhatsApp first.")
        return redirect("integrations:center")
    return render(request, "integrations/whatsapp_panel.html", {
        "integration": integration,
        "thread": integration.whatsapp_messages.all()[:200],
        "demo": whatsapp.is_demo(),
        "bridge": whatsapp.bridge_configured(),
        "configured": whatsapp.is_configured(),
    })


@login_required
@require_POST
def whatsapp_send(request):
    integration = Integration.objects.filter(
        user=request.user, provider="whatsapp", status=Integration.Status.CONNECTED
    ).first()
    if not integration:
        messages.warning(request, "Connect WhatsApp first.")
        return redirect("integrations:center")
    to = (request.POST.get("to") or "").strip()
    body = (request.POST.get("body") or "").strip()
    try:
        whatsapp.send_text(to, body)
    except whatsapp.WhatsAppError as exc:
        messages.error(request, str(exc))
        return redirect("integrations:whatsapp_panel")
    whatsapp.record_outbound(integration, to, body)
    log_event(actor=request.user, action="whatsapp.message_sent",
              resource_type="integration", resource_id=integration.pk, request=request,
              metadata={"to": to})
    messages.success(request, "Message sent.")
    return redirect("integrations:whatsapp_panel")


@csrf_exempt
def whatsapp_webhook(request):
    """Meta calls this to verify the hook (GET) and to deliver messages (POST)."""
    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge", "")
        configured = whatsapp.verify_token()
        if mode == "subscribe" and configured and token == configured:
            return HttpResponse(challenge, content_type="text/plain")
        return HttpResponse(status=403)

    if request.method == "POST":
        import json

        if not whatsapp.verify_signature(request.body, request.headers.get("X-Hub-Signature-256")):
            log_event(action="whatsapp.webhook_rejected", outcome="denied", request=request)
            return JsonResponse({"ok": False, "error": "invalid signature"}, status=403)
        try:
            payload = json.loads(request.body.decode() or "{}")
        except ValueError:
            return JsonResponse({"ok": False, "error": "bad json"}, status=400)
        integration = Integration.objects.filter(
            provider="whatsapp", status=Integration.Status.CONNECTED
        ).order_by("id").first()
        count = 0
        for message in whatsapp.parse_inbound(payload):
            if integration:
                whatsapp.record_inbound(
                    integration, message["wa_id"], message["body"],
                    name=message.get("name", ""), message_type=message["message_type"],
                    raw=message.get("raw", {}),
                )
                count += 1
        if integration and count:
            from apps.notifications.services import notify

            notify(integration.user, type="system", level="info",
                   title=f"{count} new WhatsApp message(s)",
                   message="Open the WhatsApp panel to read them.",
                   url="/integrations/whatsapp/panel/")
        return JsonResponse({"ok": True, "received": count})

    return HttpResponse(status=405)


@login_required
def call_room(request):
    """Peer-to-peer video calling in the browser (WebRTC, permission gated)."""
    log_event(actor=request.user, action="call.room_opened", request=request)
    return render(request, "integrations/call_room.html", {})


CONFIGURABLE = ["google", "github", "linkedin", "facebook", "whatsapp"]
DOCS = {
    "google": "https://console.cloud.google.com/apis/credentials",
    "github": "https://github.com/settings/developers",
    "linkedin": "https://www.linkedin.com/developers/apps",
    "facebook": "https://developers.facebook.com/apps/",
    "whatsapp": "https://developers.facebook.com/docs/whatsapp/cloud-api/get-started",
}
CREDENTIAL_LABELS = {
    "google": "Gmail & Google Calendar", "github": "GitHub", "linkedin": "LinkedIn",
    "facebook": "Facebook", "whatsapp": "WhatsApp",
}

EXAMPLES = {
    "google": "Create an OAuth 2.0 Client ID (type: Web application) in Google Cloud Console, then add the redirect URI below as an authorized redirect URI.",
    "github": "Create an OAuth App in GitHub Developer settings and paste the callback URL below.",
    "linkedin": "Create an app in the LinkedIn Developer Portal and enable Sign In with LinkedIn using OpenID Connect.",
    "facebook": "Create an app in the Meta for Developers portal and enable Facebook Login.",
    "whatsapp": "Official: create a WhatsApp Business app in Meta for Developers and copy the phone number ID, a permanent access token, the webhook verify token and the app secret. QR link: set only Bridge URL + Bridge secret (+ App secret for webhook signatures) and run the whatsapp-bridge service.",
}

FIELD_LABELS = {
    "client_id": "Client ID",
    "client_secret": "Client secret",
    "token": "Access token",
    "phone_number_id": "Phone number ID",
    "verify_token": "Webhook verify token",
    "app_secret": "App secret (webhook signatures)",
    "display_number": "Display number",
    "bridge_url": "Bridge URL (QR link)",
    "bridge_secret": "Bridge secret (QR link)",
    "demo": "Simulator (1/true to enable)",
}


@login_required
def provider_credentials(request):
    if not request.user.is_staff:
        messages.error(request, "Only administrators can manage provider credentials.")
        return redirect("integrations:center")

    if request.method == "POST":
        provider = request.POST.get("provider", "")
        if provider not in credentials.FIELDS:
            messages.error(request, "Unknown provider.")
            return redirect("integrations:provider_credentials")
        if request.POST.get("action") == "clear":
            credentials.clear(provider)
            log_event(actor=request.user, action="integration.credentials_cleared",
                      request=request, metadata={"provider": provider})
            messages.success(request, f"Cleared stored credentials for {provider}.")
            return redirect("integrations:provider_credentials")
        data, secrets_map = {}, {}
        for field, (_env, is_secret) in credentials.FIELDS[provider].items():
            value = (request.POST.get(field) or "").strip()
            (secrets_map if is_secret else data)[field] = value
        credentials.set_values(provider, data=data, secrets_map=secrets_map, user=request.user)
        log_event(actor=request.user, action="integration.credentials_updated",
                  request=request, metadata={"provider": provider})
        messages.success(request, f"Saved credentials for {provider}.")
        return redirect("integrations:provider_credentials")

    from . import whatsapp as wa

    providers_view = []
    for provider in credentials.FIELDS:
        fields_ctx = []
        for field, (env_name, is_secret) in credentials.FIELDS[provider].items():
            value = credentials.get(provider, field)
            fields_ctx.append({
                "key": field,
                "env": env_name,
                "secret": is_secret,
                "value": "" if is_secret else value,
                "is_set": bool(value),
                "label": FIELD_LABELS.get(field, field.replace("_", " ").title()),
            })
        if provider == "whatsapp":
            redirect_uri = request.build_absolute_uri(reverse("integrations:whatsapp_webhook"))
            configured = wa.is_configured()
        else:
            callback_provider = "gmail" if provider == "google" else provider
            redirect_uri = request.build_absolute_uri(
                reverse("integrations:callback", args=[callback_provider]))
            configured = get_provider_spec(callback_provider).configured
        providers_view.append({
            "key": provider,
            "label": CREDENTIAL_LABELS.get(provider, provider.title()),
            "fields": fields_ctx,
            "redirect_uri": redirect_uri,
            "docs": DOCS.get(provider, ""),
            "example": EXAMPLES.get(provider, ""),
            "configured": configured,
        })
    return render(request, "integrations/credentials.html", {"providers": providers_view})
