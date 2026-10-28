"""Tests for Round 6: comments/saved-view APIs, tag management and digest."""
import pytest
from django.test import Client
from django.utils import timezone

from apps.notifications.models import Notification
from apps.notifications.services import build_digest
from apps.tasks.models import SavedTaskFilter, Tag, Task, TaskComment

pytestmark = pytest.mark.django_db


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _auth(user):
    from rest_framework.authtoken.models import Token

    token = Token.objects.create(user=user)
    client = Client()
    client.defaults["HTTP_AUTHORIZATION"] = f"Token {token.key}"
    return client


# --- Task comments API -------------------------------------------------------
def test_api_comment_create_and_list(user):
    task = Task.objects.create(owner=user, title="Discuss me")
    client = _auth(user)
    created = client.post("/api/v1/tasks/comments/", {
        "task": task.pk, "body": "First!",
    }, content_type="application/json")
    assert created.status_code == 201, created.content
    body = created.json()
    assert body["body"] == "First!"
    assert body["author_name"]

    listing = client.get(f"/api/v1/tasks/comments/?task={task.pk}")
    assert [c["body"] for c in listing.json()["results"]] == ["First!"]


def test_api_comment_rejects_other_users_task(user, other_user):
    theirs = Task.objects.create(owner=other_user, title="Not yours")
    client = _auth(user)
    response = client.post("/api/v1/tasks/comments/", {
        "task": theirs.pk, "body": "sneaky",
    }, content_type="application/json")
    assert response.status_code == 400
    assert not TaskComment.objects.exists()


def test_api_comment_list_is_scoped(user, other_user):
    theirs = Task.objects.create(owner=other_user, title="Theirs")
    TaskComment.objects.create(task=theirs, author=other_user, body="private")
    client = _auth(user)
    response = client.get("/api/v1/tasks/comments/")
    assert response.json()["results"] == []


# --- Saved view API ----------------------------------------------------------
def test_api_saved_view_crud(user):
    client = _auth(user)
    created = client.post("/api/v1/saved-task-filters/", {
        "name": "High work", "query": {"priority": "high", "status": "todo"},
    }, content_type="application/json")
    assert created.status_code == 201, created.content
    body = created.json()
    assert "priority=high" in body["query_string"]
    filter_id = body["id"]

    assert SavedTaskFilter.objects.get(owner=user, name="High work")

    updated = client.patch(f"/api/v1/saved-task-filters/{filter_id}/", {
        "name": "Renamed",
    }, content_type="application/json")
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"

    deleted = client.delete(f"/api/v1/saved-task-filters/{filter_id}/")
    assert deleted.status_code == 204
    assert not SavedTaskFilter.objects.filter(pk=filter_id).exists()


def test_api_saved_views_are_scoped(user, other_user):
    theirs = SavedTaskFilter.objects.create(owner=other_user, name="Theirs")
    client = _auth(user)
    assert client.get("/api/v1/saved-task-filters/").json()["results"] == []
    assert client.delete(f"/api/v1/saved-task-filters/{theirs.pk}/").status_code == 404


# --- Tag management page -----------------------------------------------------
def test_tag_page_lists_and_creates(user):
    Tag.objects.create(owner=user, name="Existing")
    client = _client(user)
    page = client.get("/tasks/tags/")
    assert page.status_code == 200
    assert b"Existing" in page.content

    created = client.post("/tasks/tags/", {"name": "Fresh", "color": "#123456"})
    assert created.status_code == 302
    tag = Tag.objects.get(owner=user, name="Fresh")
    assert tag.color == "#123456"


def test_tag_page_rejects_duplicates(user):
    Tag.objects.create(owner=user, name="Dup")
    response = _client(user).post("/tasks/tags/", {"name": "dup", "color": "#123456"})
    assert response.status_code == 200
    assert Tag.objects.filter(owner=user).count() == 1


def test_tag_edit_and_delete(user):
    tag = Tag.objects.create(owner=user, name="Old", color="#111111")
    client = _client(user)
    edited = client.post(f"/tasks/tags/{tag.pk}/edit/", {"name": "New", "color": "#222222"})
    assert edited.status_code == 302
    tag.refresh_from_db()
    assert tag.name == "New" and tag.color == "#222222"

    deleted = client.post(f"/tasks/tags/{tag.pk}/delete/")
    assert deleted.status_code == 302
    assert not Tag.objects.filter(pk=tag.pk).exists()


def test_tags_page_is_scoped(user, other_user):
    theirs = Tag.objects.create(owner=other_user, name="Theirs")
    response = _client(user).post(f"/tasks/tags/{theirs.pk}/edit/", {"name": "Hack"})
    assert response.status_code == 404


# --- Digest ------------------------------------------------------------------
def test_build_digest_counts(user):
    Task.objects.create(owner=user, title="Open one")
    Task.objects.create(owner=user, title="Overdue", due_date=timezone.now() - timezone.timedelta(days=2))
    done = Task.objects.create(owner=user, title="Finished", status=Task.Status.DONE)
    Task.objects.filter(pk=done.pk).update(completed_at=timezone.now())

    digest = build_digest(user, days=7)
    assert digest["open_count"] == 2
    assert digest["overdue_count"] == 1
    assert digest["completed_count"] == 1
    assert "Overdue" in digest["overdue_titles"]
    assert "2 open tasks" in digest["message"]


def test_digest_preview_page(user):
    Task.objects.create(owner=user, title="See me")
    response = _client(user).get("/notifications/digest/")
    assert response.status_code == 200
    assert b"Digest preview" in response.content
    assert b"Open tasks" in response.content


def test_digest_send_creates_notification(user):
    response = _client(user).post("/notifications/digest/send/")
    assert response.status_code == 302
    note = Notification.objects.get(user=user)
    assert note.type == "system"
    assert "open tasks" in note.message


def test_digest_send_respects_preference(user):
    from apps.accounts.models import UserPreference

    UserPreference.objects.update_or_create(
        user=user, defaults={"in_app_notifications": False}
    )
    response = _client(user).post("/notifications/digest/send/")
    assert response.status_code == 302
    assert not Notification.objects.filter(user=user).exists()
