"""Conversation orchestration service."""
from __future__ import annotations

import logging

from django.conf import settings
from django.utils import timezone

from apps.audit_logs.services import log_event

from .commands import execute as run_slash_command, is_command

from ..models import AIUsageRecord, Conversation, Message
from .context import build_authorized_context
from .providers import AIError, AINotConfigured, AIResponse, OfflineDemoProvider, _extract_json, get_provider
from .schemas import validate_proposed_actions

logger = logging.getLogger("nexamind.ai")

SYSTEM_PROMPT = """You are NexaMind, a professional AI assistant embedded in the user's
productivity workspace. Be concise, accurate and helpful. You may ONLY reference the
authorized workspace summary provided to you; never invent tasks, events or data.

When the user asks you to create a task or event, respond with a short confirmation,
then include a single JSON object on its own enclosed in a ```json code fence with the
shape:
{"actions": [{"type": "create_task", "payload": {"title": "...", "priority": "low|medium|high|urgent", "due_date": "ISO-8601 or null", "category": "...", "description": "..."}}]}
or
{"actions": [{"type": "create_event", "payload": {"title": "...", "start": "ISO-8601", "end": "ISO-8601", "location": "...", "description": "..."}}]}
Use {"actions": []} when no structured action is needed. Propose at most 3 actions.
Never propose actions that modify data outside the JSON contract above.
"""


def get_or_create_conversation(user, conversation_id=None, title="New conversation"):
    if conversation_id:
        convo = Conversation.objects.filter(pk=conversation_id, owner=user).first()
        if convo:
            return convo
    return Conversation.objects.create(owner=user, title=title)


def build_message_history(conversation, limit=12):
    history = list(
        conversation.messages.exclude(role=Message.Role.SYSTEM)
        .order_by("-created_at")[:limit]
    )
    history.reverse()
    return [{"role": m.role if m.role in {"user", "assistant"} else "assistant",
             "content": m.content} for m in history]


def _chunk_text(text):
    for word in text.split(" "):
        yield word + " "


def _save_command_turn(user, conversation, user_text, result):
    assistant_message = Message.objects.create(
        conversation=conversation, role=Message.Role.ASSISTANT,
        content=result["reply"],
        structured={"command": True, **({"link": result["link"]} if result.get("link") else {})},
    )
    conversation.save(update_fields=["updated_at"])
    log_event(actor=user, action="ai.slash_command", resource_type="conversation",
              resource_id=conversation.pk, metadata={"command": user_text.split()[0][:40]})
    return assistant_message, result.get("link")


def _command_result(user, conversation, user_text, user_message):
    result = run_slash_command(user, user_text)
    assistant_message, link = _save_command_turn(user, conversation, user_text, result)
    return {
        "ok": True, "configured": True, "error": "", "user_message": user_message,
        "assistant_message": assistant_message, "actions": [], "action_errors": [],
        "link": link,
    }


def generate_reply(user, conversation, user_text, extra_context=""):
    """Produce an assistant reply, validate actions and persist both messages.

    Returns a dict describing the outcome rather than raising, so callers can
    render an appropriate message for configuration/upstream failures.
    """
    user_message = Message.objects.create(
        conversation=conversation, role=Message.Role.USER, content=user_text
    )

    if conversation.title == "New conversation":
        conversation.auto_title()

    if is_command(user_text):
        return _command_result(user, conversation, user_text, user_message)

    try:
        provider = get_provider(user)
    except AINotConfigured as exc:
        AIUsageRecord.objects.create(
            user=user, conversation=conversation, provider="none", success=False,
            error=str(exc)[:300],
        )
        return {
            "ok": False, "configured": False, "error": str(exc),
            "user_message": user_message, "assistant_message": None,
            "actions": [], "action_errors": [],
        }

    system = SYSTEM_PROMPT + "\n" + build_authorized_context(user, extra=extra_context)
    history = build_message_history(conversation)

    try:
        response = provider.complete(history, system=system)
    except AIError as exc:
        AIUsageRecord.objects.create(
            user=user, conversation=conversation, provider=provider.name,
            success=False, error=str(exc)[:300],
        )
        log_event(actor=user, action="ai.request_failed",
                  metadata={"provider": provider.name})
        return {
            "ok": False, "configured": True, "error": str(exc),
            "user_message": user_message, "assistant_message": None,
            "actions": [], "action_errors": [],
        }

    actions, action_errors = validate_proposed_actions(
        (response.structured or {}).get("actions")
    )

    assistant_message = Message.objects.create(
        conversation=conversation, role=Message.Role.ASSISTANT,
        content=response.text or "(no content returned)",
        structured={"actions": actions} if actions else {},
        token_count=response.total_tokens,
    )
    conversation.save(update_fields=["updated_at"])
    AIUsageRecord.objects.create(
        user=user, conversation=conversation, provider=response.provider,
        model=response.model, prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens, total_tokens=response.total_tokens,
        success=True,
    )
    log_event(actor=user, action="ai.response_generated", resource_type="conversation",
              resource_id=conversation.pk,
              metadata={"provider": response.provider, "tokens": response.total_tokens})
    return {
        "ok": True, "configured": True, "error": "", "user_message": user_message,
        "assistant_message": assistant_message, "actions": actions,
        "action_errors": action_errors,
    }


def stream_reply(user, conversation, user_text):
    """Generator yielding streamed events for a chat turn.

    Yields dicts with a ``type`` of ``start``/``delta``/``error``/``done`` so the
    view can serialize them as SSE. Provides true token-by-token streaming for
    configured providers and a deterministic fallback otherwise.
    """
    user_message = Message.objects.create(
        conversation=conversation, role=Message.Role.USER, content=user_text
    )
    if conversation.title == "New conversation":
        conversation.auto_title()
    yield {
        "type": "start",
        "user_message": {
            "role": "user", "content": user_text,
            "created_at": timezone.localtime(user_message.created_at).strftime("%H:%M"),
        },
    }

    if is_command(user_text):
        result = run_slash_command(user, user_text)
        for chunk in _chunk_text(result["reply"]):
            yield {"type": "delta", "content": chunk}
        assistant_message, link = _save_command_turn(user, conversation, user_text, result)
        yield {
            "type": "done",
            "assistant_message": {
                "id": assistant_message.pk,
                "role": "assistant",
                "content": assistant_message.content,
                "created_at": timezone.localtime(assistant_message.created_at).strftime("%H:%M"),
                "actions": [],
                "link": link,
            },
            "action_errors": [],
        }
        return

    try:
        provider = get_provider(user)
        system = SYSTEM_PROMPT + "\n" + build_authorized_context(user)
        history = build_message_history(conversation)
    except AINotConfigured as exc:
        AIUsageRecord.objects.create(
            user=user, conversation=conversation, provider="none", success=False,
            error=str(exc)[:300],
        )
        yield {"type": "error", "configured": False, "message": str(exc)}
        return

    content_parts = []
    try:
        chunks = provider.stream_chunks(history, system=system)
        for chunk in chunks:
            content_parts.append(chunk)
            yield {"type": "delta", "content": chunk}
    except AIError as exc:
        AIUsageRecord.objects.create(
            user=user, conversation=conversation, provider=provider.name,
            success=False, error=str(exc)[:300],
        )
        log_event(actor=user, action="ai.request_failed",
                  metadata={"provider": provider.name})
        yield {"type": "error", "configured": True, "message": str(exc)}
        return

    text = "".join(content_parts).strip() or "(no content returned)"
    structured = getattr(provider, "last_structured", None)
    if structured is None:
        structured = _extract_json(text) or {}
    actions, action_errors = validate_proposed_actions(structured.get("actions"))

    assistant_message = Message.objects.create(
        conversation=conversation, role=Message.Role.ASSISTANT,
        content=text, structured={"actions": actions} if actions else {},
        token_count=0 if isinstance(provider, OfflineDemoProvider) else len(text),
    )
    conversation.save(update_fields=["updated_at"])
    AIUsageRecord.objects.create(
        user=user, conversation=conversation, provider=provider.name,
        model=getattr(provider, "model", ""), success=True,
        completion_tokens=assistant_message.token_count,
    )
    log_event(actor=user, action="ai.response_generated", resource_type="conversation",
              resource_id=conversation.pk,
              metadata={"provider": provider.name, "streamed": True,
                        "tokens": assistant_message.token_count})
    yield {
        "type": "done",
        "assistant_message": {
            "id": assistant_message.pk,
            "role": "assistant",
            "content": assistant_message.content,
            "created_at": timezone.localtime(assistant_message.created_at).strftime("%H:%M"),
            "actions": actions,
        },
        "action_errors": action_errors,
    }
