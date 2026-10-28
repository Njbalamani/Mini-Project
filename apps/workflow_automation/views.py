"""Workflow builder and execution history views."""
import json
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.audit_logs.services import log_event
from apps.subscriptions.services import check_limit, increment_usage

from .engine import WorkflowError, preview_workflow, run_workflow
from .forms import WorkflowForm
from .models import (
    TriggerType,
    Workflow,
    WorkflowAction,
    WorkflowCondition,
    WorkflowExecution,
    WorkflowTrigger,
)


def _webhook_url(request, workflow):
    if not workflow.webhook_token:
        return ""
    return request.build_absolute_uri(
        reverse("workflow_automation:webhook", args=[workflow.webhook_token])
    )


@login_required
def workflow_list(request):
    qs = Workflow.objects.filter(owner=request.user).annotate(
        execution_count=Count("executions"),
        failure_count=Count("executions", filter=Q(executions__status__in=["failed", "timeout"])),
    )
    stats = WorkflowExecution.objects.filter(workflow__owner=request.user).aggregate(
        total=Count("id"),
        succeeded=Count("id", filter=Q(status="succeeded")),
        failed=Count("id", filter=Q(status__in=["failed", "timeout"])),
    )
    return render(request, "workflows/list.html", {"workflows": qs, "stats": stats})


@login_required
def workflow_detail(request, pk):
    workflow = get_object_or_404(Workflow, pk=pk, owner=request.user)
    executions = workflow.executions.all()[:20]
    trigger = workflow.triggers.first()
    is_webhook = bool(trigger and trigger.trigger_type == TriggerType.WEBHOOK)
    webhook_url = ""
    if is_webhook:
        token = workflow.ensure_webhook_token()
        webhook_url = request.build_absolute_uri(
            reverse("workflow_automation:webhook", args=[token])
        )
    return render(request, "workflows/detail.html", {
        "workflow": workflow, "executions": executions,
        "preview": preview_workflow(workflow),
        "is_webhook_trigger": is_webhook, "webhook_url": webhook_url,
    })


def _save_config(workflow, values):
    WorkflowTrigger.objects.filter(workflow=workflow).delete()
    WorkflowCondition.objects.filter(workflow=workflow).delete()
    WorkflowAction.objects.filter(workflow=workflow).delete()
    WorkflowTrigger.objects.create(
        workflow=workflow, trigger_type=values["trigger_type"],
        schedule_time=values.get("schedule_time", ""),
    )
    WorkflowCondition.objects.create(
        workflow=workflow, condition_type=values["condition_type"]
    )
    action_config = {
        key: value for key, value in (values.get("action_config") or {}).items() if value
    }
    WorkflowAction.objects.create(
        workflow=workflow, action_type=values["action_type"], order=1, config=action_config
    )


@login_required
def workflow_create(request):
    form = WorkflowForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        allowed, reason = check_limit(request.user, "workflows")
        if not allowed:
            messages.error(request, reason)
            return redirect("subscriptions:home")
        with transaction.atomic():
            workflow = form.save(commit=False)
            workflow.owner = request.user
            workflow.save()
            _save_config(workflow, form.config_values)
        increment_usage(request.user, "workflows")
        log_event(actor=request.user, action="workflow.created", resource_type="workflow",
                  resource_id=workflow.pk, request=request)
        messages.success(request, "Workflow created.")
        return redirect("workflow_automation:detail", pk=workflow.pk)
    return render(request, "workflows/form.html", {"form": form, "mode": "create"})


@login_required
def workflow_edit(request, pk):
    workflow = get_object_or_404(Workflow, pk=pk, owner=request.user)
    form = WorkflowForm(request.POST or None, instance=workflow)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            form.save()
            _save_config(workflow, form.config_values)
        log_event(actor=request.user, action="workflow.updated", resource_type="workflow",
                  resource_id=workflow.pk, request=request)
        messages.success(request, "Workflow updated.")
        return redirect("workflow_automation:detail", pk=workflow.pk)
    return render(request, "workflows/form.html", {"form": form, "mode": "edit", "workflow": workflow})


@login_required
@require_POST
def workflow_toggle(request, pk):
    workflow = get_object_or_404(Workflow, pk=pk, owner=request.user)
    workflow.is_enabled = not workflow.is_enabled
    workflow.save(update_fields=["is_enabled"])
    messages.success(request, f"Workflow {'enabled' if workflow.is_enabled else 'disabled'}.")
    return redirect("workflow_automation:detail", pk=workflow.pk)


@login_required
@require_POST
def workflow_run(request, pk):
    workflow = get_object_or_404(Workflow, pk=pk, owner=request.user)
    if not workflow.is_enabled:
        messages.warning(request, "Enable the workflow before running it.")
        return redirect("workflow_automation:detail", pk=workflow.pk)
    try:
        execution = run_workflow(
            workflow, trigger_reason="manual",
            idempotency_key=f"manual-{workflow.pk}-{request.POST.get('nonce','')}",
        )
    except WorkflowError as exc:
        messages.error(request, str(exc))
        return redirect("workflow_automation:detail", pk=workflow.pk)
    if execution.status == "succeeded":
        messages.success(request, f"Workflow ran successfully ({execution.duration_seconds}s).")
    else:
        messages.error(request, f"Workflow {execution.status}: {execution.error}")
    return redirect("workflow_automation:execution", pk=execution.pk)


@login_required
def workflow_preview(request, pk):
    workflow = get_object_or_404(Workflow, pk=pk, owner=request.user)
    return render(request, "workflows/preview.html", {
        "workflow": workflow, "preview": preview_workflow(workflow),
    })


@login_required
@require_POST
def webhook_regenerate(request, pk):
    workflow = get_object_or_404(Workflow, pk=pk, owner=request.user)
    workflow.reset_webhook_token()
    log_event(actor=request.user, action="workflow.webhook_rotated",
              resource_type="workflow", resource_id=workflow.pk, request=request)
    messages.success(
        request, "Webhook URL regenerated — update any integrations using the old URL."
    )
    return redirect("workflow_automation:detail", pk=workflow.pk)


@csrf_exempt
@require_POST
def webhook_receive(request, token):
    """Public endpoint that triggers a workflow addressed by its secret token."""
    workflow = Workflow.objects.filter(webhook_token=token).first()
    if not token or workflow is None:
        return JsonResponse({"ok": False, "error": "Unknown webhook."}, status=404)
    if not workflow.is_enabled:
        return JsonResponse({"ok": False, "error": "Workflow is disabled."}, status=409)

    payload = {}
    if request.body:
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            payload = {key: value for key, value in request.POST.items()}
    if not isinstance(payload, dict):
        payload = {"data": payload}

    idempotency = (
        request.headers.get("X-NexaMind-Idempotency")
        or payload.get("idempotency_key") or ""
    ).strip()
    if not idempotency:
        idempotency = f"webhook-{workflow.pk}-{uuid.uuid4().hex}"

    context = {
        "payload": payload,
        "notification_title": payload.get("title") or payload.get("notification_title") or "",
        "notification_message": payload.get("message") or payload.get("notification_message") or "",
        "task_title": payload.get("task_title") or "",
        "dedupe_key": f"webhook-{workflow.pk}-{idempotency}",
    }
    try:
        execution = run_workflow(
            workflow, trigger_reason="webhook", context=context,
            idempotency_key=idempotency,
        )
    except WorkflowError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    log_event(
        actor=workflow.owner, action="workflow.webhook_received",
        resource_type="workflow", resource_id=workflow.pk,
        metadata={"execution": execution.pk, "status": execution.status},
    )
    return JsonResponse({
        "ok": execution.status == "succeeded",
        "execution": execution.pk,
        "status": execution.status,
    })


@login_required
def workflow_delete(request, pk):
    workflow = get_object_or_404(Workflow, pk=pk, owner=request.user)
    if request.method == "POST":
        log_event(actor=request.user, action="workflow.deleted", resource_type="workflow",
                  resource_id=workflow.pk, request=request)
        workflow.delete()
        messages.success(request, "Workflow deleted.")
        return redirect("workflow_automation:list")
    return render(request, "workflows/confirm_delete.html", {"workflow": workflow})


@login_required
def execution_list(request):
    qs = WorkflowExecution.objects.filter(workflow__owner=request.user).select_related("workflow")
    status = request.GET.get("status", "").strip()
    if status:
        qs = qs.filter(status=status)
    paginator = Paginator(qs, 25)
    return render(request, "workflows/executions.html", {
        "page_obj": paginator.get_page(request.GET.get("page")),
        "current_status": status,
        "statuses": WorkflowExecution.STATUS,
    })


@login_required
def execution_detail(request, pk):
    execution = get_object_or_404(
        WorkflowExecution, pk=pk, workflow__owner=request.user
    )
    return render(request, "workflows/execution_detail.html", {"execution": execution})
