"""Read-only audit log views. Audit records cannot be edited via the UI."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render

from .models import AuditLog


@login_required
def audit_list(request):
    qs = AuditLog.objects.filter(actor=request.user).select_related("actor")

    action = request.GET.get("action", "").strip()
    outcome = request.GET.get("outcome", "").strip()
    if action:
        qs = qs.filter(action__icontains=action)
    if outcome in {"success", "failure", "denied"}:
        qs = qs.filter(outcome=outcome)

    paginator = Paginator(qs, 30)
    page = paginator.get_page(request.GET.get("page"))
    actions = (
        AuditLog.objects.filter(actor=request.user)
        .values_list("action", flat=True).distinct().order_by("action")[:50]
    )
    return render(request, "settings/audit.html", {
        "page_obj": page,
        "actions": actions,
        "current_action": action,
        "current_outcome": outcome,
    })
