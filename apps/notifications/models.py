"""In-app notification model."""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    TYPE_CHOICES = [
        ("task_reminder", "Task reminder"),
        ("task_overdue", "Overdue task"),
        ("event_upcoming", "Upcoming event"),
        ("workflow_failed", "Workflow failure"),
        ("workflow_completed", "Workflow completion"),
        ("integration_error", "Integration connection failure"),
        ("ai_completed", "AI processing completion"),
        ("security", "Account security event"),
        ("system", "System"),
    ]
    LEVEL_CHOICES = [
        ("info", "Info"),
        ("success", "Success"),
        ("warning", "Warning"),
        ("danger", "Danger"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    type = models.CharField(max_length=32, choices=TYPE_CHOICES, default="system")
    level = models.CharField(max_length=16, choices=LEVEL_CHOICES, default="info")
    title = models.CharField(max_length=200)
    message = models.TextField(blank=True)
    url = models.CharField(max_length=300, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    # Deduplication key prevents duplicate notifications from retried jobs.
    dedupe_key = models.CharField(max_length=120, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read", "-created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "dedupe_key"],
                condition=models.Q(dedupe_key__gt=""),
                name="unique_notification_dedupe_per_user",
            )
        ]

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])

    def __str__(self):
        return f"[{self.type}] {self.title}"
