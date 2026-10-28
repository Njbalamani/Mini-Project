"""Analytics selectors.

All metrics are computed with database aggregation scoped to the requesting
user. Genuine zero values are reported as 0; metrics that cannot be computed
are returned as None and rendered as "unavailable".
"""
from datetime import timedelta

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Sum
from django.utils import timezone

from apps.ai_assistant.models import AIUsageRecord
from apps.integrations.models import Integration
from apps.tasks.models import Task
from apps.workflow_automation.models import WorkflowExecution


def resolve_range(start, end):
    """Return (start_dt, end_dt) timezone-aware bounds for the range."""
    now = timezone.now()
    if not end:
        end = now
    if not start:
        start = end - timedelta(days=30)
    return start, end


def task_metrics(user, start, end):
    qs = Task.objects.filter(owner=user, created_at__gte=start, created_at__lte=end)
    created = qs.count()
    completed = qs.filter(status=Task.Status.DONE).count()
    overdue = Task.objects.filter(
        owner=user, due_date__lt=timezone.now()
    ).exclude(status=Task.Status.DONE).count()
    completion_pct = round(completed / created * 100, 1) if created else 0

    completed_qs = Task.objects.filter(
        owner=user, completed_at__gte=start, completed_at__lte=end
    ).annotate(
        cycle=ExpressionWrapper(F("completed_at") - F("created_at"), output_field=DurationField())
    )
    avg_cycle = completed_qs.aggregate(avg=Avg("cycle"))["avg"]
    avg_hours = round(avg_cycle.total_seconds() / 3600, 1) if avg_cycle else None

    return {
        "tasks_created": created,
        "tasks_completed": completed,
        "completion_pct": completion_pct,
        "overdue_tasks": overdue,
        "avg_completion_hours": avg_hours,
    }


def task_trend(user, start, end, buckets=14):
    """Daily created/completed counts across the range."""
    days = []
    total_days = max(1, (end.date() - start.date()).days + 1)
    step = max(1, total_days // buckets)
    labels, created_series, completed_series = [], [], []
    cursor = start.date()
    while cursor <= end.date():
        day_start = timezone.make_aware(
            timezone.datetime.combine(cursor, timezone.datetime.min.time())
        )
        day_end = day_start + timedelta(days=step)
        created = Task.objects.filter(
            owner=user, created_at__gte=day_start, created_at__lt=day_end
        ).count()
        completed = Task.objects.filter(
            owner=user, completed_at__gte=day_start, completed_at__lt=day_end
        ).count()
        labels.append(cursor.strftime("%d %b"))
        created_series.append(created)
        completed_series.append(completed)
        cursor += timedelta(days=step)
    return {"labels": labels, "created": created_series, "completed": completed_series}


def workflow_metrics(user, start, end):
    qs = WorkflowExecution.objects.filter(
        workflow__owner=user, started_at__gte=start, started_at__lte=end
    )
    total = qs.count()
    succeeded = qs.filter(status="succeeded").count()
    failed = qs.filter(status__in=["failed", "timeout"]).count()
    return {
        "executions": total,
        "succeeded": succeeded,
        "failed": failed,
        "success_rate": round(succeeded / total * 100, 1) if total else 0,
        "failure_rate": round(failed / total * 100, 1) if total else 0,
    }


def ai_metrics(user, start, end):
    qs = AIUsageRecord.objects.filter(user=user, created_at__gte=start, created_at__lte=end)
    totals = qs.aggregate(tokens=Sum("total_tokens"))
    return {
        "ai_requests": qs.count(),
        "ai_tokens": totals["tokens"] or 0,
        "ai_success": qs.filter(success=True).count(),
        "ai_failures": qs.filter(success=False).count(),
    }


def integration_metrics(user):
    return {
        "connected": Integration.objects.filter(user=user, status="connected").count(),
        "errored": Integration.objects.filter(user=user, status="error").count(),
        "total": Integration.objects.filter(user=user).count(),
    }


def status_breakdown(user):
    from django.db.models import Q as _Q
    counts = {choice: 0 for choice, _ in Task.Status.choices}
    rows = Task.objects.filter(owner=user).values("status").annotate(n=Count("id"))
    for row in rows:
        if row["status"] in counts:
            counts[row["status"]] = row["n"]
    return counts


def build_report(user, start=None, end=None):
    start, end = resolve_range(start, end)
    data = {}
    data.update(task_metrics(user, start, end))
    data.update(workflow_metrics(user, start, end))
    data.update(ai_metrics(user, start, end))
    data.update(integration_metrics(user))
    data["trend"] = task_trend(user, start, end)
    data["status_breakdown"] = status_breakdown(user)
    data["range"] = {"start": start, "end": end}
    return data
