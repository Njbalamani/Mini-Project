from django.conf import settings


def site_context(request):
    pending_tasks = 0
    if request.user.is_authenticated:
        from apps.tasks.models import Task

        pending_tasks = Task.objects.filter(owner=request.user).exclude(
            status=Task.Status.DONE
        ).count()
    return {
        "SITE_NAME": settings.NEXAMIND.get("SITE_NAME", "NexaMind"),
        "AI_CONFIGURED": bool(settings.NEXAMIND.get("AI_API_KEY")),
        "AI_PROVIDER": settings.NEXAMIND.get("AI_PROVIDER") or "not configured",
        "pending_task_count": pending_tasks,
    }
