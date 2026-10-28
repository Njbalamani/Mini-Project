"""Plan management views. Payment processing is not enabled; upgrades run in
an explicit test mode and never collect card details."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit_logs.services import log_event

from .models import Plan, Subscription
from .services import get_plan_for_user, usage_summary


@login_required
def subscription_home(request):
    plan = get_plan_for_user(request.user)
    return render(request, "settings/subscription.html", {
        "plan": plan,
        "plans": Plan.objects.filter(is_active=True),
        "usage": usage_summary(request.user),
        "subscription": Subscription.objects.filter(user=request.user).first(),
    })


@login_required
@require_POST
def switch_plan(request, slug):
    """Test-mode plan switch. A real deployment would route this through the
    payment provider's checkout before activating the subscription."""
    plan = get_object_or_404(Plan, slug=slug, is_active=True)
    Subscription.objects.update_or_create(
        user=request.user,
        defaults={"plan": plan, "status": "active"},
    )
    log_event(actor=request.user, action="subscription.changed",
              resource_type="plan", resource_id=plan.slug, request=request,
              metadata={"test_mode": True})
    messages.success(
        request,
        f"Plan changed to {plan.name} (test mode). No payment was processed.",
    )
    return redirect("subscriptions:home")
