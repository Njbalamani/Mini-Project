"""Resolve provider credentials from the database (encrypted) or the environment.

Each provider exposes a set of named fields. Non-secret fields are stored in
plain JSON; secret fields are Fernet-encrypted. An admin can enter them from
**Settings → Provider credentials** so no server file edits are needed. Anything
left blank falls back to the matching ``NEXAMIND`` environment setting.
"""
from __future__ import annotations

import json

from django.conf import settings

from .crypto import decrypt, encrypt

# provider -> {field: (env var name, is_secret)}
FIELDS = {
    "google": {
        "client_id": ("GOOGLE_CLIENT_ID", False),
        "client_secret": ("GOOGLE_CLIENT_SECRET", True),
    },
    "github": {
        "client_id": ("GITHUB_CLIENT_ID", False),
        "client_secret": ("GITHUB_CLIENT_SECRET", True),
    },
    "linkedin": {
        "client_id": ("LINKEDIN_CLIENT_ID", False),
        "client_secret": ("LINKEDIN_CLIENT_SECRET", True),
    },
    "facebook": {
        "client_id": ("FACEBOOK_CLIENT_ID", False),
        "client_secret": ("FACEBOOK_CLIENT_SECRET", True),
    },
    "whatsapp": {
        "token": ("WHATSAPP_TOKEN", True),
        "phone_number_id": ("WHATSAPP_PHONE_NUMBER_ID", False),
        "verify_token": ("WHATSAPP_VERIFY_TOKEN", False),
        "app_secret": ("WHATSAPP_APP_SECRET", True),
        "display_number": ("WHATSAPP_DISPLAY_NUMBER", False),
        "bridge_url": ("WHATSAPP_BRIDGE_URL", False),
        "bridge_secret": ("WHATSAPP_BRIDGE_SECRET", True),
        "demo": ("WHATSAPP_DEMO", False),
    },
}

# Providers that share the Google OAuth app (Gmail / Calendar).
GOOGLE_ALIASES = {"gmail", "google_calendar"}


def _config_provider(provider):
    return "google" if provider in GOOGLE_ALIASES else provider


def _secret_map(cfg):
    raw = decrypt(cfg.secrets) if cfg and cfg.secrets else ""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def get(provider, field, default=""):
    """Return a credential value: DB override first, then environment."""
    from .models import ProviderConfig

    cfg_provider = _config_provider(provider)
    spec = FIELDS.get(cfg_provider, {})
    if field not in spec:
        return default
    env_name, is_secret = spec[field]

    cfg = ProviderConfig.objects.filter(provider=cfg_provider).first()
    if cfg:
        if is_secret:
            value = _secret_map(cfg).get(field)
            if not value:
                # Legacy/plaintext fallback: values written to ``data`` before a
                # field was classified as secret (or by scripts) still resolve.
                value = (cfg.data or {}).get(field)
        else:
            value = (cfg.data or {}).get(field)
        if value:
            return value
    if env_name:
        return settings.NEXAMIND.get(env_name, default) or default
    return default


def set_values(provider, *, data=None, secrets_map=None, user=None):
    """Upsert stored credentials. Non-empty values overwrite; blanks are ignored."""
    from .models import ProviderConfig

    cfg_provider = _config_provider(provider)
    cfg, _ = ProviderConfig.objects.get_or_create(provider=cfg_provider)

    merged_data = dict(cfg.data or {})
    for key, value in (data or {}).items():
        if value not in (None, ""):
            merged_data[key] = value
    cfg.data = merged_data

    if secrets_map:
        merged_secrets = _secret_map(cfg)
        for key, value in secrets_map.items():
            if value not in (None, ""):
                merged_secrets[key] = value
        cfg.secrets = encrypt(json.dumps(merged_secrets))
    if user is not None:
        cfg.updated_by = user
    cfg.save()
    return cfg


def clear(provider):
    from .models import ProviderConfig

    ProviderConfig.objects.filter(provider=_config_provider(provider)).delete()


def field_keys(provider):
    return list(FIELDS.get(_config_provider(provider), {}).keys())


def current_values(provider):
    """Non-secret values plus which secret fields are already set (for the UI)."""
    from .models import ProviderConfig

    cfg_provider = _config_provider(provider)
    cfg = ProviderConfig.objects.filter(provider=cfg_provider).first()
    data = dict(cfg.data or {}) if cfg else {}
    secrets_map = _secret_map(cfg)
    out = {"data": data, "secrets_set": {k: bool(v) for k, v in secrets_map.items()}}
    return out


def is_configured(provider, required):
    """True when every required field resolves to a non-empty value."""
    return all(get(provider, f) for f in required)
