"""Calendar views: month grid, day view, create/edit/delete, conflict checking."""
import calendar as pycalendar
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import UserProfile
from apps.audit_logs.services import log_event

from .forms import CalendarEventForm
from .ics import build_calendar
from .models import CalendarEvent, EventReminder
from .services import (
    detect_conflicts,
    feed_events,
    find_free_slots,
    get_calendar_feed_token,
    reset_calendar_feed_token,
)


def _month_bounds(year, month):
    first = date(year, month, 1)
    last_day = pycalendar.monthrange(year, month)[1]
    last = date(year, month, last_day)
    return first, last


@login_required
def calendar_view(request):
    today = timezone.localdate()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
    except (TypeError, ValueError):
        year, month = today.year, today.month
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        year, month = today.year, today.month

    first, last = _month_bounds(year, month)
    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(timezone.datetime.combine(first, timezone.datetime.min.time()), tz)
    end_dt = timezone.make_aware(timezone.datetime.combine(last, timezone.datetime.max.time()), tz)

    events = list(
        CalendarEvent.objects.filter(owner=request.user, start__lte=end_dt, end__gte=start_dt)
        .order_by("start")
    )

    # Build a month matrix with events assigned to the day they start (expanded for recurrences).
    weeks = pycalendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    events_by_day = {}
    for week in weeks:
        for day in week:
            if day.month != month:
                continue
            day_start = timezone.make_aware(timezone.datetime.combine(day, timezone.datetime.min.time()), tz)
            day_end = day_start + timedelta(days=1)
            items = []
            for ev in events:
                for occ_start, occ_end in ev.occurrences_between(day_start, day_end):
                    if occ_start < day_end and occ_end > day_start:
                        items.append(ev)
                        break
            events_by_day[day] = items

    upcoming = (
        CalendarEvent.objects.filter(owner=request.user, end__gte=timezone.now())
        .order_by("start")[:6]
    )

    weekday_headers = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    month_matrix = []
    for week in weeks:
        row = []
        for day in week:
            row.append({
                "date": day,
                "in_month": day.month == month,
                "is_today": day == today,
                "events": events_by_day.get(day, []),
            })
        month_matrix.append(row)

    feed_token = get_calendar_feed_token(request.user)
    feed_url = request.build_absolute_uri(
        reverse("calendar_manager:feed", args=[feed_token])
    )

    return render(request, "calendar/calendar.html", {
        "year": year, "month": month,
        "month_name": pycalendar.month_name[month],
        "month_matrix": month_matrix, "weekday_headers": weekday_headers,
        "today": today, "upcoming": upcoming,
        "feed_url": feed_url,
        "prev_year": year - 1 if month == 1 else year,
        "prev_month": 12 if month == 1 else month - 1,
        "next_year": year + 1 if month == 12 else year,
        "next_month": 1 if month == 12 else month + 1,
    })


@login_required
def event_detail(request, pk):
    event = get_object_or_404(CalendarEvent, pk=pk, owner=request.user)
    return render(request, "calendar/detail.html", {"event": event})


@login_required
def event_create(request):
    form = CalendarEventForm(request.POST or None)
    conflicts = []
    if request.method == "POST" and form.is_valid():
        event = form.save(commit=False)
        event.owner = request.user
        event.timezone = str(timezone.get_current_timezone())
        conflicts = detect_conflicts(request.user, event.start, event.end)
        if conflicts and request.POST.get("acknowledge") != "1":
            messages.warning(request, "This event overlaps existing events. Review and confirm to save.")
            return render(request, "calendar/form.html", {
                "form": form, "mode": "create", "conflicts": conflicts,
            })
        with transaction.atomic():
            event.save()
            minutes = form.cleaned_data.get("reminder_minutes")
            if minutes:
                EventReminder.objects.create(event=event, minutes_before=int(minutes))
        log_event(actor=request.user, action="calendar.event_created", resource_type="event",
                  resource_id=event.pk, request=request)
        messages.success(request, "Event created.")
        return redirect("calendar_manager:detail", pk=event.pk)
    if request.method == "POST" and not form.is_valid():
        messages.error(request, "Please correct the errors below.")
    return render(request, "calendar/form.html", {"form": form, "mode": "create"})


@login_required
def event_edit(request, pk):
    event = get_object_or_404(CalendarEvent, pk=pk, owner=request.user)
    form = CalendarEventForm(request.POST or None, instance=event)
    if request.method == "POST" and form.is_valid():
        conflicts = detect_conflicts(request.user, form.cleaned_data["start"],
                                     form.cleaned_data["end"], exclude_pk=event.pk)
        if conflicts and request.POST.get("acknowledge") != "1":
            messages.warning(request, "This event overlaps existing events. Confirm to save.")
            return render(request, "calendar/form.html", {
                "form": form, "mode": "edit", "event": event, "conflicts": conflicts,
            })
        form.save()
        log_event(actor=request.user, action="calendar.event_updated", resource_type="event",
                  resource_id=event.pk, request=request)
        messages.success(request, "Event updated.")
        return redirect("calendar_manager:detail", pk=event.pk)
    return render(request, "calendar/form.html", {"form": form, "mode": "edit", "event": event})


@login_required
def event_delete(request, pk):
    event = get_object_or_404(CalendarEvent, pk=pk, owner=request.user)
    if request.method == "POST":
        log_event(actor=request.user, action="calendar.event_deleted", resource_type="event",
                  resource_id=event.pk, request=request)
        event.delete()
        messages.success(request, "Event deleted.")
        return redirect("calendar_manager:calendar")
    return render(request, "calendar/confirm_delete.html", {"event": event})


@login_required
@require_POST
def event_move(request, pk):
    """Reschedule an event by dragging it to a new day (keeps time-of-day)."""
    event = get_object_or_404(CalendarEvent, pk=pk, owner=request.user)
    target_raw = request.POST.get("date", "")
    try:
        target = date.fromisoformat(target_raw)
    except ValueError:
        return JsonResponse({"ok": False, "error": "Invalid date."}, status=400)

    local_start = timezone.localtime(event.start)
    delta = target - local_start.date()
    if delta.days == 0:
        return JsonResponse({"ok": True, "unchanged": True})

    event.start = event.start + delta
    event.end = event.end + delta
    event.save()
    log_event(actor=request.user, action="calendar.event_moved", resource_type="event",
              resource_id=event.pk, request=request, metadata={"date": target.isoformat()})
    return JsonResponse({
        "ok": True,
        "start": timezone.localtime(event.start).isoformat(),
        "end": timezone.localtime(event.end).isoformat(),
    })


@login_required
def free_slots(request):
    day_param = request.GET.get("date") or timezone.localdate().isoformat()
    try:
        day = date.fromisoformat(day_param)
    except ValueError:
        day = timezone.localdate()
    slots = find_free_slots(request.user, day)
    slot_list = [
        {"start": start, "end": end, "minutes": int((end - start).total_seconds() // 60)}
        for start, end in slots
    ]
    return render(request, "calendar/free_slots.html", {"slots": slot_list, "day": day})


@login_required
def calendar_export(request):
    """Download the authenticated user's events as an iCalendar (.ics) file."""
    body = build_calendar(feed_events(request.user), calendar_name="NexaMind")
    response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="nexamind.ics"'
    return response


def calendar_feed(request, token):
    """Public, read-only feed addressed by an unguessable per-user token."""
    profile = (
        UserProfile.objects.filter(calendar_feed_token=token)
        .select_related("user")
        .first()
    )
    if profile is None or not profile.calendar_feed_token:
        raise Http404("Unknown calendar feed")

    body = build_calendar(feed_events(profile.user), calendar_name="NexaMind")
    response = HttpResponse(body, content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = 'inline; filename="nexamind.ics"'
    return response


@login_required
@require_POST
def calendar_feed_reset(request):
    """Rotate the feed token, invalidating any previously shared URL."""
    reset_calendar_feed_token(request.user)
    log_event(actor=request.user, action="calendar.feed_rotated", request=request)
    messages.success(request, "Calendar feed URL regenerated. Update your subscriptions.")
    return redirect("calendar_manager:calendar")
