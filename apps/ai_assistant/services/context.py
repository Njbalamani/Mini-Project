"""Builds the authorized context that is safe to send to the AI provider.

Only data owned by (or explicitly shared with) the requesting user is included.
Passwords, tokens, credentials and full email/document bodies are never added.
"""
from django.utils import timezone

from apps.calendar_manager.models import CalendarEvent
from apps.tasks.models import Task


def build_context_summary(user) -> str:
    lines = []
    tasks = Task.objects.filter(owner=user)
    total = tasks.count()
    done = tasks.filter(status=Task.Status.DONE).count()
    overdue = tasks.open_tasks().filter(due_date__lt=timezone.now()).count()
    lines.append(f"- Tasks: {total} total, {done} completed, {total - done} open, {overdue} overdue.")

    upcoming = tasks.open_tasks().exclude(due_date=None).order_by("due_date")[:5]
    for task in upcoming:
        priority = task.get_priority_display()
        due = timezone.localtime(task.due_date).strftime("%a %d %b %H:%M")
        lines.append(f"- Open task: \"{task.title}\" ({priority}), due {due}.")

    events = CalendarEvent.objects.filter(
        owner=user, end__gte=timezone.now()
    ).order_by("start")[:5]
    for event in events:
        start = timezone.localtime(event.start).strftime("%a %d %b %H:%M")
        lines.append(f"- Upcoming event: \"{event.title}\" at {start}.")

    if not lines:
        lines.append("- The workspace is empty; no tasks or events yet.")
    return "\n".join(lines)


def build_workspace_items(user, limit=60):
    """Return a compact, structured view of the user's own items for the local
    reasoner. Only the requesting user's rows are included."""
    items = []
    for task in Task.objects.filter(owner=user).order_by("due_date")[:limit]:
        items.append({
            "type": "task",
            "title": task.title,
            "due": task.due_date.isoformat() if task.due_date else None,
            "priority": task.get_priority_display().lower(),
            "done": task.status == Task.Status.DONE,
        })
    for event in CalendarEvent.objects.filter(owner=user).order_by("start")[:limit]:
        items.append({
            "type": "event",
            "title": event.title,
            "start": event.start.isoformat() if event.start else None,
            "end": event.end.isoformat() if event.end else None,
            "location": getattr(event, "location", "") or "",
        })
    return items


def build_authorized_context(user, extra=""):
    """Return the system prompt context scoped to this user."""
    summary = build_context_summary(user)
    return (
        f"Current date/time: {timezone.now().isoformat()}\n"
        f"User timezone: {timezone.get_current_timezone()}\n"
        "Authorized workspace summary (this is the ONLY user data you may reference):\n"
        f"{summary}\n"
        f"{extra}"
    )
