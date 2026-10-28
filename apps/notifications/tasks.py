"""Celery tasks for the notifications app."""
import logging

from celery import shared_task
from django.utils import timezone

from .services import notify

logger = logging.getLogger("nexamind.notifications")


@shared_task(ignore_result=True)
def send_weekly_digest():
    """Send an in-app weekly workspace digest to users who opted in.

    Respects ``UserPreference.weekly_digest`` and ``in_app_notifications``.
    Idempotent per user/week.
    """
    from apps.accounts.models import UserPreference

    from .services import build_digest

    week = timezone.localdate().strftime("%G-W%V")
    prefs = (
        UserPreference.objects.filter(
            weekly_digest=True, in_app_notifications=True
        ).select_related("user")[:2000]
    )

    sent = 0
    for pref in prefs:
        digest = build_digest(pref.user, days=7)
        result = notify(
            pref.user,
            type="system",
            level="info",
            title="Your weekly NexaMind digest",
            message=digest["message"],
            url="/app/",
            dedupe_key=f"weekly-digest-{week}",
        )
        if result is not None:
            sent += 1
    return sent
