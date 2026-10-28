"""Audit logging service. Never log secrets, tokens or full message bodies."""
import logging
import threading

from .models import AuditLog

logger = logging.getLogger("nexamind.audit")

_state = threading.local()

SENSITIVE_KEYS = {
    "password", "token", "access_token", "refresh_token", "api_key",
    "secret", "authorization", "client_secret", "code",
}


def set_request_id(value):
    _state.request_id = value


def get_request_id():
    return getattr(_state, "request_id", "")


def _scrub(metadata):
    if not isinstance(metadata, dict):
        return {}
    cleaned = {}
    for key, value in metadata.items():
        if key.lower() in SENSITIVE_KEYS:
            cleaned[key] = "[redacted]"
        elif isinstance(value, dict):
            cleaned[key] = _scrub(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            cleaned[key] = value
        else:
            cleaned[key] = str(value)
    return cleaned


def log_event(actor=None, action="", resource_type="", resource_id="", outcome="success",
              request=None, metadata=None):
    """Create an audit record, failing soft if persistence is unavailable."""
    ip = None
    request_id = get_request_id()
    if request is not None:
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
        ip = forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR")
        request_id = getattr(request, "request_id", request_id)
    try:
        return AuditLog.objects.create(
            actor=actor if getattr(actor, "is_authenticated", False) else None,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id else "",
            outcome=outcome,
            request_id=request_id or "",
            ip_address=ip,
            metadata=_scrub(metadata or {}),
        )
    except Exception:  # pragma: no cover - audit must never break the request
        logger.exception("Failed to write audit log for action=%s", action)
        return None
