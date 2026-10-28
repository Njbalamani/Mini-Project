"""iCalendar (RFC 5545) serialisation for calendar exports and subscribed feeds.

Kept free of Django request/settings dependencies so it can be unit tested and
reused from management commands. All datetimes are emitted in UTC (``Z``) so
that subscribing clients localise them correctly.
"""
from datetime import timezone as datetime_timezone

from django.utils import timezone

PRODID = "-//NexaMind//Calendar//EN"

#: Map of the model's recurrence choices to RRULE values.
RRULES = {
    "daily": "FREQ=DAILY",
    "weekly": "FREQ=WEEKLY",
    "monthly": "FREQ=MONTHLY",
}


def escape_text(value):
    """Escape a text value for use inside a content line (RFC 5545 3.3.11)."""
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def fold_line(line, limit=75):
    """Fold a content line to ``limit`` octets, as required by RFC 5545 3.1."""
    encoded = line.encode("utf-8")
    if len(encoded) <= limit:
        return line
    chunks = [encoded[:limit]]
    rest = encoded[limit:]
    while rest:
        chunks.append(rest[: limit - 1])
        rest = rest[limit - 1 :]
    parts = [chunks[0].decode("utf-8", "ignore")]
    parts.extend(" " + chunk.decode("utf-8", "ignore") for chunk in chunks[1:])
    return "\r\n".join(parts)


def _fmt(dt):
    return dt.astimezone(datetime_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_vevent(event, dtstamp=None):
    """Return the list of (possibly folded) lines for one event."""
    dtstamp = dtstamp or timezone.now()
    lines = [
        "BEGIN:VEVENT",
        f"UID:event-{event.pk}@nexamind",
        f"DTSTAMP:{_fmt(dtstamp)}",
        f"DTSTART:{_fmt(event.start)}",
        f"DTEND:{_fmt(event.end)}",
        f"SUMMARY:{escape_text(event.title)}",
    ]
    if event.description:
        lines.append(f"DESCRIPTION:{escape_text(event.description)}")
    if event.location:
        lines.append(f"LOCATION:{escape_text(event.location)}")
    if event.recurrence in RRULES:
        lines.append(f"RRULE:{RRULES[event.recurrence]}")
    lines.append("END:VEVENT")
    return [fold_line(line) for line in lines]


def build_calendar(events, calendar_name="NexaMind", dtstamp=None):
    """Serialise an iterable of events into a complete VCALENDAR document."""
    dtstamp = dtstamp or timezone.now()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        fold_line(f"X-WR-CALNAME:{escape_text(calendar_name)}"),
    ]
    for event in events:
        lines.extend(build_vevent(event, dtstamp))
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
