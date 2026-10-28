"""Slash-command handling for the AI assistant.

Commands run deterministically on the server (no model call) so they work even
when no AI provider is configured. Each returns a plain-text reply plus an
optional deep link the UI can surface.
"""
from __future__ import annotations

from datetime import timedelta

from django.urls import NoReverseMatch, reverse
from django.utils import timezone

HELP = (
    "Available commands:\n"
    "• /task <title> — create a task\n"
    "• /event <title> — schedule a 1-hour event\n"
    "• /event <title> | YYYY-MM-DD HH:MM — schedule at a specific time\n"
    "• /email <to> | <subject> | <body> — draft an email\n"
    "• /summarize — summarise your workspace\n"
    "• /help — show this list"
)


def _safe_reverse(name, **kwargs):
    try:
        return reverse(name, kwargs=kwargs)
    except NoReverseMatch:
        return ""


def is_command(text):
    return bool(text) and text.strip().startswith("/")


def _cmd_task(user, arg):
    from apps.tasks.services import create_task

    title = arg.strip()
    if not title:
        return {"reply": "Usage: /task <title>", "link": None}
    task = create_task(user, title=title, actor=user)
    return {
        "reply": f"Created task “{task.title}”.",
        "link": {"label": "Open task", "url": _safe_reverse("tasks:detail", pk=task.pk)},
    }


def _cmd_event(user, arg):
    from apps.calendar_manager.models import CalendarEvent

    parts = [p.strip() for p in arg.split("|", 1)]
    title = parts[0]
    if not title:
        return {"reply": "Usage: /event <title> | YYYY-MM-DD HH:MM", "link": None}

    start = None
    if len(parts) == 2 and parts[1]:
        from django.utils.dateparse import parse_datetime

        start = parse_datetime(parts[1])
        if start is None:
            start = parse_datetime(parts[1].replace(" ", "T"))
        if start is None:
            return {"reply": "Could not read that date. Use YYYY-MM-DD HH:MM.", "link": None}
    if start is None:
        start = timezone.now().replace(second=0, microsecond=0) + timedelta(hours=1)
    if timezone.is_naive(start):
        start = timezone.make_aware(start, timezone.get_current_timezone())

    event = CalendarEvent(
        owner=user, title=title, start=start, end=start + timedelta(hours=1),
        timezone=str(timezone.get_current_timezone()),
    )
    event.full_clean(exclude=["owner"])
    event.save()
    when = timezone.localtime(start).strftime("%b %d, %H:%M")
    return {
        "reply": f"Scheduled “{event.title}” for {when}.",
        "link": {"label": "Open calendar", "url": _safe_reverse("calendar_manager:calendar")},
    }


def _cmd_email(user, arg):
    from apps.email_manager.models import EmailDraft

    parts = [p.strip() for p in arg.split("|")]
    to = parts[0] if parts and parts[0] else ""
    subject = parts[1] if len(parts) > 1 else "(no subject)"
    body = parts[2] if len(parts) > 2 else ""
    draft = EmailDraft.objects.create(owner=user, to=to, subject=subject, body=body)
    return {
        "reply": f"Drafted email to {to or 'nobody'} — subject “{subject}”.",
        "link": {"label": "Open drafts", "url": _safe_reverse("email_manager:home")},
    }


def _cmd_summarize(user, _arg):
    from apps.ai_assistant.models import Conversation
    from apps.calendar_manager.models import CalendarEvent
    from apps.documents.models import Document
    from apps.tasks.models import Task

    open_tasks = Task.objects.filter(owner=user).exclude(status=Task.Status.DONE)
    overdue = [t for t in open_tasks if t.is_overdue]
    now = timezone.now()
    upcoming = CalendarEvent.objects.filter(
        owner=user, start__gte=now, start__lte=now + timedelta(days=7)
    ).count()
    docs = Document.objects.filter(owner=user).count()
    convos = Conversation.objects.filter(owner=user).count()
    reply = (
        f"Here's your workspace at a glance:\n"
        f"• {open_tasks.count()} open tasks ({len(overdue)} overdue)\n"
        f"• {upcoming} events in the next 7 days\n"
        f"• {docs} documents, {convos} conversations"
    )
    return {"reply": reply, "link": {"label": "Open dashboard", "url": _safe_reverse("dashboard:home")}}


COMMANDS = {
    "help": lambda user, arg: {"reply": HELP, "link": None},
    "task": _cmd_task,
    "event": _cmd_event,
    "email": _cmd_email,
    "summarize": _cmd_summarize,
    "summary": _cmd_summarize,
}


def execute(user, text):
    """Run a slash command. Returns a dict, or None if not a command.

    The returned dict has ``reply`` (str) and ``link`` ({label, url} | None).
    """
    if not is_command(text):
        return None
    stripped = text.strip()[1:]
    name, _, arg = stripped.partition(" ")
    handler = COMMANDS.get(name.lower())
    if handler is None:
        return {"reply": f"Unknown command “/{name}”.\n\n{HELP}", "link": None}
    return handler(user, arg)
