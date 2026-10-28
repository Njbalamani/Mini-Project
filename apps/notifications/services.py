"""Notification creation service with preference checks and deduplication."""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import UserPreference

from .models import Notification

logger = logging.getLogger("nexamind.notifications")

GROUP_PREFIX = "user_notifications"


def broadcast_notification(notification):
    """Push a notification to the user's live (WebSocket) channel, if available."""
    if not hasattr(settings, "CHANNEL_LAYERS"):
        return
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return
    try:
        async_to_sync(channel_layer.group_send)(
            f"{GROUP_PREFIX}_{notification.user_id}",
            {
                "type": "notify",
                "id": notification.pk,
                "notif_type": notification.type,
                "level": notification.level,
                "title": notification.title,
                "message": notification.message,
                "url": notification.url,
                "created_at": timezone.localtime(notification.created_at).strftime("%H:%M"),
                "key": "nm-notif",
            },
        )
    except Exception:  # pragma: no cover - never break message flow on push failure
        logger.warning("Could not broadcast notification %s", notification.pk)


def notify(user, type, title, message="", level="info", url="", dedupe_key=""):
    """Create a notification respecting the user's in-app preference.

    Returns the Notification instance or None if suppressed/duplicate.
    """
    pref = UserPreference.objects.filter(user=user).first()
    if pref and not pref.in_app_notifications:
        return None

    try:
        with transaction.atomic():
            notification = Notification.objects.create(
                user=user, type=type, level=level, title=title,
                message=message, url=url, dedupe_key=dedupe_key,
            )
    except IntegrityError:
        return None

    if settings.NEXAMIND.get("NOTIFICATIONS_WS_ENABLED", True):
        broadcast_notification(notification)
    return notification


def notify_many(users, **kwargs):
    return [notify(user, **kwargs) for user in users]


def mark_all_read(user):
    return Notification.objects.filter(user=user, is_read=False).update(
        is_read=True, read_at=timezone.now()
    )


def build_digest(user, days=7):
    """Assemble a factual workspace digest for a user.

    Pure read-only aggregation (tasks + upcoming events) used both by the
    weekly Celery job and the on-demand preview/send views. No fabrication.
    """
    from apps.calendar_manager.models import CalendarEvent
    from apps.tasks.models import Task

    now = timezone.now()
    window_end = now + timezone.timedelta(days=days)
    tasks = Task.objects.filter(owner=user)

    open_tasks = tasks.exclude(status=Task.Status.DONE)
    overdue_qs = open_tasks.filter(due_date__lt=now).order_by("due_date")
    overdue_count = overdue_qs.count()
    overdue = list(overdue_qs.values_list("title", flat=True)[:5])
    due_soon = list(
        open_tasks.filter(due_date__gte=now, due_date__lte=window_end)
        .order_by("due_date").values_list("title", flat=True)[:5]
    )
    completed = tasks.filter(
        status=Task.Status.DONE, completed_at__gte=now - timezone.timedelta(days=days)
    ).count()
    events = list(
        CalendarEvent.objects.filter(owner=user, end__gte=now, start__lte=window_end)
        .order_by("start")
        .values_list("title", "start")[:5]
    )

    open_count = open_tasks.count()
    message = (
        f"{open_count} open tasks ({overdue_count} overdue), "
        f"{completed} completed in the last {days} days."
    )
    return {
        "generated_at": now,
        "days": days,
        "open_count": open_count,
        "overdue_count": overdue_count,
        "overdue_titles": overdue,
        "due_soon_titles": due_soon,
        "completed_count": completed,
        "events": [
            {"title": title, "start": start} for title, start in events
        ],
        "message": message,
    }
