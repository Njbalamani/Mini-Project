"""Tests for the task service layer and status transitions."""
import pytest

from apps.tasks.models import Task, TaskActivity
from apps.tasks.services import create_task, set_status

pytestmark = pytest.mark.django_db


def test_create_task_trims_title_and_logs_activity(user):
    task = create_task(user, title="  Write the report  ")
    assert task.title == "Write the report"
    assert task.owner == user
    assert TaskActivity.objects.filter(task=task).count() == 1


def test_completing_a_task_sets_completed_at(user):
    task = create_task(user, title="A task")
    set_status(task, Task.Status.DONE, actor=user)
    task.refresh_from_db()
    assert task.status == Task.Status.DONE
    assert task.completed_at is not None


def test_tasks_are_scoped_to_their_owner(user, other_user):
    create_task(user, title="Mine")
    create_task(other_user, title="Theirs")
    assert Task.objects.filter(owner=user).count() == 1
