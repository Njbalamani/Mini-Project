"""Dashboard data selectors - every number comes from the database."""
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from apps.ai_assistant.models import Conversation
from apps.audit_logs.models import AuditLog
from apps.calendar_manager.models import CalendarEvent
from apps.integrations.models import Integration
from apps.notifications.models import Notification
from apps.tasks.models import Task
from apps.workflow_automation.models import Workflow, WorkflowExecution


def task_stats(user):
    qs = Task.objects.filter(owner=user)
    return {
        "total": qs.count(),
        "pending": qs.exclude(status=Task.Status.DONE).count(),
        "completed": qs.filter(status=Task.Status.DONE).count(),
        "overdue": qs.exclude(status=Task.Status.DONE).filter(due_date__lt=timezone.now()).count(),
    }


def upcoming_events(user, limit=5):
    return (
        CalendarEvent.objects.filter(owner=user, end__gte=timezone.now())
        .order_by("start")[:limit]
    )


def recent_activity(user, limit=8):
    return AuditLog.objects.filter(actor=user).order_by("-timestamp")[:limit]


def workflow_stats(user):
    executions = WorkflowExecution.objects.filter(workflow__owner=user)
    total = executions.count()
    succeeded = executions.filter(status="succeeded").count()
    return {
        "total_workflows": Workflow.objects.filter(owner=user).count(),
        "active_workflows": Workflow.objects.filter(owner=user, is_enabled=True).count(),
        "executions": total,
        "succeeded": succeeded,
        "failed": executions.filter(status__in=["failed", "timeout"]).count(),
        "success_rate": round(succeeded / total * 100) if total else 0,
    }


def integration_stats(user):
    return {
        "connected": Integration.objects.filter(user=user, status="connected").count(),
        "errored": Integration.objects.filter(user=user, status="error").count(),
    }


def recent_conversations(user, limit=4):
    return Conversation.objects.filter(owner=user)[:limit]


def unread_notifications(user):
    return Notification.objects.filter(user=user, is_read=False).count()


def productivity_trend(user, days=7):
    end = timezone.now()
    start = end - timedelta(days=days - 1)
    labels, created, completed = [], [], []
    for offset in range(days):
        day = (start + timedelta(days=offset)).date()
        day_start = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time()))
        day_end = day_start + timedelta(days=1)
        labels.append(day.strftime("%a"))
        created.append(
            Task.objects.filter(owner=user, created_at__gte=day_start, created_at__lt=day_end).count()
        )
        completed.append(
            Task.objects.filter(owner=user, completed_at__gte=day_start, completed_at__lt=day_end).count()
        )
    return {"labels": labels, "created": created, "completed": completed}


def status_breakdown(user):
    rows = (
        Task.objects.filter(owner=user).values("status").annotate(n=Count("id")).order_by()
    )
    return {row["status"]: row["n"] for row in rows}


def build_dashboard(user):
    return {
        "tasks": task_stats(user),
        "events": upcoming_events(user),
        "activity": recent_activity(user),
        "workflows": workflow_stats(user),
        "integrations": integration_stats(user),
        "conversations": recent_conversations(user),
        "unread": unread_notifications(user),
        "trend": productivity_trend(user),
        "status_breakdown": status_breakdown(user),
    }
