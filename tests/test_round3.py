"""Tests for calendar ICS feeds, task comments and task CSV export."""
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.calendar_manager.ics import build_calendar, escape_text, fold_line
from apps.calendar_manager.models import CalendarEvent
from apps.calendar_manager.services import get_calendar_feed_token
from apps.tasks.models import Task, TaskComment

pytestmark = pytest.mark.django_db


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _event(user, **kwargs):
    start = kwargs.pop("start", timezone.now() + timedelta(hours=1))
    end = kwargs.pop("end", start + timedelta(hours=1))
    return CalendarEvent.objects.create(
        owner=user, title=kwargs.pop("title", "Team sync"),
        start=start, end=end, **kwargs
    )


# --- ICS serialisation -------------------------------------------------------
def test_ics_escape_and_fold():
    assert escape_text("a, b; c\\d") == "a\\, b\\; c\\\\d"
    assert escape_text("line1\nline2") == "line1\\nline2"
    long_line = "SUMMARY:" + "x" * 200
    folded = fold_line(long_line)
    assert "\r\n " in folded
    assert folded.replace("\r\n ", "") == long_line


def test_build_calendar_contains_events(user):
    event = _event(user, title="Design review", location="Room, 1; B")
    body = build_calendar([event])
    assert body.startswith("BEGIN:VCALENDAR\r\n")
    assert body.rstrip().endswith("END:VCALENDAR")
    assert "BEGIN:VEVENT" in body
    assert f"UID:event-{event.pk}@nexamind" in body
    assert "SUMMARY:Design review" in body
    assert "LOCATION:Room\\, 1\\; B" in body
    assert body.count("DTSTART") == 1


def test_recurring_event_emits_rrule(user):
    event = _event(user, recurrence="weekly")
    body = build_calendar([event])
    assert "RRULE:FREQ=WEEKLY" in body


# --- Export & feed views -----------------------------------------------------
def test_calendar_export_download(user):
    _event(user, title="Export me")
    response = _client(user).get("/calendar/export.ics")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/calendar")
    assert "attachment" in response["Content-Disposition"]
    assert b"SUMMARY:Export me" in response.content


def test_calendar_feed_public_and_token_scoped(user):
    _event(user, title="Feed event")
    token = get_calendar_feed_token(user)
    # No authentication required for the token-addressed feed.
    ok = Client().get(f"/calendar/feed/{token}.ics")
    assert ok.status_code == 200
    assert b"SUMMARY:Feed event" in ok.content

    assert Client().get("/calendar/feed/not-a-real-token.ics").status_code == 404


def test_calendar_feed_reset_invalidates_old_token(user):
    old = get_calendar_feed_token(user)
    assert Client().get(f"/calendar/feed/{old}.ics").status_code == 200

    response = _client(user).post("/calendar/feed/reset/")
    assert response.status_code == 302
    assert Client().get(f"/calendar/feed/{old}.ics").status_code == 404

    new = get_calendar_feed_token(user)
    assert new != old
    assert Client().get(f"/calendar/feed/{new}.ics").status_code == 200


def test_calendar_view_shows_feed_url(user):
    response = _client(user).get("/calendar/")
    assert response.status_code == 200
    token = get_calendar_feed_token(user)
    assert f"/calendar/feed/{token}.ics".encode() in response.content


# --- Task comments -----------------------------------------------------------
def test_comment_add_and_delete(user):
    task = Task.objects.create(owner=user, title="Discussed task")
    client = _client(user)
    response = client.post(f"/tasks/{task.pk}/comments/add/", {"body": "First!"})
    assert response.status_code == 302
    comment = TaskComment.objects.get(task=task)
    assert comment.body == "First!"
    assert comment.author == user
    assert task.activity.filter(action="commented").exists()

    client.post(f"/tasks/{task.pk}/comments/{comment.pk}/delete/")
    assert not TaskComment.objects.filter(pk=comment.pk).exists()


def test_empty_comment_rejected(user):
    task = Task.objects.create(owner=user, title="Task")
    _client(user).post(f"/tasks/{task.pk}/comments/add/", {"body": "   "})
    assert not TaskComment.objects.filter(task=task).exists()


def test_task_detail_renders_discussion(user):
    task = Task.objects.create(owner=user, title="With discussion")
    TaskComment.objects.create(task=task, author=user, body="Rendered note")
    response = _client(user).get(f"/tasks/{task.pk}/")
    assert response.status_code == 200
    assert b"Discussion" in response.content
    assert b"Rendered note" in response.content


def test_cannot_comment_on_others_task(user, other_user):
    task = Task.objects.create(owner=other_user, title="Private")
    response = _client(user).post(f"/tasks/{task.pk}/comments/add/", {"body": "hi"})
    assert response.status_code == 404


# --- CSV export --------------------------------------------------------------
def test_task_csv_export(user):
    Task.objects.create(owner=user, title="Alpha", priority=Task.Priority.HIGH)
    response = _client(user).get("/tasks/export.csv")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    content = response.content.decode()
    assert "Title,Status,Priority" in content
    assert "Alpha" in content


def test_export_json_includes_task_comments(user):
    from apps.accounts.export import build_export_json

    task = Task.objects.create(owner=user, title="Portable")
    TaskComment.objects.create(task=task, author=user, body="portable note")
    data = build_export_json(user)
    assert any(c["body"] == "portable note" for c in data["task_comments"])
