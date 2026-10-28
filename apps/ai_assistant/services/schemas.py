"""Validation of AI-proposed structured actions.

A model returning valid JSON does not make the action safe or correct. Every
proposed action is validated against an explicit schema, value ranges and
application rules before it is ever surfaced to the user for confirmation.
"""
from __future__ import annotations

from datetime import datetime

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from apps.tasks.models import Task

TASK_PRIORITIES = {choice for choice, _ in Task.Priority.choices}
WORKFLOW_TRIGGERS = {"manual", "scheduled", "task_overdue", "event_upcoming"}
WORKFLOW_ACTIONS = {"create_notification", "summarize_tasks", "suggest_deadline"}

ALLOWED_ACTIONS = {"create_task", "create_event", "create_workflow", "none"}


class ActionValidationError(Exception):
    def __init__(self, errors):
        self.errors = errors if isinstance(errors, list) else [errors]
        super().__init__("; ".join(self.errors))


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    parsed = parse_datetime(str(value))
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _clip(value, length):
    return (value or "")[:length]


def validate_action(action: dict) -> dict:
    """Validate a single proposed action and return a normalised dict.

    Raises ActionValidationError with a list of human-readable problems.
    """
    if not isinstance(action, dict):
        raise ActionValidationError("Action must be an object.")
    action_type = action.get("type")
    if action_type not in ALLOWED_ACTIONS:
        raise ActionValidationError(f"Unsupported action type: {action_type!r}")
    if action_type == "none":
        return {"type": "none"}

    errors = []
    payload = action.get("payload") or {}
    if not isinstance(payload, dict):
        raise ActionValidationError("Action payload must be an object.")

    if action_type == "create_task":
        title = _clip(payload.get("title", "").strip(), 200)
        if len(title) < 2:
            errors.append("Task title must be at least 2 characters.")
        priority = payload.get("priority", "medium")
        if priority not in TASK_PRIORITIES:
            priority = "medium"
        due = _parse_dt(payload.get("due_date"))
        if due and due < timezone.now() - timezone.timedelta(days=1):
            errors.append("Due date cannot be in the past.")
        if errors:
            raise ActionValidationError(errors)
        return {
            "type": "create_task",
            "payload": {
                "title": title,
                "description": _clip(payload.get("description", ""), 2000),
                "priority": priority,
                "category": _clip(payload.get("category", ""), 80),
                "due_date": due.isoformat() if due else None,
            },
        }

    if action_type == "create_event":
        title = _clip(payload.get("title", "").strip(), 200)
        if len(title) < 2:
            errors.append("Event title must be at least 2 characters.")
        start = _parse_dt(payload.get("start"))
        end = _parse_dt(payload.get("end"))
        if start is None:
            errors.append("Event requires a valid start time.")
        if end is None and start is not None:
            end = start + timezone.timedelta(hours=1)
        if start and end and end <= start:
            errors.append("Event end must be after its start.")
        if errors:
            raise ActionValidationError(errors)
        return {
            "type": "create_event",
            "payload": {
                "title": title,
                "description": _clip(payload.get("description", ""), 2000),
                "location": _clip(payload.get("location", ""), 200),
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        }

    if action_type == "create_workflow":
        name = _clip(payload.get("name", "").strip(), 200)
        if len(name) < 2:
            errors.append("Workflow name must be at least 2 characters.")
        trigger = payload.get("trigger", "manual")
        if trigger not in WORKFLOW_TRIGGERS:
            errors.append(f"Unsupported trigger: {trigger!r}")
        action = payload.get("action", "create_notification")
        if action not in WORKFLOW_ACTIONS:
            errors.append(f"Unsupported workflow action: {action!r}")
        if errors:
            raise ActionValidationError(errors)
        return {
            "type": "create_workflow",
            "payload": {"name": name, "trigger": trigger, "action": action,
                        "description": _clip(payload.get("description", ""), 500)},
        }

    raise ActionValidationError(f"Unhandled action type: {action_type!r}")


def validate_proposed_actions(raw_actions) -> tuple[list, list]:
    """Validate a list of actions. Returns (valid_actions, error_messages)."""
    valid, errors = [], []
    if raw_actions is None:
        return valid, errors
    if not isinstance(raw_actions, list):
        return valid, ["Proposed actions must be a list."]
    for index, action in enumerate(raw_actions[:5]):
        try:
            normalized = validate_action(action)
            if normalized.get("type") != "none":
                valid.append(normalized)
        except ActionValidationError as exc:
            errors.append(f"Action {index + 1}: {'; '.join(exc.errors)}")
    return valid, errors
