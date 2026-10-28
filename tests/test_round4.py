"""Tests for saved task views, session management and the create-task workflow action."""
import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.test import Client
from django.utils import timezone

from apps.tasks.models import SavedTaskFilter, Task
from apps.workflow_automation.engine import run_workflow
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


def _client(user):
    client = Client()
    client.force_login(user)
    return client


# --- Saved task filters ------------------------------------------------------
def test_save_and_apply_filter(user):
    client = _client(user)
    response = client.post("/tasks/saved-filters/save/", {
        "name": "High work", "status": "todo", "priority": "high", "q": "report",
        "next": "/tasks/",
    })
    assert response.status_code == 302
    saved = SavedTaskFilter.objects.get(owner=user, name="High work")
    assert saved.query == {"q": "report", "status": "todo", "priority": "high"}
    assert "priority=high" in saved.query_string

    listing = client.get("/tasks/")
    assert b"High work" in listing.content


def test_save_filter_upserts_by_name(user):
    client = _client(user)
    client.post("/tasks/saved-filters/save/", {"name": "Mine", "status": "todo"})
    client.post("/tasks/saved-filters/save/", {"name": "Mine", "status": "done"})
    assert SavedTaskFilter.objects.filter(owner=user, name="Mine").count() == 1
    assert SavedTaskFilter.objects.get(owner=user, name="Mine").query == {"status": "done"}


def test_delete_filter(user):
    saved = SavedTaskFilter.objects.create(owner=user, name="Temp", query={"q": "x"})
    _client(user).post(f"/tasks/saved-filters/{saved.pk}/delete/")
    assert not SavedTaskFilter.objects.filter(pk=saved.pk).exists()


def test_saved_filters_are_private(user, other_user):
    saved = SavedTaskFilter.objects.create(owner=other_user, name="Theirs")
    response = _client(user).post(f"/tasks/saved-filters/{saved.pk}/delete/")
    assert response.status_code == 404


# --- Active sessions ---------------------------------------------------------
def _extra_session(user):
    store = SessionStore()
    store["_auth_user_id"] = str(user.pk)
    store["_auth_user_backend"] = "django.contrib.auth.backends.ModelBackend"
    store.create()
    return store.session_key


def test_sessions_page_lists_current(user):
    client = _client(user)
    response = client.get("/accounts/sessions/")
    assert response.status_code == 200
    assert b"This device" in response.content
    assert client.session.session_key[:8].encode() in response.content


def test_revoke_other_sessions(user):
    client = _client(user)
    current = client.session.session_key
    other = _extra_session(user)

    response = client.post("/accounts/sessions/revoke-others/")
    assert response.status_code == 302
    from django.contrib.sessions.models import Session

    assert not Session.objects.filter(session_key=other).exists()
    assert Session.objects.filter(session_key=current).exists()


def test_revoke_single_session(user):
    client = _client(user)
    other = _extra_session(user)
    _client(user).post(f"/accounts/sessions/{other}/revoke/")
    assert not SessionStore(session_key=other).load()


def test_cannot_revoke_current_session(user):
    client = _client(user)
    key = client.session.session_key
    client.post(f"/accounts/sessions/{key}/revoke/")
    assert _client(user).get("/accounts/sessions/").status_code == 200
    from django.contrib.sessions.models import Session
    assert Session.objects.filter(session_key=key).exists()


# --- Workflow create-task action --------------------------------------------
def _workflow(user, **action_config):
    wf = Workflow.objects.create(owner=user, name="Follow-up bot")
    WorkflowTrigger.objects.create(workflow=wf, trigger_type=TriggerType.MANUAL)
    WorkflowCondition.objects.create(workflow=wf, condition_type=ConditionType.ALWAYS)
    WorkflowAction.objects.create(
        workflow=wf, action_type=ActionType.CREATE_TASK, config=action_config
    )
    return wf


def test_create_task_action_runs(user):
    wf = _workflow(user, title="Call the client", priority="high")
    execution = run_workflow(wf, trigger_reason="test")
    assert execution.status == "succeeded"
    task = Task.objects.get(owner=user)
    assert task.title == "Call the client"
    assert task.priority == Task.Priority.HIGH


def test_create_task_action_defaults(user):
    wf = _workflow(user)
    run_workflow(wf, trigger_reason="test")
    task = Task.objects.get(owner=user)
    assert task.title == "Follow-up: Follow-up bot"
    assert task.priority == Task.Priority.MEDIUM


def test_workflow_form_persists_action_config(user):
    response = _client(user).post("/workflows/create/", {
        "name": "Auto task", "description": "",
        "trigger_type": TriggerType.MANUAL,
        "condition_type": ConditionType.ALWAYS,
        "action_type": ActionType.CREATE_TASK,
        "action_title": "Prepare report",
        "action_priority": "urgent",
        "is_enabled": "on",
    })
    assert response.status_code == 302
    action = WorkflowAction.objects.get(workflow__owner=user)
    assert action.config == {"title": "Prepare report", "priority": "urgent"}


def test_create_task_action_requires_title(user):
    response = _client(user).post("/workflows/create/", {
        "name": "Missing title",
        "trigger_type": "manual", "condition_type": "always",
        "action_type": "create_task", "is_enabled": "on",
    })
    assert response.status_code == 200
    assert b"Provide a title" in response.content
    assert not Workflow.objects.filter(owner=user, name="Missing title").exists()
