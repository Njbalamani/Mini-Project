"""Analytics views."""
import json
from datetime import datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

from .selectors import build_report


def _parse_range(request):
    end = timezone.now()
    start = end - timedelta(days=30)
    start_param = request.GET.get("start")
    end_param = request.GET.get("end")
    if start_param:
        try:
            start = timezone.make_aware(datetime.fromisoformat(start_param))
        except ValueError:
            pass
    if end_param:
        try:
            end_dt = datetime.fromisoformat(end_param)
            end = timezone.make_aware(end_dt.replace(hour=23, minute=59, second=59))
        except ValueError:
            pass
    if start > end:
        start = end - timedelta(days=30)
    return start, end


@login_required
def analytics_home(request):
    start, end = _parse_range(request)
    report = build_report(request.user, start, end)
    return render(request, "analytics/home.html", {
        "report": report,
        "start": start.date().isoformat(),
        "end": end.date().isoformat(),
        "trend_json": json.dumps(report["trend"]),
        "workflows_json": json.dumps({"succeeded": report["succeeded"], "failed": report["failed"]}),
        "status_json": json.dumps(report["status_breakdown"]),
    })


@login_required
def analytics_data(request):
    start, end = _parse_range(request)
    report = build_report(request.user, start, end)
    report["range"]["start"] = report["range"]["start"].isoformat()
    report["range"]["end"] = report["range"]["end"].isoformat()
    return JsonResponse(report)
