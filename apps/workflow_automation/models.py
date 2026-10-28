"""Workflow automation models.

The engine is deliberately constrained: triggers, conditions and actions are
chosen from a small, well-defined catalogue. No arbitrary Python or shell
execution is possible through a workflow definition.
"""
import secrets
import uuid

from django.conf import settings
from django.db import models


class TriggerType(models.TextChoices):
    MANUAL = "manual", "Manual"
    SCHEDULED = "scheduled", "At a scheduled time"
    TASK_OVERDUE = "task_overdue", "A task becomes overdue"
    EVENT_UPCOMING = "event_upcoming", "An event is upcoming"
    WEBHOOK = "webhook", "Inbound webhook"


class ConditionType(models.TextChoices):
    TASK_INCOMPLETE = "task_incomplete", "Task is still incomplete"
    ALWAYS = "always", "Always"


class ActionType(models.TextChoices):
    CREATE_NOTIFICATION = "create_notification", "Create an in-app notification"
    SUMMARIZE_TASKS = "summarize_tasks", "Summarize open tasks"
    SUGGEST_DEADLINE = "suggest_deadline", "Suggest a revised deadline"
    CREATE_TASK = "create_task", "Create a follow-up task"


class Workflow(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workflows"
    )
    name = models.CharField(max_length=200)
    description = models.CharField(max_length=400, blank=True)
    is_enabled = models.BooleanField(default=True, db_index=True)
    last_run_at = models.DateTimeField(null=True, blank=True)
    run_count = models.PositiveIntegerField(default=0)
    # Secret, unguessable address for inbound webhook triggers.
    webhook_token = models.CharField(
        max_length=64, unique=True, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner", "is_enabled"])]

    def __str__(self):
        return self.name

    def ensure_webhook_token(self):
        """Return the workflow's webhook token, creating one on first use."""
        if not self.webhook_token:
            self.webhook_token = secrets.token_urlsafe(32)
            self.save(update_fields=["webhook_token", "updated_at"])
        return self.webhook_token

    def reset_webhook_token(self):
        """Invalidate the previous webhook URL and issue a fresh token."""
        self.webhook_token = secrets.token_urlsafe(32)
        self.save(update_fields=["webhook_token", "updated_at"])
        return self.webhook_token

    def validate_configuration(self):
        """Return a list of configuration problems (empty when valid)."""
        errors = []
        triggers = list(self.triggers.all())
        actions = list(self.actions.all())
        if not triggers:
            errors.append("A workflow needs exactly one trigger.")
        if len(triggers) > 1:
            errors.append("A workflow may only have one trigger.")
        if not actions:
            errors.append("A workflow needs at least one action.")
        if len(actions) > 5:
            errors.append("A workflow may have at most 5 actions.")
        return errors


class WorkflowTrigger(models.Model):
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="triggers")
    trigger_type = models.CharField(max_length=24, choices=TriggerType.choices)
    # For scheduled triggers: ISO time-of-day (HH:MM) evaluated by a periodic job.
    schedule_time = models.CharField(max_length=5, blank=True)
    config = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.workflow_id}:trigger={self.trigger_type}"


class WorkflowCondition(models.Model):
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="conditions")
    condition_type = models.CharField(max_length=24, choices=ConditionType.choices)
    config = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.workflow_id}:condition={self.condition_type}"


class WorkflowAction(models.Model):
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="actions")
    action_type = models.CharField(max_length=32, choices=ActionType.choices)
    order = models.PositiveIntegerField(default=1)
    config = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.workflow_id}:action={self.action_type}"


class WorkflowExecution(models.Model):
    STATUS = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("timeout", "Timed out"),
    ]
    workflow = models.ForeignKey(Workflow, on_delete=models.CASCADE, related_name="executions")
    trigger_reason = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default="pending", db_index=True)
    # Idempotency key prevents duplicate executions for the same event.
    idempotency_key = models.CharField(max_length=120, blank=True, db_index=True)
    error = models.CharField(max_length=400, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["workflow", "-started_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["workflow", "idempotency_key"],
                condition=models.Q(idempotency_key__gt=""),
                name="unique_workflow_execution_idempotency",
            )
        ]

    @property
    def duration_seconds(self):
        if self.finished_at:
            return round((self.finished_at - self.started_at).total_seconds(), 2)
        return None

    def __str__(self):
        return f"Execution<{self.workflow_id}:{self.status}>"


class WorkflowExecutionStep(models.Model):
    execution = models.ForeignKey(
        WorkflowExecution, on_delete=models.CASCADE, related_name="steps"
    )
    step_name = models.CharField(max_length=120)
    order = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=12, default="pending")
    detail = models.CharField(max_length=400, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{self.execution_id}:{self.step_name}({self.status})"
