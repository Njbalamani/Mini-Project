"""Round 10: unofficial QR bridge mode for personal WhatsApp numbers."""
import hashlib
import hmac
import json

import pytest
from django.test import Client

from apps.integrations import credentials, whatsapp
from apps.integrations.models import Integration, WhatsAppMessage

pytestmark = pytest.mark.django_db


def _client(user):
    c = Client()
    c.force_login(user)
    return c


def _bridge_on():
    credentials.set_values("whatsapp", data={
        "bridge_url": "http://127.0.0.1:3100",
        "app_secret": "sign-me",
        "demo": "",
    }, secrets_map={"bridge_secret": "bridge-shared-secret"})


class _Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or json.dumps(self._payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise whatsapp.requests.HTTPError()


def test_bridge_configured_requires_url_and_secret():
    credentials.set_values("whatsapp", data={"bridge_url": "http://127.0.0.1:3100"},
                           secrets_map={})
    assert not whatsapp.bridge_configured()
    credentials.set_values("whatsapp", data={}, secrets_map={"bridge_secret": "s"})
    assert whatsapp.bridge_configured()
    assert whatsapp.is_configured()


def test_send_routes_through_bridge(monkeypatch):
    _bridge_on()
    calls = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["url"] = url
        calls["headers"] = headers
        calls["body"] = json
        return _Resp(200, {"ok": True})

    monkeypatch.setattr(whatsapp.requests, "post", fake_post)
    result = whatsapp.send_text("15551230000", "hello from bridge")
    assert result["ok"] is True
    assert calls["url"].endswith("/send")
    assert calls["headers"]["x-bridge-secret"] == "bridge-shared-secret"
    assert calls["body"]["to"] == "15551230000"


def test_send_surfaces_bridge_error(monkeypatch):
    _bridge_on()

    def fake_post(*a, **k):
        return _Resp(400, {"error": "bad number"})

    monkeypatch.setattr(whatsapp.requests, "post", fake_post)
    with pytest.raises(whatsapp.WhatsAppError):
        whatsapp.send_text("1", "hi")


def test_bridge_status_offline_when_unreachable(monkeypatch):
    _bridge_on()

    def boom(*a, **k):
        raise whatsapp.requests.ConnectionError("no route")

    monkeypatch.setattr(whatsapp.requests, "get", boom)
    assert whatsapp.bridge_status()["status"] == "offline"


def test_qr_status_endpoint(user):
    _bridge_on()
    response = _client(user).get("/integrations/whatsapp/qr/status/")
    assert response.status_code == 200
    assert response.json()["status"] in {"qr", "open", "offline", "connecting", "starting"}


def test_qr_status_endpoint(user):
    _bridge_on()
    response = _client(user).get("/integrations/whatsapp/qr/status/")
    assert response.status_code == 200


def test_request_pairing_code(monkeypatch):
    _bridge_on()

    def fake_post(url, json=None, headers=None, timeout=None):
        assert url.endswith("/pair")
        assert headers["x-bridge-secret"] == "bridge-shared-secret"
        return _Resp(200, {"ok": True, "code": "ABCD-EFGH"})

    monkeypatch.setattr(whatsapp.requests, "post", fake_post)
    assert whatsapp.request_pairing("15551230000") == "ABCD-EFGH"


def test_pair_endpoint_needs_step_up(user):
    _bridge_on()
    response = _client(user).post("/integrations/whatsapp/pair/", {"number": "15551230000"})
    assert response.status_code == 403
    assert response.json()["error"] == "step_up_required"


def test_pair_endpoint_after_step_up(user, monkeypatch):
    _bridge_on()
    monkeypatch.setattr(whatsapp.requests, "post",
                        lambda *a, **k: _Resp(200, {"code": "ABCD-EFGH"}))
    client = _client(user)
    client.post("/integrations/step-up/", {"password": "test-pass-123"})
    response = client.post("/integrations/whatsapp/pair/", {"number": "15551230000"})
    assert response.status_code == 200
    assert response.json()["code"] == "ABCD-EFGH"


def test_connect_page_shows_qr_when_bridge_configured(user):
    _bridge_on()
    client = _client(user)
    client.get("/integrations/whatsapp/connect/")
    client.post("/integrations/step-up/", {"password": "test-pass-123"})
    response = client.get("/integrations/whatsapp/connect/")
    assert response.status_code == 200
    assert b"Link with a code" in response.content
    assert b"whatsapp/pair/" in response.content


def _sign(payload, secret):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, sig


def test_app_secret_resolves_from_legacy_plaintext_data():
    """An app_secret stored in plain ``data`` (older rows) must still resolve."""
    _bridge_on()
    assert credentials.get("whatsapp", "app_secret") == "sign-me"
    assert whatsapp._app_secret() == "sign-me"


def test_bridge_inbound_webhook_accepts_plaintext_app_secret(user):
    _bridge_on()
    Integration.objects.create(user=user, provider="whatsapp",
                               status=Integration.Status.CONNECTED)
    payload = {"object": "whatsapp_business_account", "bridge": True, "entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": "15551230000", "profile": {"name": "Grace"}}],
        "messages": [{"from": "15551230000", "id": "wamid.b1", "type": "text",
                      "text": {"body": "hi via bridge"}}],
    }}]}]}
    body, sig = _sign(payload, "sign-me")
    response = Client().post("/integrations/whatsapp/webhook/", body,
                             content_type="application/json",
                             HTTP_X_HUB_SIGNATURE_256=sig)
    assert response.status_code == 200 and response.json()["received"] == 1
    assert WhatsAppMessage.objects.filter(user=user, body="hi via bridge").exists()


def test_bridge_inbound_webhook_rejects_bad_signature(user):
    _bridge_on()
    Integration.objects.create(user=user, provider="whatsapp",
                               status=Integration.Status.CONNECTED)
    body, _ = _sign({"entry": []}, "sign-me")
    response = Client().post("/integrations/whatsapp/webhook/", body,
                             content_type="application/json",
                             HTTP_X_HUB_SIGNATURE_256="sha256=deadbeef")
    assert response.status_code == 403
