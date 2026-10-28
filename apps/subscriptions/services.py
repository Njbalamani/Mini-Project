"""Server-side usage limit enforcement.

Limits are evaluated on the server for every relevant operation so they cannot
be bypassed by calling the API directly or by tampering with the frontend.
"""
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import (
    DEFAULT_FREE_LIMITS,
    DEFAULT_PREMIUM_LIMITS,
    Plan,
    Subscription,
    UsageRecord,
)


def current_period():
    return timezone.now().strftime("%Y-%m")


def get_plan_for_user(user):
    sub = Subscription.objects.filter(user=user, status="active").select_related("plan").first()
    if sub:
        return sub.plan
    return (
        Plan.objects.filter(slug="free", is_active=True).first()
        or Plan.objects.filter(is_premium=False, is_active=True).first()
    )


def limits_for_user(user):
    plan = get_plan_for_user(user)
    if plan:
        return {m: plan.limit_for(m) for m in DEFAULT_FREE_LIMITS}
    return dict(DEFAULT_FREE_LIMITS)


def current_usage(user, metric, period=None):
    period = period or current_period()
    record = UsageRecord.objects.filter(user=user, metric=metric, period=period).first()
    return record.count if record else 0


def check_limit(user, metric, amount=1, period=None):
    """Return (allowed, reason). Unlimited metrics (-1) always pass."""
    limits = limits_for_user(user)
    limit = limits.get(metric)
    if limit is None or limit < 0:
        return True, ""
    used = current_usage(user, metric, period)
    if used + amount > limit:
        return False, (
            f"You have reached your plan limit for {metric.replace('_', ' ')} "
            f"({used}/{limit}). Upgrade your plan to continue."
        )
    return True, ""


@transaction.atomic
def increment_usage(user, metric, amount=1, period=None):
    period = period or current_period()
    record, created = UsageRecord.objects.select_for_update().get_or_create(
        user=user, metric=metric, period=period, defaults={"count": 0}
    )
    if not created:
        record.count = F("count") + amount
        record.save(update_fields=["count"])
        record.refresh_from_db()
    else:
        UsageRecord.objects.filter(pk=record.pk).update(count=amount)
        record.refresh_from_db()
    return record.count


def usage_summary(user):
    limits = limits_for_user(user)
    summary = []
    for metric, limit in limits.items():
        used = current_usage(user, metric)
        pct = 0 if limit < 0 else min(100, int(used / limit * 100)) if limit else 100
        summary.append({
            "metric": metric,
            "label": metric.replace("_", " ").title(),
            "used": used,
            "limit": limit,
            "unlimited": limit < 0,
            "percent": pct,
        })
    return summary
