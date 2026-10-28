"""Celery tasks for workflow automation and reminders."""
import logging

from celery import shared_task
from django.utils import timezone

from apps.notifications.services import notify

from .engine import run_workflow
from .models import TriggerType, Workflow

logger = logging.getLogger("nexamind.workflows")


@shared_task(bind=True, max_retries=2, ignore_result=True)
def execute_workflow_task(self, workflow_id, trigger_reason="manual", context=None,
                          idempotency_key=""):
    workflow = Workflow.objects.filter(pk=workflow_id, is_enabled=True).first()
    if workflow is None:
        return None
    try:
        execution = run_workflow(workflow, trigger_reason=trigger_reason,
                                 context=context or {}, idempotency_key=idempotency_key)
        return execution.pk
    except Exception as exc:  # pragma: no cover - retried by celery
        logger.exception("Background workflow execution failed")
        raise self.retry(exc=exc, countdown=30)


@shared_task(ignore_result=True)
def scan_overdue_tasks():
    """Trigger overdue-task workflows and send reminders (idempotent per task/day)."""
    now = timezone.now()
    from apps.accounts.models import UserPreference
    from apps.tasks.models import Task

    overdue = list(Task.objects.open_tasks().filter(due_date__lt=now).select_related("owner")[:500])
    owner_ids = {t.owner_id for t in overdue}
    prefs = {p.user_id: p for p in UserPreference.objects.filter(user_id__in=owner_ids)}
    today = now.strftime("%Y%m%d")
    for task in overdue:
        pref = prefs.get(task.owner_id)
        if pref is None or pref.task_reminders:
            notify(
                task.owner, type="task_overdue", level="warning",
                title=f"Task overdue: {task.title}",
                message=f"This task was due {task.due_date:%d %b %H:%M}.",
                url=f"/tasks/{task.pk}/",
                dedupe_key=f"overdue-{task.pk}-{today}",
            )
        workflows = Workflow.objects.filter(
            owner=task.owner, is_enabled=True, triggers__trigger_type=TriggerType.TASK_OVERDUE
        ).distinct()
        for workflow in workflows:
            execute_workflow_task.delay(
                workflow.pk, trigger_reason="task_overdue",
                context={"task_id": task.pk},
                idempotency_key=f"overdue-{workflow.pk}-{task.pk}-{today}",
            )


@shared_task(ignore_result=True)
def scan_scheduled_workflows():
    """Run workflows whose scheduled time matches the current minute."""
    current = timezone.localtime().strftime("%H:%M")
    today = timezone.localdate().isoformat()
    workflows = Workflow.objects.filter(
        is_enabled=True, triggers__trigger_type=TriggerType.SCHEDULED,
        triggers__schedule_time=current,
    ).distinct()
    for workflow in workflows:
        execute_workflow_task.delay(
            workflow.pk, trigger_reason="scheduled",
            idempotency_key=f"scheduled-{workflow.pk}-{today}-{current}",
        )
