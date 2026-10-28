from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "type", "level", "title", "is_read", "created_at")
    list_filter = ("type", "level", "is_read")
    search_fields = ("title", "message")
