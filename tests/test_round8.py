"""Round 8: integration step-up security + WhatsApp, LinkedIn and Facebook."""
import hashlib
import hmac
import json
from unittest import mock

import pytest
from django.conf import settings
from django.test import Client, override_settings

from apps.integrations import security, whatsapp
from apps.integrations.models import Integration, WhatsAppMessage

pytestmark = pytest.mark.django_db


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _nexamind(**extra):
    cfg = dict(settings.NEXAMIND)
    cfg.update(extra)
    return override_settings(NEXAMIND=cfg)


# --- Step-up security --------------------------------------------------------
def test_connect_requires_step_up(user):
    client = _client(user)
    response = client.get("/integrations/github/connect/")
    assert response.status_code == 302
    assert response.url == "/integrations/step-up/"


def test_step_up_with_password_then_resumes(user):
    client = _client(user)
    client.get("/integrations/github/connect/")
    response = client.post("/integrations/step-up/", {"password": "test-pass-123"})
    assert response.status_code == 302
    assert response.url == "/integrations/github/connect/"
    assert client.session.get(security.STEP_UP_SESSION_KEY)


def test_step_up_wrong_password(user):
    client = _client(user)
    client.get("/integrations/github/connect/")
    response = client.post("/integrations/step-up/", {"password": "nope"})
    assert response.status_code == 200
    assert not client.session.get(security.STEP_UP_SESSION_KEY)


def test_step_up_uses_totp_when_enabled(user):
    from types import SimpleNamespace

    from apps.accounts.models import UserProfile

    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.totp_enabled = True
    profile.save(update_fields=["totp_enabled"])
    dummy = SimpleNamespace(user=user)
    with mock.patch("apps.integrations.security.tfa.verify_any", return_value=True) as m:
        ok, error = security.verify_challenge(dummy, code="123456")
    assert ok and error == ""
    m.assert_called_once()


def test_step_up_password_branch_when_no_totp(user):
    from types import SimpleNamespace

    dummy = SimpleNamespace(user=user)
    ok, _ = security.verify_challenge(dummy, password="test-pass-123")
    assert ok
    bad, _ = security.verify_challenge(dummy, password="wrong")
    assert not bad


def test_disconnect_requires_step_up(user):
    Integration.objects.create(user=user, provider="github", status=Integration.Status.CONNECTED)
    client = _client(user)
    response = client.post("/integrations/github/disconnect/")
    assert response.status_code == 302
    assert response.url == "/integrations/step-up/"
    assert Integration.objects.filter(user=user, provider="github").exists()


def test_disconnect_after_step_up_removes(user):
    Integration.objects.create(user=user, provider="github", status=Integration.Status.CONNECTED)
    client = _client(user)
    client.get("/integrations/step-up/")
    client.post("/integrations/step-up/", {"password": "test-pass-123"})
    response = client.post("/integrations/github/disconnect/")
    assert response.status_code == 302
    assert not Integration.objects.filter(user=user, provider="github").exists()


# --- Provider catalog --------------------------------------------------------
def test_center_lists_new_providers(user):
    client = _client(user)
    response = client.get("/integrations/")
    assert response.status_code == 200
    for label in [b"WhatsApp", b"LinkedIn", b"Facebook"]:
        assert label in response.content


def test_linkedin_and_facebook_specs_unconfigured_by_default():
    from apps.integrations.providers import get_provider_spec

    for key in ("linkedin", "facebook"):
        spec = get_provider_spec(key)
        assert spec.key == key
        assert spec.configured is False


# --- WhatsApp ----------------------------------------------------------------
def test_whatsapp_connect_requires_configuration(user):
    client = _client(user)
    client.get("/integrations/whatsapp/connect/")
    client.post("/integrations/step-up/", {"password": "test-pass-123"})
    with _nexamind(WHATSAPP_TOKEN="", WHATSAPP_PHONE_NUMBER_ID=""):
        response = client.post("/integrations/whatsapp/connect/", {"number": "+1"})
    assert response.status_code == 302
    assert not Integration.objects.filter(user=user, provider="whatsapp").exists()


def test_whatsapp_connect_enables_messaging(user):
    client = _client(user)
    client.get("/integrations/whatsapp/connect/")
    client.post("/integrations/step-up/", {"password": "test-pass-123"})
    with _nexamind(WHATSAPP_TOKEN="tok", WHATSAPP_PHONE_NUMBER_ID="123",
                   WHATSAPP_DISPLAY_NUMBER="+15550000"):
        response = client.post("/integrations/whatsapp/connect/", {"number": "+15551111"})
    assert response.status_code == 302
    integration = Integration.objects.get(user=user, provider="whatsapp")
    assert integration.status == Integration.Status.CONNECTED
    assert integration.external_account == "+15551111"


def test_whatsapp_send_records_outbound(user):
    Integration.objects.create(user=user, provider="whatsapp", status=Integration.Status.CONNECTED)
    client = _client(user)
    fake = mock.Mock(status_code=200)
    fake.json.return_value = {"messages": [{"id": "wamid.1"}]}
    with _nexamind(WHATSAPP_TOKEN="tok", WHATSAPP_PHONE_NUMBER_ID="123"), \
            mock.patch("apps.integrations.whatsapp.requests.post", return_value=fake) as post:
        response = client.post("/integrations/whatsapp/send/", {"to": "+15551212", "body": "Hi"})
    assert response.status_code == 302
    assert WhatsAppMessage.objects.filter(user=user, direction="outbound", body="Hi").exists()
    post.assert_called_once()


def test_whatsapp_webhook_verifies_token():
    client = Client()
    with _nexamind(WHATSAPP_VERIFY_TOKEN="verify-me"):
        ok = client.get("/integrations/whatsapp/webhook/",
                        {"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                         "hub.challenge": "abc123"})
        bad = client.get("/integrations/whatsapp/webhook/",
                         {"hub.mode": "subscribe", "hub.verify_token": "wrong"})
    assert ok.status_code == 200 and ok.content == b"abc123"
    assert bad.status_code == 403


def _signed(payload: dict, secret: str):
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return body, sig


def test_whatsapp_webhook_rejects_bad_signature(user):
    Integration.objects.create(user=user, provider="whatsapp", status=Integration.Status.CONNECTED)
    with _nexamind(WHATSAPP_APP_SECRET="s3cr3t"):
        body, _ = _signed({"entry": []}, "s3cr3t")
        response = Client().post("/integrations/whatsapp/webhook/", body,
                                 content_type="application/json",
                                 HTTP_X_HUB_SIGNATURE_256="sha256=deadbeef")
    assert response.status_code == 403


def test_whatsapp_webhook_stores_inbound(user):
    integration = Integration.objects.create(
        user=user, provider="whatsapp", status=Integration.Status.CONNECTED)
    payload = {"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": "447700900000", "profile": {"name": "Ada"}}],
        "messages": [{"from": "447700900000", "id": "wamid.1", "type": "text",
                      "text": {"body": "Hello NexaMind"}}],
    }}]}]}
    with _nexamind(WHATSAPP_APP_SECRET="s3cr3t"):
        body, sig = _signed(payload, "s3cr3t")
        response = Client().post("/integrations/whatsapp/webhook/", body,
                                 content_type="application/json",
                                 HTTP_X_HUB_SIGNATURE_256=sig)
    assert response.status_code == 200 and response.json()["received"] == 1
    message = WhatsAppMessage.objects.get(integration=integration)
    assert message.body == "Hello NexaMind" and message.contact_name == "Ada"


def test_whatsapp_is_configured_flag(user):
    with _nexamind(WHATSAPP_TOKEN="", WHATSAPP_PHONE_NUMBER_ID=""):
        assert whatsapp.is_configured() is False
    with _nexamind(WHATSAPP_TOKEN="t", WHATSAPP_PHONE_NUMBER_ID="1"):
        assert whatsapp.is_configured() is True


# --- Providers configured ----------------------------------------------------
def test_linkedin_connect_when_configured_redirects_to_provider(user):
    client = _client(user)
    client.get("/integrations/linkedin/connect/")
    client.post("/integrations/step-up/", {"password": "test-pass-123"})
    with _nexamind(LINKEDIN_CLIENT_ID="cid", LINKEDIN_CLIENT_SECRET="secret"):
        response = client.get("/integrations/linkedin/connect/")
    assert response.status_code == 302
    assert response.url.startswith("https://www.linkedin.com/oauth/v2/authorization")


def test_facebook_provider_spec(user):
    from apps.integrations.providers import get_provider_spec

    spec = get_provider_spec("facebook")
    assert "facebook.com" in spec.authorize_url
    assert "public_profile" in spec.scopes
