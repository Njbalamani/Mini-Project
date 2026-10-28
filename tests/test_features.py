"""Tests for API tokens, 2FA, data export, bulk actions, slash commands, recurrence."""
import io
import json
import zipfile

import pytest
import pyotp
from django.test import Client
from django.utils import timezone
from rest_framework.authtoken.models import Token

from apps.accounts import twofactor as tfa
from apps.ai_assistant.services.assistant import generate_reply, get_or_create_conversation
from apps.ai_assistant.services.commands import execute
from apps.tasks.models import Task
from apps.tasks.services import create_task, set_status

pytestmark = pytest.mark.django_db


def _client(user):
    client = Client()
    client.force_login(user)
    return client


# --- Recurring tasks ---------------------------------------------------------
def test_recurring_task_spawns_next_occurrence(user):
    due = timezone.now() + timezone.timedelta(days=1)
    task = create_task(user, title="Standup", due_date=due,
                       recurrence=Task.Recurrence.DAILY)
    set_status(task, Task.Status.DONE, actor=user)
    spawned = Task.objects.filter(owner=user, title="Standup").exclude(pk=task.pk)
    assert spawned.count() == 1
    nxt = spawned.first()
    assert nxt.status == Task.Status.TODO
    assert nxt.due_date.date() == (due + timezone.timedelta(days=1)).date()
    assert nxt.recurrence == Task.Recurrence.DAILY


def test_non_recurring_task_does_not_spawn(user):
    task = create_task(user, title="One-off")
    set_status(task, Task.Status.DONE, actor=user)
    assert Task.objects.filter(owner=user).count() == 1


# --- Bulk actions ------------------------------------------------------------
def test_bulk_complete_multiple_tasks(user):
    a = create_task(user, title="A")
    b = create_task(user, title="B")
    response = _client(user).post("/tasks/bulk/", {
        "ids": [a.pk, b.pk], "action": "complete", "next": "/tasks/",
    })
    assert response.status_code == 302
    a.refresh_from_db(); b.refresh_from_db()
    assert a.status == Task.Status.DONE
    assert b.status == Task.Status.DONE


def test_bulk_does_not_touch_other_users_tasks(user, other_user):
    mine = create_task(user, title="Mine")
    theirs = create_task(other_user, title="Theirs")
    _client(user).post("/tasks/bulk/", {"ids": [mine.pk, theirs.pk], "action": "complete"})
    theirs.refresh_from_db()
    assert theirs.status != Task.Status.DONE


# --- Slash commands ----------------------------------------------------------
def test_slash_task_command_creates_task(user):
    convo = get_or_create_conversation(user)
    result = generate_reply(user, convo, "/task Prepare the demo")
    assert result["ok"] is True
    assert "Prepare the demo" in result["assistant_message"].content
    assert Task.objects.filter(owner=user, title="Prepare the demo").exists()
    assert result["link"]["url"]


def test_slash_summarize_command(user):
    create_task(user, title="Summarise me")
    result = execute(user, "/summarize")
    assert "open tasks" in result["reply"]


def test_unknown_slash_command_returns_help(user):
    result = execute(user, "/frobnicate things")
    assert "Unknown command" in result["reply"]


def test_non_command_returns_none(user):
    assert execute(user, "hello there") is None


# --- Two-factor authentication ----------------------------------------------
def test_totp_setup_and_login_challenge(user):
    client = _client(user)
    assert client.get("/accounts/two-factor/setup/").status_code == 200

    user.profile.refresh_from_db()
    secret = tfa._decrypt_secret(user.profile.totp_secret)
    response = client.post("/accounts/two-factor/setup/", {"code": pyotp.TOTP(secret).now()})
    assert response.status_code == 200
    user.profile.refresh_from_db()
    assert user.profile.totp_enabled is True
    assert user.profile.totp_backup_codes

    client.logout()
    assert client.login(email=user.email, password="test-pass-123")
    guarded = client.get("/app/")
    assert guarded.status_code == 302
    assert "/accounts/two-factor/verify/" in guarded["Location"]

    challenge = _client(user).post(
        "/accounts/two-factor/verify/", {"code": pyotp.TOTP(tfa._decrypt_secret(_fresh_secret(user))).now()}
    ) if False else None
    # complete challenge on the same client/session
    client.post("/accounts/two-factor/verify/", {"code": pyotp.TOTP(_secret(user)).now()})
    assert client.get("/app/").status_code == 200


def _secret(user):
    return tfa._decrypt_secret(user.profile.totp_secret)


def test_backup_codes_single_use(user):
    user.profile.totp_secret = tfa.encrypt_secret(tfa.generate_secret())
    user.profile.totp_enabled = True
    user.profile.save()
    codes = tfa.generate_backup_codes(user.profile)
    user.profile.refresh_from_db()
    assert tfa.verify_backup_code(user.profile, codes[0]) is True
    assert tfa.verify_backup_code(user.profile, codes[0]) is False


# --- API tokens --------------------------------------------------------------
def test_api_tokens_page_creates_token(user):
    response = _client(user).get("/accounts/api-tokens/")
    assert response.status_code == 200
    assert Token.objects.filter(user=user).exists()


def test_api_token_regenerate_changes_key(user):
    old_key = Token.objects.create(user=user).key
    response = _client(user).post("/accounts/api-tokens/regenerate/")
    assert response.status_code == 302
    assert Token.objects.get(user=user).key != old_key


def test_token_authenticates_api_request(user):
    token = Token.objects.create(user=user)
    response = Client().get("/api/v1/accounts/me/", HTTP_AUTHORIZATION=f"Token {token.key}")
    assert response.status_code == 200


# --- Data export -------------------------------------------------------------
def test_data_export_json(user):
    create_task(user, title="Exportable")
    response = _client(user).get("/accounts/export/")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    payload = json.loads(response.content)
    assert "Exportable" in [t["title"] for t in payload["tasks"]]


def test_data_export_zip(user):
    create_task(user, title="Zip me")
    response = _client(user).get("/accounts/export/?format=zip")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    assert "export.json" in archive.namelist()
    data = json.loads(archive.read("export.json"))
    assert any(t["title"] == "Zip me" for t in data["tasks"])


# --- Template rendering smoke ------------------------------------------------
def test_new_pages_render(user):
    create_task(user, title="Render me")
    client = _client(user)
    for path in [
        "/accounts/two-factor/",
        "/accounts/two-factor/setup/",
        "/accounts/api-tokens/",
        "/accounts/data/",
        "/tasks/?view=list",
        "/tasks/?view=kanban",
        "/assistant/",
        "/app/",
    ]:
        response = client.get(path)
        assert response.status_code == 200, f"{path} -> {response.status_code}"


def test_task_form_renders_recurrence(user):
    response = _client(user).get("/tasks/create/")
    assert response.status_code == 200
    content = response.content.decode()
    assert "recurrence" in content
    assert "Repeat until" in content


# --- Assistant "Ask AI" entry point ------------------------------------------
def test_dashboard_ask_ai_button_posts_new_conversation(user):
    """The dashboard 'Ask AI' control must POST to new_conversation (not GET)."""
    client = _client(user)
    html = client.get("/app/").content.decode()
    assert 'action="/assistant/new/"' in html
    assert "Ask AI" in html

    response = client.post("/assistant/new/")
    assert response.status_code == 302
    assert response.url.startswith("/assistant/c/")

    # new_conversation is POST-only; a bare GET must not silently 200.
    assert client.get("/assistant/new/").status_code == 405

