"""WhatsApp Business Cloud API integration.

Sending and receiving messages is supported. WhatsApp does **not** expose an API
for placing or receiving voice/video calls, so calling is handled separately by
the in-app WebRTC feature. Credentials (a long-lived Cloud API token, the phone
number id, the webhook verify token and the app secret) are configured server
side via the NEXAMIND settings block, never in the browser.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from uuid import uuid4

import requests

logger = logging.getLogger("nexamind.integrations")

GRAPH_VERSION = "v21.0"


class WhatsAppError(Exception):
    pass


def _cfg(key, default=""):
    from . import credentials

    return credentials.get("whatsapp", key, default)


def is_configured():
    return bridge_configured() or bool(_cfg("token") and _cfg("phone_number_id"))


def bridge_configured():
    """True when the unofficial QR bridge URL + shared secret are set."""
    return bool(_cfg("bridge_url")) and bool(_cfg("bridge_secret"))


def _bridge_url(path=""):
    return _cfg("bridge_url").rstrip("/") + path


def bridge_status():
    """Ask the bridge for its current state. Returns None if unreachable."""
    if not bridge_configured():
        return None
    try:
        resp = requests.get(_bridge_url("/qr"), timeout=5)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError):
        return {"status": "offline", "qr": None, "me": None, "error": "bridge unreachable"}


def request_pairing(number):
    """Ask the bridge to generate a pairing code for ``number``.

    Returns the code string. Raises WhatsAppError on failure.
    """
    if not bridge_configured():
        raise WhatsAppError("The QR bridge is not configured.")
    number = (number or "").strip()
    if not number:
        raise WhatsAppError("Enter your WhatsApp number with country code.")
    try:
        resp = requests.post(
            _bridge_url("/pair"),
            json={"number": number},
            headers={"x-bridge-secret": _cfg("bridge_secret")},
            timeout=20,
        )
    except requests.RequestException as exc:
        raise WhatsAppError(f"WhatsApp bridge unreachable: {exc}") from exc
    try:
        payload = resp.json()
    except ValueError:
        payload = {}
    if resp.status_code >= 400:
        raise WhatsAppError(payload.get("error", "Could not create a pairing code."))
    return payload.get("code", "")


def not_configured_message():
    return ("WhatsApp is not configured yet. An administrator must add either the "
            "Cloud API token + phone number id, or the QR bridge URL + secret, under "
            "Integrations → Provider credentials.")


def display_number():
    return _cfg("display_number", "")


def is_demo():
    """True when the simulator is enabled (no real messages leave the server)."""
    return str(_cfg("demo")).strip().lower() in {"1", "true", "yes", "on"}


def verify_token():
    return _cfg("verify_token", "")


def _app_secret():
    return _cfg("app_secret", "")


def verify_signature(payload_bytes, signature_header):
    """Validate Meta's X-Hub-Signature-256 HMAC. Fails closed when unset."""
    secret = _app_secret()
    if not secret:
        logger.warning("WHATSAPP_APP_SECRET is not set; rejecting unsigned webhook.")
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()
    provided = signature_header.split("=", 1)[1]
    return hmac.compare_digest(expected, provided)


def send_text(to, body):
    """Send a plain text message. Uses the QR bridge if configured, then the
    simulator, then the official Cloud API. Raises WhatsAppError."""
    if not is_configured():
        raise WhatsAppError(not_configured_message())
    if not to or not body:
        raise WhatsAppError("Both a recipient and a message are required.")
    if bridge_configured():
        try:
            resp = requests.post(
                _bridge_url("/send"),
                json={"to": to, "text": body[:4096]},
                headers={"x-bridge-secret": _cfg("bridge_secret")},
                timeout=20,
            )
        except requests.RequestException as exc:
            raise WhatsAppError(f"WhatsApp bridge unreachable: {exc}") from exc
        if resp.status_code >= 400:
            detail = resp.text
            try:
                detail = resp.json().get("error", detail)
            except ValueError:
                pass
            raise WhatsAppError(f"Bridge error: {detail}")
        return resp.json()
    if is_demo():
        return {"messaging_product": "whatsapp", "simulated": True,
                "contacts": [{"wa_id": to}],
                "messages": [{"id": f"wamid.demo.{uuid4().hex[:18]}"}]}
    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{_cfg('phone_number_id')}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": body[:4096]},
    }
    headers = {
        "Authorization": f"Bearer {_cfg('token')}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
    except requests.RequestException as exc:
        raise WhatsAppError(f"Network error contacting WhatsApp: {exc}") from exc
    if resp.status_code >= 400:
        raise WhatsAppError(f"WhatsApp API HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def parse_inbound(payload):
    """Extract inbound messages from a webhook notification payload."""
    results = []
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            contacts = {c.get("wa_id"): c.get("profile", {}).get("name", "")
                        for c in value.get("contacts", []) or []}
            for msg in value.get("messages", []) or []:
                sender = msg.get("from", "")
                text = ""
                if msg.get("type") == "text":
                    text = (msg.get("text") or {}).get("body", "")
                results.append({
                    "wa_id": sender,
                    "name": contacts.get(sender, ""),
                    "message_type": msg.get("type", "unknown"),
                    "body": text,
                    "external_id": msg.get("id", ""),
                    "timestamp": msg.get("timestamp", ""),
                    "raw": msg,
                })
    return results


def record_inbound(integration, sender, body, name="", message_type="text", raw=None):
    """Persist an inbound message against the owning user's integration."""
    from .models import WhatsAppMessage

    return WhatsAppMessage.objects.create(
        user=integration.user,
        integration=integration,
        direction=WhatsAppMessage.Direction.INBOUND,
        wa_id=sender,
        contact_name=name[:120],
        body=body,
        message_type=message_type,
        raw=raw or {},
    )


def record_outbound(integration, to, body):
    """Persist an outbound message we sent."""
    from .models import WhatsAppMessage

    return WhatsAppMessage.objects.create(
        user=integration.user,
        integration=integration,
        direction=WhatsAppMessage.Direction.OUTBOUND,
        wa_id=to,
        body=body,
        message_type="text",
    )
