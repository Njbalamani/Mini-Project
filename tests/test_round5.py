"""Tests for task tags/labels: web UI, filtering and the REST API."""
import pytest
from django.test import Client

from apps.tasks.models import Tag, Task
from apps.tasks.services import parse_tag_names, set_task_tags

pytestmark = pytest.mark.django_db


def _client(user):
    client = Client()
    client.force_login(user)
    return client


# --- Service helpers ---------------------------------------------------------
def test_parse_tag_names_dedupes_and_trims():
    assert parse_tag_names(" work , urgent,work ,, ") == ["work", "urgent"]


def test_parse_tag_names_caps_at_eight():
    raw = ",".join(f"t{i}" for i in range(20))
    assert len(parse_tag_names(raw)) == 8


def test_set_task_tags_creates_and_reuses(user):
    task = Task.objects.create(owner=user, title="Tagged")
    tags = set_task_tags(task, "work, urgent")
    assert {t.name for t in tags} == {"work", "urgent"}
    assert Task.objects.get(pk=task.pk).tags.count() == 2

    other = Task.objects.create(owner=user, title="Tagged again")
    set_task_tags(other, "work")
    assert Tag.objects.filter(owner=user).count() == 2


def test_tag_colours_are_stable(user):
    set_task_tags(Task.objects.create(owner=user, title="A"), "work")
    first = Tag.objects.get(owner=user, name="work").color
    tag = Tag.objects.create(owner=user, name="work2")
    set_task_tags(Task.objects.create(owner=user, title="B"), "work")
    assert Tag.objects.get(owner=user, name="work").color == first


# --- Web UI ------------------------------------------------------------------
def test_create_task_with_tags(user):
    response = _client(user).post("/tasks/create/", {
        "title": "Write report", "description": "",
        "status": "todo", "priority": "high", "category": "",
        "recurrence": "none", "tags": "work, urgent",
    })
    assert response.status_code == 302
    task = Task.objects.get(owner=user, title="Write report")
    assert {t.name for t in task.tags.all()} == {"work", "urgent"}


def test_edit_task_updates_tags(user):
    task = Task.objects.create(owner=user, title="Edit me")
    set_task_tags(task, "old")
    response = _client(user).post(f"/tasks/{task.pk}/edit/", {
        "title": "Edit me", "description": "",
        "status": "todo", "priority": "medium", "category": "",
        "recurrence": "none", "tags": "new, fresh",
    })
    assert response.status_code == 302
    assert {t.name for t in Task.objects.get(pk=task.pk).tags.all()} == {"new", "fresh"}


def test_detail_shows_tags(user):
    task = Task.objects.create(owner=user, title="Show tags")
    set_task_tags(task, "alpha")
    response = _client(user).get(f"/tasks/{task.pk}/")
    assert response.status_code == 200
    assert b"alpha" in response.content


def test_filter_by_tag(user):
    a = Task.objects.create(owner=user, title="Alpha task")
    b = Task.objects.create(owner=user, title="Beta task")
    set_task_tags(a, "alpha")
    set_task_tags(b, "beta")
    response = _client(user).get("/tasks/?tag=alpha")
    assert response.status_code == 200
    assert b"Alpha task" in response.content
    assert b"Beta task" not in response.content


def test_tags_are_scoped_to_owner(user, other_user):
    mine = Task.objects.create(owner=user, title="Mine")
    set_task_tags(mine, "shared")
    theirs = Task.objects.create(owner=other_user, title="Theirs")
    set_task_tags(theirs, "shared")
    assert Tag.objects.filter(owner=user, name="shared").count() == 1
    assert Tag.objects.filter(owner=other_user, name="shared").count() == 1


def test_recurring_task_copies_tags(user):
    task = Task.objects.create(
        owner=user, title="Daily", recurrence=Task.Recurrence.DAILY,
    )
    set_task_tags(task, "habit")
    from apps.tasks.services import spawn_next_occurrence

    nxt = spawn_next_occurrence(task)
    assert nxt is not None
    assert {t.name for t in nxt.tags.all()} == {"habit"}


# --- REST API ----------------------------------------------------------------
def _auth(user):
    from rest_framework.authtoken.models import Token

    token = Token.objects.create(user=user)
    client = Client()
    client.defaults["HTTP_AUTHORIZATION"] = f"Token {token.key}"
    return client


def test_api_creates_task_with_tags(user):
    client = _auth(user)
    response = client.post("/api/v1/tasks/", {
        "title": "API task", "priority": "high", "tag_names": ["api", "urgent"],
    }, content_type="application/json")
    assert response.status_code == 201, response.content
    body = response.json()
    assert {t["name"] for t in body["tags"]} == {"api", "urgent"}
    assert Task.objects.get(owner=user, title="API task").tags.count() == 2


def test_api_filters_tasks_by_tag(user):
    a = Task.objects.create(owner=user, title="Tagged")
    set_task_tags(a, "keep")
    client = _auth(user)
    response = client.get("/api/v1/tasks/?tag=keep")
    assert response.status_code == 200
    assert [t["title"] for t in response.json()["results"]] == ["Tagged"]


def test_api_tag_endpoint_is_scoped(user, other_user):
    Tag.objects.create(owner=other_user, name="theirs")
    client = _auth(user)
    response = client.get("/api/v1/tags/")
    assert response.status_code == 200
    assert response.json()["results"] == []

    created = client.post("/api/v1/tags/", {"name": "mine"}, content_type="application/json")
    assert created.status_code == 201
    assert created.json()["color"].startswith("#")
    assert Tag.objects.filter(owner=user, name="mine").exists()
