"""Notification center views. Users can only ever access their own rows."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import Notification
from .services import build_digest, notify


@login_required
def notification_list(request):
    qs = Notification.objects.filter(user=request.user)
    unread_only = request.GET.get("unread") == "1"
    type_filter = request.GET.get("type", "").strip()
    if unread_only:
        qs = qs.filter(is_read=False)
    if type_filter:
        qs = qs.filter(type=type_filter)
    paginator = Paginator(qs, 25)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "notifications/list.html", {
        "page_obj": page,
        "types": Notification.TYPE_CHOICES,
        "unread_only": unread_only,
        "current_type": type_filter,
        "unread_count": Notification.objects.filter(user=request.user, is_read=False).count(),
    })


@login_required
@require_POST
def mark_read(request, pk):
    note = get_object_or_404(Notification, pk=pk, user=request.user)
    note.mark_read()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "unread": Notification.objects.filter(
            user=request.user, is_read=False).count()})
    return redirect(note.url or "notifications:list")


@login_required
@require_POST
def mark_all_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    messages.success(request, "All notifications marked as read.")
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "unread": 0})
    return redirect("notifications:list")


@login_required
def digest_preview(request):
    """Preview the workspace digest that would be sent, without creating it."""
    digest = build_digest(request.user, days=7)
    return render(request, "notifications/digest.html", {
        "digest": digest,
        "sent": request.GET.get("sent") == "1",
    })


@login_required
@require_POST
def digest_send(request):
    """Create the digest notification for the current user on demand."""
    digest = build_digest(request.user, days=7)
    result = notify(
        request.user,
        type="system",
        level="info",
        title="Your NexaMind digest",
        message=digest["message"],
        url="/app/",
    )
    if result is None:
        messages.info(request, "Digest not delivered — in-app notifications are disabled in your preferences.")
        return redirect("notifications:digest")
    messages.success(request, "Digest sent to your notifications.")
    return redirect("notifications:list")
