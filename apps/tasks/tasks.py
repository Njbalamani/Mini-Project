"""Celery tasks for the tasks app."""
import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.notifications.services import notify

logger = logging.getLogger("nexamind.tasks")


@shared_task(ignore_result=True)
def send_due_task_reminders():
    """Notify users about open tasks due within the next 24 hours.

    Idempotent per task/day so retries and overlapping schedules are safe.
    Respects each user's ``task_reminders`` preference.
    """
    from apps.accounts.models import UserPreference

    from .models import Task

    now = timezone.now()
    soon = now + timedelta(hours=24)
    tasks = list(
        Task.objects.open_tasks()
        .filter(due_date__gte=now, due_date__lte=soon)
        .select_related("owner")[:500]
    )
    if not tasks:
        return 0

    owner_ids = {t.owner_id for t in tasks}
    prefs = {
        p.user_id: p
        for p in UserPreference.objects.filter(user_id__in=owner_ids)
    }
    day = now.strftime("%Y%m%d")
    sent = 0
    for task in tasks:
        pref = prefs.get(task.owner_id)
        if pref is not None and not pref.task_reminders:
            continue
        result = notify(
            task.owner,
            type="task_reminder",
            level="info",
            title=f"Task due soon: {task.title}",
            message=f"Due {task.due_date:%d %b %H:%M}. Priority: {task.get_priority_display()}.",
            url=f"/tasks/{task.pk}/",
            dedupe_key=f"due-soon-{task.pk}-{day}",
        )
        if result is not None:
            sent += 1
    return sent
