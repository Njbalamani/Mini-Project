"""Constrained workflow execution engine.

Safety properties:
* Only the actions registered in ACTION_HANDLERS can run; there is no dynamic
  code execution path.
* Every execution carries an idempotency key so retried triggers do not create
  duplicate side effects.
* Execution is wrapped with an explicit timeout budget.
* Conditions are evaluated against the workflow owner's own data only.
"""
from __future__ import annotations

import logging
import time

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit_logs.services import log_event
from apps.notifications.services import notify
from apps.tasks.models import Task

from .models import (
    ActionType,
    ConditionType,
    Workflow,
    WorkflowExecution,
    WorkflowExecutionStep,
)

logger = logging.getLogger("nexamind.workflows")

EXECUTION_TIMEOUT_SECONDS = 30
MAX_RETRIES = 2


class WorkflowError(Exception):
    pass


class ExecutionTimeout(WorkflowError):
    pass


def _evaluate_conditions(workflow, context):
    for condition in workflow.conditions.all():
        if condition.condition_type == ConditionType.ALWAYS:
            continue
        if condition.condition_type == ConditionType.TASK_INCOMPLETE:
            task = context.get("task")
            if task is not None and getattr(task, "status", None) == Task.Status.DONE:
                return False
    return True


def _action_create_notification(workflow, context, action=None):
    title = context.get("notification_title") or f"Workflow: {workflow.name}"
    message = context.get("notification_message") or "Your workflow ran successfully."
    notify(
        workflow.owner, type="workflow_completed", level="info", title=title,
        message=message, url=context.get("url", ""), dedupe_key=context.get("dedupe_key", ""),
    )
    return f"Notification sent: {title}"


def _action_summarize_tasks(workflow, context, action=None):
    tasks = Task.objects.filter(owner=workflow.owner).open_tasks()
    overdue = tasks.filter(due_date__lt=timezone.now()).count()
    summary = f"{tasks.count()} open tasks, {overdue} overdue."
    notify(
        workflow.owner, type="workflow_completed", title=f"Task summary: {workflow.name}",
        message=summary, url="/tasks/",
    )
    return summary


def _action_suggest_deadline(workflow, context, action=None):
    task = context.get("task")
    if task is None:
        raise WorkflowError("suggest_deadline requires a task context.")
    suggested = timezone.now() + timezone.timedelta(days=2)
    notify(
        workflow.owner, type="task_overdue", level="warning",
        title=f"Suggested new deadline for \u201c{task.title}\u201d",
        message=f"Consider moving this to {suggested:%A %d %b %H:%M}.",
        url=f"/tasks/{task.pk}/",
    )
    return f"Suggested deadline {suggested.isoformat()}"


def _action_create_task(workflow, context, action=None):
    """Create a follow-up task for the workflow owner (config: title, priority)."""
    from apps.tasks.services import create_task

    config = (action.config if action is not None else {}) or {}
    title = (config.get("title") or context.get("task_title")
             or f"Follow-up: {workflow.name}").strip()
    priority = config.get("priority") or Task.Priority.MEDIUM
    if priority not in dict(Task.Priority.choices):
        priority = Task.Priority.MEDIUM
    task = create_task(
        owner=workflow.owner, title=title[:200], priority=priority, actor=workflow.owner,
    )
    return f"Created task \u201c{task.title}\u201d (#{task.pk})"


ACTION_HANDLERS = {
    ActionType.CREATE_NOTIFICATION: _action_create_notification,
    ActionType.SUMMARIZE_TASKS: _action_summarize_tasks,
    ActionType.SUGGEST_DEADLINE: _action_suggest_deadline,
    ActionType.CREATE_TASK: _action_create_task,
}


def _run_action_with_retry(action, workflow, context):
    handler = ACTION_HANDLERS.get(action.action_type)
    if handler is None:
        raise WorkflowError(f"No handler registered for action {action.action_type!r}.")
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return handler(workflow, context, action)
        except Exception as exc:  # noqa: BLE001 - retried, then surfaced
            last_error = exc
            logger.warning(
                "Workflow action %s failed (attempt %s): %s",
                action.action_type, attempt + 1, exc,
            )
    raise WorkflowError(f"Action {action.action_type} failed: {last_error}")


def run_workflow(workflow, trigger_reason="manual", context=None, idempotency_key=""):
    """Execute a workflow synchronously and return its WorkflowExecution."""
    context = context or {}
    errors = workflow.validate_configuration()
    if errors:
        raise WorkflowError("Invalid workflow: " + "; ".join(errors))

    if idempotency_key:
        existing = WorkflowExecution.objects.filter(
            workflow=workflow, idempotency_key=idempotency_key
        ).first()
        if existing:
            logger.info("Skipping duplicate execution for key %s", idempotency_key)
            return existing

    try:
        execution = WorkflowExecution.objects.create(
            workflow=workflow, trigger_reason=trigger_reason, status="running",
            idempotency_key=idempotency_key,
        )
    except IntegrityError:
        return WorkflowExecution.objects.get(
            workflow=workflow, idempotency_key=idempotency_key
        )

    started = time.monotonic()
    failure = ""
    try:
        if not _evaluate_conditions(workflow, context):
            execution.status = "succeeded"
            execution.finished_at = timezone.now()
            execution.error = "Conditions not met; nothing to do."
            execution.save(update_fields=["status", "finished_at", "error"])
            WorkflowExecutionStep.objects.create(
                execution=execution, step_name="conditions", order=0, status="skipped",
                detail="Conditions not satisfied.",
            )
            return execution

        for action in workflow.actions.all():
            if time.monotonic() - started > EXECUTION_TIMEOUT_SECONDS:
                raise ExecutionTimeout("Workflow exceeded its time budget.")
            step = WorkflowExecutionStep.objects.create(
                execution=execution, step_name=action.get_action_type_display(),
                order=action.order, status="running",
            )
            try:
                detail = _run_action_with_retry(action, workflow, context)
                step.status = "succeeded"
                step.detail = str(detail)[:400]
            except WorkflowError as exc:
                step.status = "failed"
                step.detail = str(exc)[:400]
                raise
            finally:
                step.save(update_fields=["status", "detail"])

        execution.status = "succeeded"
    except ExecutionTimeout as exc:
        execution.status = "timeout"
        failure = str(exc)
    except Exception as exc:  # noqa: BLE001
        execution.status = "failed"
        failure = str(exc)
        logger.exception("Workflow %s execution failed", workflow.pk)

    execution.finished_at = timezone.now()
    execution.error = failure[:400]
    execution.save(update_fields=["status", "finished_at", "error"])

    workflow.last_run_at = timezone.now()
    workflow.run_count = (workflow.run_count or 0) + 1
    workflow.save(update_fields=["last_run_at", "run_count"])

    if execution.status in {"failed", "timeout"}:
        notify(
            workflow.owner, type="workflow_failed", level="danger",
            title=f"Workflow failed: {workflow.name}", message=failure[:200],
            url=f"/workflows/{workflow.pk}/",
            dedupe_key=f"wf-fail-{execution.pk}",
        )
    log_event(
        actor=workflow.owner, action="workflow.executed", resource_type="workflow",
        resource_id=workflow.pk, outcome="success" if execution.status == "succeeded" else "failure",
        metadata={"execution": execution.pk, "status": execution.status,
                  "reason": trigger_reason},
    )
    return execution


def preview_workflow(workflow, context=None):
    """Dry-run description of what a workflow would do (no side effects)."""
    context = context or {}
    steps = []
    errors = workflow.validate_configuration()
    if errors:
        return {"valid": False, "errors": errors, "steps": []}
    conditions_met = _evaluate_conditions(workflow, context)
    step_no = 1
    for condition in workflow.conditions.all():
        steps.append({"order": step_no, "kind": "condition",
                      "label": condition.get_condition_type_display()})
        step_no += 1
    for action in workflow.actions.all():
        steps.append({"order": step_no, "kind": "action",
                      "label": action.get_action_type_display()})
        step_no += 1
    return {"valid": True, "errors": [], "steps": steps, "conditions_met": conditions_met}
