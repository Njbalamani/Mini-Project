"""Task models with validated status transitions and deadlines."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class TaskQuerySet(models.QuerySet):
    def for_user(self, user):
        return self.filter(owner=user)

    def open_tasks(self):
        return self.exclude(status=Task.Status.DONE)

    def overdue(self):
        return self.open_tasks().filter(due_date__lt=timezone.now())


class Task(models.Model):
    class Status(models.TextChoices):
        TODO = "todo", "To do"
        IN_PROGRESS = "in_progress", "In progress"
        BLOCKED = "blocked", "Blocked"
        DONE = "done", "Done"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Recurrence(models.TextChoices):
        NONE = "none", "Does not repeat"
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tasks"
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.TODO, db_index=True)
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM, db_index=True)
    category = models.CharField(max_length=80, blank=True, db_index=True)
    due_date = models.DateTimeField(null=True, blank=True, db_index=True)
    tags = models.ManyToManyField("Tag", blank=True, related_name="tasks")
    recurrence = models.CharField(max_length=10, choices=Recurrence.choices, default=Recurrence.NONE)
    recurrence_until = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TaskQuerySet.as_manager()

    class Meta:
        ordering = ["status", "-priority", "due_date", "-created_at"]
        indexes = [
            models.Index(fields=["owner", "status"]),
            models.Index(fields=["owner", "due_date"]),
        ]

    VALID_TRANSITIONS = {
        Status.TODO: {Status.IN_PROGRESS, Status.BLOCKED, Status.DONE},
        Status.IN_PROGRESS: {Status.BLOCKED, Status.DONE, Status.TODO},
        Status.BLOCKED: {Status.IN_PROGRESS, Status.TODO, Status.DONE},
        Status.DONE: {Status.TODO, Status.IN_PROGRESS},
    }

    def clean(self):
        if self.due_date and self.due_date < timezone.now() - timezone.timedelta(days=3650):
            raise ValidationError({"due_date": "Due date is unreasonably far in the past."})

    @property
    def is_overdue(self):
        return (
            self.due_date is not None
            and self.status != self.Status.DONE
            and self.due_date < timezone.now()
        )

    @property
    def is_complete(self):
        return self.status == self.Status.DONE

    def can_transition_to(self, new_status):
        if new_status == self.status:
            return True
        return new_status in self.VALID_TRANSITIONS.get(self.status, set())

    def __str__(self):
        return self.title


TAG_PALETTE = [
    "#d4af37", "#c084fc", "#60a5fa", "#34d399",
    "#f87171", "#fbbf24", "#22d3ee", "#a3e635",
]


class Tag(models.Model):
    """A user-owned label that can be applied to many tasks."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tags"
    )
    name = models.CharField(max_length=40)
    color = models.CharField(max_length=7, default=TAG_PALETTE[0])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "name"], name="unique_tag_name_per_user"
            )
        ]

    def __str__(self):
        return self.name


class TaskActivity(models.Model):
    ACTION_CHOICES = [
        ("created", "Created"),
        ("updated", "Updated"),
        ("status_changed", "Status changed"),
        ("completed", "Completed"),
        ("reopened", "Reopened"),
        ("commented", "Commented"),
        ("deleted", "Deleted"),
    ]

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="activity")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="task_activity"
    )
    action = models.CharField(max_length=32, choices=ACTION_CHOICES)
    detail = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Task activity"

    def __str__(self):
        return f"{self.task_id}:{self.action}"


class TaskComment(models.Model):
    """A threaded discussion note attached to a task."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="task_comments"
    )
    body = models.TextField(max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment<{self.author_id}@{self.task_id}>"


class SavedTaskFilter(models.Model):
    """A named, reusable set of task-list filters for a user."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_task_filters"
    )
    name = models.CharField(max_length=80)
    query = models.JSONField(default=dict, blank=True)
    pinned = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["owner", "name"], name="unique_saved_filter_name_per_user"
            )
        ]

    @property
    def query_string(self):
        """URL-encoded representation of the stored filters."""
        from urllib.parse import urlencode

        return urlencode({k: v for k, v in (self.query or {}).items() if v})

    def __str__(self):
        return f"{self.name} <{self.owner_id}>"
