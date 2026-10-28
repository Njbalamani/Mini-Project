from .models import Notification


def notifications(request):
    if not request.user.is_authenticated:
        return {"unread_notifications": 0, "recent_notifications": []}
    qs = Notification.objects.filter(user=request.user)
    return {
        "unread_notifications": qs.filter(is_read=False).count(),
        "recent_notifications": list(qs[:6]),
    }
