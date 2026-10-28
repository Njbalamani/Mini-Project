"""User data export / portability.

Builds a JSON snapshot of everything a user owns, plus an optional ZIP archive
that also bundles uploaded files (documents and avatars).
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal


def _value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        try:
            return value.decode()
        except UnicodeDecodeError:
            return value.hex()
    return value


def _dump(obj, fields=None):
    data = {}
    for field in obj._meta.concrete_fields:
        if fields and field.name not in fields:
            continue
        data[field.name] = _value(getattr(obj, field.attname))
    return data


def _dump_qs(qs, fields=None):
    return [_dump(obj, fields) for obj in qs]


def build_export_json(user) -> dict:
    from apps.ai_assistant.models import Conversation
    from apps.calendar_manager.models import CalendarEvent
    from apps.documents.models import Document
    from apps.email_manager.models import EmailDraft, EmailMessageMeta
    from apps.integrations.models import Integration
    from apps.notifications.models import Notification
    from apps.tasks.models import SavedTaskFilter, Tag, Task, TaskComment
    from apps.workflow_automation.models import Workflow, WorkflowExecution

    from .models import LoginActivity, UserPreference, UserProfile

    profile = UserProfile.objects.filter(user=user).first()
    preferences = UserPreference.objects.filter(user=user).first()

    conversations = []
    for convo in Conversation.objects.filter(owner=user).order_by("created_at"):
        entry = _dump(convo, fields=["title", "created_at", "updated_at"])
        entry["messages"] = [
            _dump(m, fields=["role", "content", "created_at"])
            for m in convo.messages.all().order_by("created_at")
        ]
        conversations.append(entry)

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": {
            "email": user.email,
            "full_name": user.full_name,
            "is_email_verified": user.is_email_verified,
            "date_joined": _value(user.date_joined),
        },
        "profile": _dump(profile, fields=[
            "bio", "job_title", "company", "timezone", "language", "theme",
        ]) if profile else None,
        "preferences": _dump(preferences, fields=[
            "email_notifications", "in_app_notifications", "task_reminders",
            "workflow_notifications", "integration_alerts", "weekly_digest",
        ]) if preferences else None,
        "tasks": _dump_qs(Task.objects.filter(owner=user)),
        "task_tags": _dump_qs(Tag.objects.filter(owner=user)),
        "task_comments": _dump_qs(TaskComment.objects.filter(task__owner=user)),
        "saved_task_filters": _dump_qs(SavedTaskFilter.objects.filter(owner=user)),
        "events": _dump_qs(CalendarEvent.objects.filter(owner=user)),
        "documents": _dump_qs(Document.objects.filter(owner=user)),
        "conversations": conversations,
        "workflows": _dump_qs(Workflow.objects.filter(owner=user)),
        "workflow_executions": _dump_qs(WorkflowExecution.objects.filter(workflow__owner=user)),
        "emails": _dump_qs(EmailMessageMeta.objects.filter(owner=user)),
        "email_drafts": _dump_qs(EmailDraft.objects.filter(owner=user)),
        "notifications": _dump_qs(Notification.objects.filter(user=user)),
        "integrations": _dump_qs(Integration.objects.filter(user=user), fields=[
            "provider", "status", "created_at",
        ]),
        "login_activity": _dump_qs(LoginActivity.objects.filter(user=user)[:200]),
    }


def _read_file(field_file):
    if not field_file:
        return None
    try:
        with field_file.open("rb") as handle:
            return handle.read()
    except (FileNotFoundError, ValueError):
        return None


def build_export_zip(user) -> bytes:
    from apps.documents.models import Document

    from .models import UserProfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "export.json",
            json.dumps(build_export_json(user), indent=2, default=str),
        )
        for doc in Document.objects.filter(owner=user):
            content = _read_file(getattr(doc, "file", None))
            if content is not None:
                archive.writestr(f"documents/{doc.pk}-{doc.file.name.split('/')[-1]}", content)
        profile = UserProfile.objects.filter(user=user).first()
        if profile and profile.avatar:
            content = _read_file(profile.avatar)
            if content is not None:
                archive.writestr(
                    f"avatars/{profile.avatar.name.split('/')[-1]}", content
                )
    return buffer.getvalue()
