"""Tests for Round 7: workflow webhooks, calendar drag-drop, tag autocomplete."""
import pytest
from django.test import Client
from django.utils import timezone

from apps.calendar_manager.models import CalendarEvent
from apps.notifications.models import Notification
from apps.tasks.forms import TaskForm
from apps.tasks.models import Tag
from apps.workflow_automation.models import (
    ActionType,
    ConditionType,
    TriggerType,
    Workflow,
    WorkflowAction,
    WorkflowCondition,
    WorkflowTrigger,
)

pytestmark = pytest.mark.django_db


def _make_webhook_workflow(user, enabled=True, with_token=False):
    wf = Workflow.objects.create(owner=user, name="Inbound", is_enabled=enabled)
    WorkflowTrigger.objects.create(workflow=wf, trigger_type=TriggerType.WEBHOOK)
    WorkflowCondition.objects.create(workflow=wf, condition_type=ConditionType.ALWAYS)
    WorkflowAction.objects.create(
        workflow=wf, action_type=ActionType.CREATE_NOTIFICATION
    )
    if with_token:
        wf.ensure_webhook_token()
    return wf


# --- Workflow webhook --------------------------------------------------------
def test_webhook_unknown_token_404():
    response = Client().post(
        "/workflows/hooks/nope/", "{}", content_type="application/json"
    )
    assert response.status_code == 404


def test_webhook_requires_post(user):
    wf = _make_webhook_workflow(user, with_token=True)
    response = Client().get(f"/workflows/hooks/{wf.webhook_token}/")
    assert response.status_code == 405


def test_webhook_disabled_returns_409(user):
    wf = _make_webhook_workflow(user, enabled=False, with_token=True)
    response = Client().post(
        f"/workflows/hooks/{wf.webhook_token}/", "{}", content_type="application/json"
    )
    assert response.status_code == 409


def test_webhook_runs_workflow_with_payload(user):
    wf = _make_webhook_workflow(user, with_token=True)
    response = Client().post(
        f"/workflows/hooks/{wf.webhook_token}/",
        {"title": "Deploy finished", "message": "All services healthy"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["ok"] is True and body["status"] == "succeeded"
    note = Notification.objects.get(user=user)
    assert note.title == "Deploy finished"
    assert note.message == "All services healthy"
    assert wf.executions.count() == 1


def test_webhook_idempotency_header_dedupes(user):
    wf = _make_webhook_workflow(user, with_token=True)
    client = Client()
    payload = {"title": "Ping"}
    first = client.post(
        f"/workflows/hooks/{wf.webhook_token}/", payload,
        content_type="application/json", HTTP_X_NEXAMIND_IDEMPOTENCY="abc-123",
    )
    second = client.post(
        f"/workflows/hooks/{wf.webhook_token}/", payload,
        content_type="application/json", HTTP_X_NEXAMIND_IDEMPOTENCY="abc-123",
    )
    assert first.json()["execution"] == second.json()["execution"]
    assert wf.executions.count() == 1


def test_webhook_regenerate_rotates_token(user):
    wf = _make_webhook_workflow(user, with_token=True)
    old = wf.webhook_token
    client = Client()
    client.force_login(user)
    response = client.post(f"/workflows/{wf.pk}/webhook/regenerate/")
    assert response.status_code == 302
    wf.refresh_from_db()
    assert wf.webhook_token and wf.webhook_token != old


def test_webhook_detail_page_creates_and_shows_token(user):
    wf = _make_webhook_workflow(user)
    assert not wf.webhook_token
    client = Client()
    client.force_login(user)
    response = client.get(f"/workflows/{wf.pk}/")
    assert response.status_code == 200
    wf.refresh_from_db()
    assert wf.webhook_token
    assert wf.webhook_token.encode() in response.content


# --- Calendar drag-and-drop --------------------------------------------------
def _event(user, days=0):
    start = timezone.now().replace(minute=0, second=0, microsecond=0) + timezone.timedelta(days=days)
    return CalendarEvent.objects.create(
        owner=user, title="Standup", start=start, end=start + timezone.timedelta(hours=1)
    )


def test_event_move_shifts_whole_days(user):
    event = _event(user)
    start = timezone.localtime(event.start)
    target = (start + timezone.timedelta(days=2)).date()
    client = Client()
    client.force_login(user)
    response = client.post(f"/calendar/{event.pk}/move/", {"date": target.isoformat()})
    assert response.status_code == 200
    event.refresh_from_db()
    moved = timezone.localtime(event.start)
    assert moved.date() == target
    assert moved.hour == start.hour and moved.minute == start.minute


def test_event_move_invalid_date(user):
    event = _event(user)
    client = Client()
    client.force_login(user)
    response = client.post(f"/calendar/{event.pk}/move/", {"date": "not-a-date"})
    assert response.status_code == 400


def test_event_move_same_day_is_noop(user):
    event = _event(user)
    original = event.start
    client = Client()
    client.force_login(user)
    response = client.post(
        f"/calendar/{event.pk}/move/",
        {"date": timezone.localtime(event.start).date().isoformat()},
    )
    assert response.status_code == 200 and response.json().get("unchanged") is True
    event.refresh_from_db()
    assert event.start == original


def test_event_move_scoped_to_owner(user, other_user):
    event = _event(other_user)
    client = Client()
    client.force_login(user)
    response = client.post(
        f"/calendar/{event.pk}/move/", {"date": timezone.localdate().isoformat()}
    )
    assert response.status_code == 404


# --- Tag autocomplete --------------------------------------------------------
def test_form_exposes_tag_suggestions(user):
    Tag.objects.create(owner=user, name="work")
    Tag.objects.create(owner=user, name="urgent")
    form = TaskForm(user=user)
    raw = form.fields["tags"].widget.attrs["data-suggestions"]
    assert "work" in raw and "urgent" in raw


def test_form_suggestions_are_scoped(user, other_user):
    Tag.objects.create(owner=other_user, name="secret")
    form = TaskForm(user=user)
    assert "secret" not in form.fields["tags"].widget.attrs["data-suggestions"]


def test_create_page_renders_suggestions(user):
    Tag.objects.create(owner=user, name="backend")
    client = Client()
    client.force_login(user)
    response = client.get("/tasks/create/")
    assert response.status_code == 200
    assert b"data-suggestions" in response.content
