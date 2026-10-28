"""Calendar service layer: conflict detection and availability."""
import secrets
from datetime import timedelta

from django.utils import timezone

from apps.accounts.models import UserProfile

from .models import CalendarEvent


def get_calendar_feed_token(user):
    """Return the user's calendar feed token, creating one on first use."""
    profile, _ = UserProfile.objects.get_or_create(user=user)
    if not profile.calendar_feed_token:
        profile.calendar_feed_token = secrets.token_urlsafe(32)
        profile.save(update_fields=["calendar_feed_token", "updated_at"])
    return profile.calendar_feed_token


def reset_calendar_feed_token(user):
    """Invalidate the previous feed URL and issue a fresh token."""
    profile, _ = UserProfile.objects.get_or_create(user=user)
    profile.calendar_feed_token = secrets.token_urlsafe(32)
    profile.save(update_fields=["calendar_feed_token", "updated_at"])
    return profile.calendar_feed_token


def feed_events(user, *, days_back=1):
    """Events to include in an export/feed (recent past onward)."""
    cutoff = timezone.now() - timedelta(days=days_back)
    return CalendarEvent.objects.filter(owner=user, end__gte=cutoff).order_by("start")


def overlapping_events(user, start, end, exclude_pk=None):
    qs = CalendarEvent.objects.filter(
        owner=user, start__lt=end, end__gt=start,
    )
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return qs.order_by("start")


def detect_conflicts(user, start, end, exclude_pk=None):
    return list(overlapping_events(user, start, end, exclude_pk=exclude_pk))


def find_free_slots(user, day, *, work_start=9, work_end=18, slot_minutes=30):
    """Return candidate free slots within working hours for the given day."""
    tz = timezone.get_current_timezone()
    day_start = timezone.make_aware(
        timezone.datetime(day.year, day.month, day.day, work_start, 0), tz
    )
    day_end = timezone.make_aware(
        timezone.datetime(day.year, day.month, day.day, work_end, 0), tz
    )
    busy = list(
        CalendarEvent.objects.filter(owner=user, start__lt=day_end, end__gt=day_start)
        .order_by("start").values_list("start", "end")
    )
    slots = []
    cursor = day_start
    step = timedelta(minutes=slot_minutes)
    while cursor + step <= day_end:
        slot_end = cursor + step
        conflict = any(b_start < slot_end and b_end > cursor for b_start, b_end in busy)
        if not conflict:
            slots.append((cursor, slot_end))
        cursor = slot_end
    return slots
