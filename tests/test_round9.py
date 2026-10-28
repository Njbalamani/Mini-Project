"""Round 9: in-app encrypted provider credentials that unblock connecting."""
import pytest
from django.test import Client

from apps.integrations import credentials, whatsapp
from apps.integrations.models import Integration, ProviderConfig
from apps.integrations.providers import get_provider_spec

pytestmark = pytest.mark.django_db


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _staff_client(user):
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    return _client(user)


# --- Credential store --------------------------------------------------------
def test_secrets_are_encrypted_at_rest():
    credentials.set_values("google", data={"client_id": "cid-123"},
                           secrets_map={"client_secret": "super-secret"})
    cfg = ProviderConfig.objects.get(provider="google")
    assert "super-secret" not in cfg.secrets
    assert "cid-123" not in cfg.secrets
    assert credentials.get("google", "client_id") == "cid-123"
    assert credentials.get("google", "client_secret") == "super-secret"


def test_blank_values_do_not_overwrite():
    credentials.set_values("github", data={"client_id": "keep"}, secrets_map={})
    credentials.set_values("github", data={"client_id": ""}, secrets_map={})
    assert credentials.get("github", "client_id") == "keep"


def test_google_credentials_shared_by_gmail_and_calendar():
    credentials.set_values("google", data={"client_id": "gid"},
                           secrets_map={"client_secret": "gsecret"})
    assert get_provider_spec("gmail").configured
    assert get_provider_spec("google_calendar").configured
    assert get_provider_spec("gmail").client_id == "gid"


def test_env_fallback_when_no_db_override(settings):
    from copy import deepcopy

    from django.test import override_settings

    cfg = deepcopy(settings.NEXAMIND)
    cfg["GITHUB_CLIENT_ID"] = "env-id"
    cfg["GITHUB_CLIENT_SECRET"] = "env-secret"
    with override_settings(NEXAMIND=cfg):
        assert get_provider_spec("github").configured
    credentials.set_values("github", data={"client_id": "db-id"},
                           secrets_map={"client_secret": "db-secret"})
    assert credentials.get("github", "client_id") == "db-id"


def test_whatsapp_becomes_configured_from_store():
    assert not whatsapp.is_configured()
    credentials.set_values("whatsapp", data={"phone_number_id": "12345"},
                           secrets_map={"token": "EAAG..."})
    assert whatsapp.is_configured()
    assert whatsapp.display_number() == ""


# --- Credential admin page ---------------------------------------------------
def test_credentials_page_requires_staff(user):
    response = _client(user).get("/integrations/credentials/")
    assert response.status_code == 302
    assert response.url == "/integrations/"


def test_staff_can_save_and_clear(user):
    client = _staff_client(user)
    assert client.get("/integrations/credentials/").status_code == 200
    response = client.post("/integrations/credentials/", {
        "provider": "linkedin", "client_id": "li-id", "client_secret": "li-secret",
    })
    assert response.status_code == 302
    assert credentials.get("linkedin", "client_id") == "li-id"
    assert get_provider_spec("linkedin").configured

    response = client.post("/integrations/credentials/", {"provider": "linkedin",
                                                          "action": "clear"})
    assert response.status_code == 302
    assert not ProviderConfig.objects.filter(provider="linkedin").exists()


def test_configuring_google_enables_connect_redirect(user):
    credentials.set_values("google", data={"client_id": "cid"},
                           secrets_map={"client_secret": "csecret"})
    client = _staff_client(user)
    client.get("/integrations/gmail/connect/")
    response = client.post("/integrations/step-up/", {"password": "test-pass-123"})
    assert response.status_code == 302
    response = client.get("/integrations/gmail/connect/")
    assert response.status_code == 302
    assert response.url.startswith("https://accounts.google.com/o/oauth2/v2/auth")


def test_whatsapp_connect_works_after_credentials_saved(user):
    credentials.set_values("whatsapp",
                           data={"phone_number_id": "999", "display_number": "+1555"},
                           secrets_map={"token": "EAAG"})
    client = _client(user)
    client.get("/integrations/whatsapp/connect/")
    client.post("/integrations/step-up/", {"password": "test-pass-123"})
    response = client.post("/integrations/whatsapp/connect/", {"number": "+15550001"})
    assert response.status_code == 302
    integration = Integration.objects.get(user=user, provider="whatsapp")
    assert integration.status == Integration.Status.CONNECTED


# --- Simulator mode ----------------------------------------------------------
def test_demo_send_is_simulated_and_recorded(user, monkeypatch):
    credentials.set_values("whatsapp",
                           data={"phone_number_id": "999", "demo": "1"},
                           secrets_map={"token": "EAAG"})
    assert whatsapp.is_demo()

    def _boom(*_a, **kwargs):
        raise AssertionError("demo send must not touch the network")

    import apps.integrations.whatsapp as wa
    monkeypatch.setattr(wa.requests, "post", boom := (lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("network"))))
    result = whatsapp.send_text("15550001", "hello from demo")
    assert result.get("simulated") is True


def test_panel_shows_sent_message(user):
    credentials.set_values("whatsapp",
                           data={"phone_number_id": "999", "demo": "1"},
                           secrets_map={"token": "EAAG"})
    client = _client(user)
    client.get("/integrations/whatsapp/connect/")
    client.post("/integrations/step-up/", {"password": "test-pass-123"})
    client.post("/integrations/whatsapp/connect/", {"number": "15550001"})
    client.post("/integrations/whatsapp/send/", {"to": "15550001", "body": "hi there"})
    response = client.get("/integrations/whatsapp/panel/")
    assert response.status_code == 200
    assert b"hi there" in response.content
    assert b"Simulator mode" in response.content

