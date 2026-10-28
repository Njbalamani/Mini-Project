"""AI assistant views: chat, conversations, actions, export and feedback."""
import csv
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit_logs.services import log_event
from apps.calendar_manager.models import CalendarEvent
from apps.subscriptions.services import check_limit
from apps.tasks.services import create_task

from .forms import AIConfigForm
from .models import AssistantFeedback, Conversation, Message
from .search import global_search, search_count
from .services import (
    AINotConfigured,
    generate_reply,
    get_provider,
    learn_correction,
    learn_from_feedback,
    stream_reply,
    training_stats,
)
from .services.context import build_workspace_items
from .services.local_ml import LocalAssistant, intent_metrics, textrank_keywords
from .services.schemas import ActionValidationError, validate_action


def _provider_status(user):
    try:
        return {"configured": True, "name": get_provider(user).name}
    except AINotConfigured:
        return {"configured": False, "name": "not configured"}


@login_required
def assistant_home(request):
    conversations = Conversation.objects.filter(owner=request.user, is_archived=False)
    return render(request, "assistant/home.html", {
        "conversations": conversations[:50],
        "provider": _provider_status(request.user),
    })


@login_required
def conversation_detail(request, pk):
    conversation = get_object_or_404(Conversation, pk=pk, owner=request.user)
    msg = conversation.messages.all()
    return render(request, "assistant/conversation.html", {
        "conversation": conversation,
        "messages": msg,
        "provider": _provider_status(request.user),
        "conversations": Conversation.objects.filter(owner=request.user, is_archived=False)[:50],
    })


@login_required
@require_POST
def new_conversation(request):
    conversation = Conversation.objects.create(owner=request.user, title="New conversation")
    return redirect("ai_assistant:conversation", pk=conversation.pk)


@login_required
@require_POST
def send_message(request, pk):
    conversation = get_object_or_404(Conversation, pk=pk, owner=request.user)
    text = (request.POST.get("message") or "").strip()
    if not text:
        return JsonResponse({"ok": False, "error": "Message cannot be empty."}, status=400)

    allowed, reason = check_limit(request.user, "ai_messages")
    if not allowed:
        return JsonResponse({"ok": False, "error": reason}, status=429)

    wants_stream = (
        request.headers.get("Accept", "").startswith("text/event-stream")
        or request.POST.get("stream") == "1"
    )
    if wants_stream:
        return _stream_response(request.user, conversation, text)

    result = generate_reply(request.user, conversation, text)
    payload = {
        "ok": result["ok"],
        "configured": result.get("configured", True),
        "error": result.get("error", ""),
        "action_errors": result.get("action_errors", []),
        "user_message": {
            "role": "user", "content": text,
            "created_at": timezone.localtime(result["user_message"].created_at).strftime("%H:%M"),
        } if result.get("user_message") else None,
    }
    if result.get("assistant_message"):
        payload["assistant_message"] = {
            "id": result["assistant_message"].pk,
            "role": "assistant",
            "content": result["assistant_message"].content,
            "created_at": timezone.localtime(result["assistant_message"].created_at).strftime("%H:%M"),
            "actions": result.get("actions", []),
            "link": result.get("link"),
        }
    return JsonResponse(payload)


def _stream_response(user, conversation, text):
    """Stream a reply as Server-Sent Events (text/event-stream)."""

    def event_stream():
        for event in stream_reply(user, conversation, text):
            yield f"data: {json.dumps(event)}\n\n"

    response = StreamingHttpResponse(
        event_stream(), content_type="text/event-stream"
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
@require_POST
def delete_conversation(request, pk):
    conversation = get_object_or_404(Conversation, pk=pk, owner=request.user)
    log_event(actor=request.user, action="ai.conversation_deleted",
              resource_type="conversation", resource_id=conversation.pk, request=request)
    conversation.delete()
    messages.success(request, "Conversation deleted.")
    return redirect("ai_assistant:home")


@login_required
def conversation_search(request):
    q = request.GET.get("q", "").strip()
    groups = global_search(request.user, q, per_type=20) if q else []
    paginator = Paginator([h for g in groups for h in g.hits], 20)
    return render(request, "assistant/search.html", {
        "q": q,
        "groups": groups,
        "total": search_count(groups),
        "page_obj": paginator.get_page(request.GET.get("page")),
    })


@login_required
def quick_search(request):
    """JSON endpoint powering the Ctrl+K command palette."""
    q = request.GET.get("q", "").strip()
    groups = global_search(request.user, q, per_type=5)
    return JsonResponse({
        "ok": True,
        "query": q,
        "total": search_count(groups),
        "groups": [
            {
                "key": g.key, "label": g.label, "icon": g.icon,
                "hits": [
                    {"title": h.title, "subtitle": h.subtitle, "url": h.url, "type": h.type}
                    for h in g.hits
                ],
            }
            for g in groups
        ],
    })


@login_required
def export_conversation(request, pk):
    conversation = get_object_or_404(Conversation, pk=pk, owner=request.user)
    fmt = request.GET.get("format", "txt")
    if fmt == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="conversation-{pk}.csv"'
        writer = csv.writer(response)
        writer.writerow(["timestamp", "role", "content"])
        for m in conversation.messages.all():
            writer.writerow([m.created_at.isoformat(), m.role, m.content])
        return response
    body = [f"NexaMind conversation: {conversation.title}",
            f"Exported: {timezone.now().isoformat()}", ""]
    for m in conversation.messages.all():
        body.append(f"[{m.created_at:%Y-%m-%d %H:%M}] {m.role.upper()}")
        body.append(m.content)
        body.append("")
    response = HttpResponse("\n".join(body), content_type="text/plain")
    response["Content-Disposition"] = f'attachment; filename="conversation-{pk}.txt"'
    return response


@login_required
@require_POST
def message_feedback(request, pk):
    message = get_object_or_404(Message, pk=pk, conversation__owner=request.user)
    try:
        rating = int(request.POST.get("rating"))
    except (TypeError, ValueError):
        return JsonResponse({"ok": False, "error": "Invalid rating."}, status=400)
    if rating not in (1, -1):
        return JsonResponse({"ok": False, "error": "Rating must be 1 or -1."}, status=400)
    AssistantFeedback.objects.update_or_create(
        message=message, defaults={
            "user": request.user, "rating": rating,
            "comment": (request.POST.get("comment") or "")[:400],
        },
    )
    learn_from_feedback(message, rating)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def message_correction(request, pk):
    """Teach the local ML engine the correct intent for the user's message."""
    message = get_object_or_404(Message, pk=pk, conversation__owner=request.user)
    intent = (request.POST.get("intent") or "").strip()
    if not intent:
        return JsonResponse({"ok": False, "error": "Missing intent."}, status=400)
    user_text = message.content
    if message.role != Message.Role.USER:
        previous = (
            Message.objects.filter(
                conversation=message.conversation, role=Message.Role.USER,
                created_at__lte=message.created_at,
            ).order_by("-created_at").first()
        )
        if previous:
            user_text = previous.content
    learn_correction(request.user, user_text, intent)
    return JsonResponse({"ok": True, "intent": intent})


@login_required
def assistant_insights(request):
    """Show the offline ML pipeline, its algorithms and what it has learned."""
    now = timezone.now()
    items = build_workspace_items(request.user)
    assistant = LocalAssistant(now)
    examples = assistant.examples
    clusters = [
        [m.get("title", "") for m in group]
        for group in assistant.cluster_items(items, k=min(4, max(1, len(items) // 2)))
    ]
    keywords = textrank_keywords(" ".join(it.get("title", "") for it in items), top_k=12)
    report = intent_metrics(examples, n_splits=3)
    return render(request, "assistant/insights.html", {
        "provider": _provider_status(request.user),
        "stats": training_stats(request.user),
        "clusters": clusters,
        "keywords": keywords,
        "item_count": len(items),
        "intents": sorted({label for label, _ in examples}),
        "model_names": assistant.classifier.model_names(),
        "metric_accuracy": report["accuracy"],
        "metric_f1": report["macro"]["f1"],
        "metric_precision": report["macro"]["precision"],
        "metric_recall": report["macro"]["recall"],
        "example_count": len(examples),
        "fold_count": 3,
        "per_class": report["labels"],
    })


@login_required
def autocomplete(request):
    """Suggest the next words using the n-gram language model over user data."""
    from .services.learning import corpus_for
    from .services.local_ml import NGramLanguageModel

    prefix = request.GET.get("q", "").strip()
    corpus = corpus_for(request.user)
    corpus += [it.get("title", "") for it in build_workspace_items(request.user)]
    model = NGramLanguageModel(order=2).train(corpus)
    return JsonResponse({
        "ok": True,
        "query": prefix,
        "suggestions": model.autocomplete(prefix, max_results=6) if prefix else [],
    })


def _execute_action(user, action, request):
    """Create the real object for a confirmed, already-validated action."""
    action_type = action.get("type")
    payload = action.get("payload", {})
    if action_type == "create_task":
        allowed, reason = check_limit(user, "tasks")
        if not allowed:
            return False, reason
        from django.utils.dateparse import parse_datetime
        due = parse_datetime(payload["due_date"]) if payload.get("due_date") else None
        task = create_task(
            user, title=payload["title"], description=payload.get("description", ""),
            priority=payload.get("priority", "medium"),
            category=payload.get("category", ""), due_date=due, actor=user,
        )
        log_event(actor=user, action="ai.action_executed", resource_type="task",
                  resource_id=task.pk, request=request, metadata={"via": "assistant"})
        return True, task
    if action_type == "create_event":
        from django.utils.dateparse import parse_datetime
        start = parse_datetime(payload["start"])
        end = parse_datetime(payload["end"])
        event = CalendarEvent.objects.create(
            owner=user, title=payload["title"], description=payload.get("description", ""),
            location=payload.get("location", ""), start=start, end=end,
        )
        log_event(actor=user, action="ai.action_executed", resource_type="event",
                  resource_id=event.pk, request=request, metadata={"via": "assistant"})
        return True, event
    if action_type == "create_workflow":
        from apps.workflow_automation.models import Workflow, WorkflowAction, WorkflowTrigger
        allowed, reason = check_limit(user, "workflows")
        if not allowed:
            return False, reason
        workflow = Workflow.objects.create(
            owner=user, name=payload["name"], description=payload.get("description", ""),
        )
        WorkflowTrigger.objects.create(workflow=workflow, trigger_type=payload["trigger"])
        WorkflowAction.objects.create(workflow=workflow, action_type=payload["action"], order=1)
        log_event(actor=user, action="ai.action_executed", resource_type="workflow",
                  resource_id=workflow.pk, request=request, metadata={"via": "assistant"})
        return True, workflow
    return False, "Unsupported action."


@login_required
@require_POST
def execute_action(request):
    """Validate and execute a proposed action after explicit user confirmation."""
    try:
        raw = json.loads(request.body or "{}")
        action = validate_action(raw.get("action", {}))
    except (json.JSONDecodeError, ActionValidationError) as exc:
        msg = "; ".join(getattr(exc, "errors", [])) or "Invalid action payload."
        return JsonResponse({"ok": False, "error": msg}, status=400)

    ok, result = _execute_action(request.user, action, request)
    if not ok:
        return JsonResponse({"ok": False, "error": result}, status=400)
    url = ""
    if action["type"] == "create_task":
        url = redirect("tasks:detail", pk=result.pk).url
        label = f'Task "{result.title}" created.'
    elif action["type"] == "create_event":
        url = redirect("calendar_manager:detail", pk=result.pk).url
        label = f'Event "{result.title}" created.'
    else:
        url = redirect("workflow_automation:detail", pk=result.pk).url
        label = f'Workflow "{result.name}" created.'
    return JsonResponse({"ok": True, "label": label, "url": url})


@login_required
def ai_settings(request):
    config = getattr(request.user, "ai_config", None)
    from .models import AIProviderConfiguration
    config, _ = AIProviderConfiguration.objects.get_or_create(user=request.user)
    form = AIConfigForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "AI preferences saved.")
        return redirect("ai_assistant:settings")
    return render(request, "assistant/settings.html", {
        "form": form, "provider": _provider_status(request.user),
    })
