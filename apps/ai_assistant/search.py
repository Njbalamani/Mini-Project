"""Unified workspace search shared by the command palette and the search page."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from django.db.models import Q
from django.urls import NoReverseMatch, reverse


@dataclass
class Hit:
    title: str
    subtitle: str = ""
    url: str = ""
    type: str = ""


@dataclass
class Group:
    key: str
    label: str
    icon: str
    hits: list[Hit] = field(default_factory=list)


def _safe_reverse(name: str, *args) -> str:
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return ""


def _tasks(user, q, limit):
    from apps.tasks.models import Task

    hits = []
    for t in (
        Task.objects.filter(owner=user)
        .filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(category__icontains=q))
        .order_by("status", "-priority", "-created_at")[:limit]
    ):
        hits.append(Hit(t.title, t.get_status_display(), _safe_reverse("tasks:detail", t.pk), "task"))
    return hits


def _events(user, q, limit):
    from apps.calendar_manager.models import CalendarEvent

    hits = []
    for e in (
        CalendarEvent.objects.filter(owner=user)
        .filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(location__icontains=q))
        .order_by("-start")[:limit]
    ):
        when = e.start.strftime("%d %b %Y %H:%M") if getattr(e, "start", None) else ""
        hits.append(Hit(e.title, when, _safe_reverse("calendar_manager:detail", e.pk), "event"))
    return hits


def _documents(user, q, limit):
    from apps.documents.models import Document

    hits = []
    for d in (
        Document.objects.filter(owner=user)
        .filter(Q(title__icontains=q) | Q(original_name__icontains=q))
        .order_by("-created_at")[:limit]
    ):
        hits.append(Hit(d.title or d.original_name, d.get_status_display(), _safe_reverse("documents:detail", d.pk), "document"))
    return hits


def _conversations(user, q, limit):
    from apps.ai_assistant.models import Conversation

    hits = []
    for c in (
        Conversation.objects.filter(owner=user)
        .filter(Q(title__icontains=q) | Q(messages__content__icontains=q))
        .distinct()
        .order_by("-updated_at")[:limit]
    ):
        hits.append(Hit(c.title, "AI conversation", _safe_reverse("ai_assistant:conversation", c.pk), "conversation"))
    return hits


def _workflows(user, q, limit):
    from apps.workflow_automation.models import Workflow

    hits = []
    for w in (
        Workflow.objects.filter(owner=user)
        .filter(Q(name__icontains=q) | Q(description__icontains=q))
        .order_by("-created_at")[:limit]
    ):
        hits.append(Hit(w.name, "Enabled" if w.is_enabled else "Disabled", _safe_reverse("workflow_automation:detail", w.pk), "workflow"))
    return hits


def _emails(user, q, limit):
    from apps.email_manager.models import EmailMessageMeta

    hits = []
    for m in (
        EmailMessageMeta.objects.filter(owner=user)
        .filter(Q(subject__icontains=q) | Q(sender__icontains=q) | Q(snippet__icontains=q))
        .order_by("-fetched_at")[:limit]
    ):
        hits.append(Hit(m.subject or "(no subject)", m.sender, _safe_reverse("email_manager:detail", m.pk), "email"))
    return hits


_SEARCHERS: list[tuple[str, str, str, Callable]] = [
    ("tasks", "Tasks", "check", _tasks),
    ("events", "Calendar", "calendar", _events),
    ("documents", "Documents", "doc", _documents),
    ("conversations", "Conversations", "spark", _conversations),
    ("workflows", "Workflows", "bolt", _workflows),
    ("emails", "Email", "mail", _emails),
]


def global_search(user, query: str, per_type: int = 5) -> list[Group]:
    """Return grouped search results across every workspace app for ``user``."""
    query = (query or "").strip()
    if not query or not user.is_authenticated:
        return []
    groups: list[Group] = []
    for key, label, icon, fn in _SEARCHERS:
        try:
            hits = fn(user, query, per_type)
        except Exception:  # pragma: no cover - a single app must not break search
            hits = []
        if hits:
            groups.append(Group(key=key, label=label, icon=icon, hits=hits))
    return groups


def search_count(groups) -> int:
    return sum(len(g.hits) for g in groups)
