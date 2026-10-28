"""Dashboard and public landing views, plus error handlers."""
import json

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone

from .selectors import build_dashboard


def landing(request):
    features = [
        {"icon": "spark", "title": "Conversational AI",
         "text": "Summarize tasks, draft emails, plan your day and generate workflows by simply asking."},
        {"icon": "check", "title": "Smart task manager",
         "text": "Priorities, deadlines, categories, history — plus list and Kanban views powered by real data."},
        {"icon": "calendar", "title": "Smart calendar",
         "text": "Timezone-aware events, recurrence, conflict detection and free-slot suggestions."},
        {"icon": "mail", "title": "Email assistant",
         "text": "Read-only Gmail metadata, AI summaries, replies and action items — never sent without approval."},
        {"icon": "bolt", "title": "Visual workflow builder",
         "text": "Triggers, conditions and actions with execution history, retries and idempotency built in."},
        {"icon": "doc", "title": "Document intelligence",
         "text": "PDF, DOCX and TXT processing with summaries, keywords, dates and evidence-backed Q&A."},
        {"icon": "chart", "title": "Productivity analytics",
         "text": "Server-aggregated metrics and trends — never fabricated, always derived from your data."},
        {"icon": "shield", "title": "Security first",
         "text": "Server-side authorization, encrypted tokens, audit logging and rate limiting everywhere."},
    ]
    return render(request, "landing/home.html", {"features": features})


@login_required
def dashboard_home(request):
    data = build_dashboard(request.user)
    hour = timezone.localtime().hour
    greeting = "morning" if hour < 12 else ("afternoon" if hour < 18 else "evening")
    return render(request, "dashboard/home.html", {
        "data": data,
        "greeting": greeting,
        "trend_json": json.dumps(data["trend"]),
        "status_json": json.dumps(data["status_breakdown"]),
    })


def error_404(request, exception=None):
    return render(request, "errors/404.html", status=404)


def error_500(request):
    return render(request, "errors/500.html", status=500)
