"""Plans, subscriptions and server-side usage accounting."""
from django.conf import settings
from django.db import models
from django.utils import timezone

# Metric keys used by the limit service.
METRICS = ["ai_messages", "tasks", "workflows", "documents"]

# Fallback limits used when no Plan rows exist (keeps limits configurable but
# functional out of the box). -1 means unlimited.
DEFAULT_FREE_LIMITS = {"ai_messages": 30, "tasks": 50, "workflows": 2, "documents": 3}
DEFAULT_PREMIUM_LIMITS = {"ai_messages": 2000, "tasks": -1, "workflows": 50, "documents": 100}


class Plan(models.Model):
    slug = models.SlugField(unique=True)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=240, blank=True)
    price_cents = models.PositiveIntegerField(default=0)
    is_premium = models.BooleanField(default=False)
    limits = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["price_cents"]

    def limit_for(self, metric):
        return self.limits.get(metric, DEFAULT_FREE_LIMITS.get(metric, 0))

    @property
    def price_display(self):
        if not self.price_cents:
            return "Free"
        return f"${self.price_cents / 100:.2f}"

    def __str__(self):
        return self.name


class Subscription(models.Model):
    STATUS = [("active", "Active"), ("canceled", "Canceled"), ("past_due", "Past due")]
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscription"
    )
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    status = models.CharField(max_length=16, choices=STATUS, default="active")
    started_at = models.DateTimeField(default=timezone.now)
    current_period_end = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def is_active(self):
        return self.status == "active"

    def __str__(self):
        return f"{self.user_id} -> {self.plan.slug}"


class UsageRecord(models.Model):
    """Rolling usage counter per user, per metric, per period (YYYY-MM)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="usage_records"
    )
    metric = models.CharField(max_length=32, db_index=True)
    period = models.CharField(max_length=7, db_index=True)  # e.g. 2026-10
    count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "metric", "period")]
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.user_id}:{self.metric}={self.count}@{self.period}"
