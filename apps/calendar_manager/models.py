"""Calendar event models with timezone awareness and recurrence."""
from datetime import timedelta

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class CalendarEvent(models.Model):
    class Source(models.TextChoices):
        LOCAL = "local", "NexaMind"
        GOOGLE = "google", "Google Calendar"

    RECURRENCE_CHOICES = [
        ("none", "Does not repeat"),
        ("daily", "Daily"),
        ("weekly", "Weekly"),
        ("monthly", "Monthly"),
    ]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="events"
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=200, blank=True)
    start = models.DateTimeField(db_index=True)
    end = models.DateTimeField(db_index=True)
    all_day = models.BooleanField(default=False)
    timezone = models.CharField(max_length=64, default="UTC")
    recurrence = models.CharField(max_length=10, choices=RECURRENCE_CHOICES, default="none")
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.LOCAL)
    external_id = models.CharField(max_length=191, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start"]
        indexes = [models.Index(fields=["owner", "start"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end__gte=models.F("start")),
                name="event_end_after_start",
            )
        ]

    def clean(self):
        if self.end and self.start and self.end < self.start:
            raise ValidationError({"end": "End time must be after the start time."})

    @property
    def duration_minutes(self):
        return int((self.end - self.start).total_seconds() // 60)

    def occurrences_between(self, start, end):
        """Yield occurrence start/end pairs inside the window (bounded)."""
        if self.recurrence == "none":
            if self.start <= end and self.end >= start:
                yield self.start, self.end
            return
        duration = self.end - self.start
        step = {
            "daily": timedelta(days=1),
            "weekly": timedelta(weeks=1),
            "monthly": relativedelta(months=1),
        }[self.recurrence]
        current = self.start
        guard = 0
        while current <= end and guard < 400:
            if current + duration >= start:
                yield current, current + duration
            current = current + step
            guard += 1

    def __str__(self):
        return f"{self.title} @ {self.start:%Y-%m-%d %H:%M}"


class EventReminder(models.Model):
    event = models.ForeignKey(CalendarEvent, on_delete=models.CASCADE, related_name="reminders")
    minutes_before = models.PositiveIntegerField(default=15)
    sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-minutes_before"]

    def __str__(self):
        return f"Reminder {self.minutes_before}m before {self.event_id}"
