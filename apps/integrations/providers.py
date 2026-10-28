"""OAuth provider descriptors and HTTP helpers.

All provider-specific API code lives here. Credentials come exclusively from
environment settings; nothing is hard-coded and no token is ever exposed to the
browser.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import requests
from django.conf import settings

logger = logging.getLogger("nexamind.integrations")


class IntegrationNotConfigured(Exception):
    """Raised when the provider's client credentials are missing."""


class IntegrationError(Exception):
    """Raised for upstream/API failures."""


@dataclass
class ProviderSpec:
    key: str
    label: str
    authorize_url: str
    token_url: str
    scopes: list
    client_id: str = ""
    client_secret: str = ""
    extra_auth_params: dict = field(default_factory=dict)

    @property
    def configured(self):
        return bool(self.client_id and self.client_secret)


def _google_scopes(provider_key):
    if provider_key == "gmail":
        return [settings.NEXAMIND.get("GMAIL_SCOPE", "https://www.googleapis.com/auth/gmail.readonly")]
    return ["https://www.googleapis.com/auth/calendar.readonly"]


def get_provider_spec(provider_key):
    from . import credentials

    if provider_key == "gmail":
        return ProviderSpec(
            key="gmail", label="Gmail",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            scopes=_google_scopes("gmail"),
            client_id=credentials.get("google", "client_id"),
            client_secret=credentials.get("google", "client_secret"),
            extra_auth_params={"access_type": "offline", "prompt": "consent",
                               "include_granted_scopes": "true"},
        )
    if provider_key == "google_calendar":
        return ProviderSpec(
            key="google_calendar", label="Google Calendar",
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            scopes=_google_scopes("google_calendar"),
            client_id=credentials.get("google", "client_id"),
            client_secret=credentials.get("google", "client_secret"),
            extra_auth_params={"access_type": "offline", "prompt": "consent",
                               "include_granted_scopes": "true"},
        )
    if provider_key == "github":
        return ProviderSpec(
            key="github", label="GitHub",
            authorize_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",
            scopes=["read:user", "public_repo"],
            client_id=credentials.get("github", "client_id"),
            client_secret=credentials.get("github", "client_secret"),
        )
    if provider_key == "linkedin":
        return ProviderSpec(
            key="linkedin", label="LinkedIn",
            authorize_url="https://www.linkedin.com/oauth/v2/authorization",
            token_url="https://www.linkedin.com/oauth/v2/accessToken",
            scopes=["openid", "profile", "email"],
            client_id=credentials.get("linkedin", "client_id"),
            client_secret=credentials.get("linkedin", "client_secret"),
        )
    if provider_key == "facebook":
        return ProviderSpec(
            key="facebook", label="Facebook",
            authorize_url="https://www.facebook.com/v21.0/dialog/oauth",
            token_url="https://graph.facebook.com/v21.0/oauth/access_token",
            scopes=["public_profile", "email"],
            client_id=credentials.get("facebook", "client_id"),
            client_secret=credentials.get("facebook", "client_secret"),
        )
    raise IntegrationError(f"Unknown provider: {provider_key!r}")


def build_authorize_url(spec, redirect_uri, state):
    if not spec.configured:
        raise IntegrationNotConfigured(
            f"{spec.label} is not configured on this server. Add the client id/secret "
            "to the environment to enable it."
        )
    from urllib.parse import urlencode

    params = {
        "client_id": spec.client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(spec.scopes),
        "state": state,
    }
    params.update(spec.extra_auth_params)
    return f"{spec.authorize_url}?{urlencode(params)}"


def exchange_code_for_token(spec, code, redirect_uri):
    if not spec.configured:
        raise IntegrationNotConfigured(f"{spec.label} is not configured.")
    payload = {
        "client_id": spec.client_id,
        "client_secret": spec.client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    }
    headers = {"Accept": "application/json"}
    try:
        resp = requests.post(spec.token_url, data=payload, headers=headers, timeout=30)
    except requests.RequestException as exc:
        raise IntegrationError(f"Token exchange failed: {exc}") from exc
    if resp.status_code >= 400:
        raise IntegrationError(f"Token endpoint HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def refresh_access_token(spec, refresh_token):
    if not spec.configured:
        raise IntegrationNotConfigured(f"{spec.label} is not configured.")
    payload = {
        "client_id": spec.client_id,
        "client_secret": spec.client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    try:
        resp = requests.post(spec.token_url, data=payload,
                             headers={"Accept": "application/json"}, timeout=30)
    except requests.RequestException as exc:
        raise IntegrationError(f"Token refresh failed: {exc}") from exc
    if resp.status_code >= 400:
        raise IntegrationError(f"Refresh HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def fetch_github_profile(access_token):
    return _get_json("https://api.github.com/user",
                     headers={"Authorization": f"Bearer {access_token}",
                              "Accept": "application/vnd.github+json"})


def fetch_github_repositories(access_token, limit=10):
    data = _get_json(
        f"https://api.github.com/user/repos?per_page={limit}&sort=updated",
        headers={"Authorization": f"Bearer {access_token}",
                 "Accept": "application/vnd.github+json"},
    )
    if not isinstance(data, list):
        return []
    return [{"name": r.get("name"), "private": r.get("private"),
             "language": r.get("language"), "updated_at": r.get("updated_at"),
             "stars": r.get("stargazers_count")} for r in data]


def fetch_google_profile(access_token):
    return _get_json("https://www.googleapis.com/oauth2/v2/userinfo",
                     headers={"Authorization": f"Bearer {access_token}"})


def fetch_linkedin_profile(access_token):
    return _get_json("https://api.linkedin.com/v2/userinfo",
                     headers={"Authorization": f"Bearer {access_token}"})


def fetch_facebook_profile(access_token):
    return _get_json("https://graph.facebook.com/me?fields=id,name,email",
                     headers={"Authorization": f"Bearer {access_token}"})


def fetch_gmail_metadata(access_token, max_results=10):
    """Read-only message metadata (subjects/senders) - never full bodies."""
    listing = _get_json(
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults={max_results}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    messages = []
    for item in (listing.get("messages") or [])[:max_results]:
        detail = _get_json(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
            f"{item['id']}?format=metadata&metadataHeaders=Subject&metadataHeaders=From&metadataHeaders=Date",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        headers = {h["name"].lower(): h["value"] for h in
                   detail.get("payload", {}).get("headers", [])}
        messages.append({
            "id": item["id"],
            "subject": headers.get("subject", "(no subject)"),
            "from": headers.get("from", ""),
            "date": headers.get("date", ""),
            "snippet": detail.get("snippet", ""),
        })
    return messages


def _get_json(url, headers=None):
    try:
        resp = requests.get(url, headers=headers or {}, timeout=30)
    except requests.RequestException as exc:
        raise IntegrationError(f"Request failed: {exc}") from exc
    if resp.status_code == 401:
        raise IntegrationError("Authorization expired; reconnect the integration.")
    if resp.status_code == 403:
        raise IntegrationError("Access forbidden (rate limit or insufficient scope).")
    if resp.status_code >= 400:
        raise IntegrationError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        return resp.json()
    except ValueError as exc:
        raise IntegrationError("Provider returned a non-JSON response.") from exc
