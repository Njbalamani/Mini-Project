"""Email assistant views. Sending remains gated behind explicit settings."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit_logs.services import log_event
from apps.integrations.models import Integration
from apps.integrations.services import get_valid_access_token
from apps.integrations.providers import IntegrationError, fetch_gmail_metadata

from .forms import CategorizationRuleForm, DraftForm, EmailSettingsForm
from .models import CategorizationRule, EmailDraft, EmailMessageMeta
from .services import ai_draft_reply, ai_summarize, categorize_email, get_settings, store_metadata


@login_required
def email_home(request):
    integration = Integration.objects.filter(user=request.user, provider="gmail").first()
    messages_meta = EmailMessageMeta.objects.filter(owner=request.user)[:25]
    return render(request, "email/home.html", {
        "integration": integration,
        "settings": get_settings(request.user),
        "messages_meta": messages_meta,
        "drafts": EmailDraft.objects.filter(owner=request.user)[:10],
        "rules": CategorizationRule.objects.filter(owner=request.user),
    })


@login_required
@require_POST
def fetch_metadata(request):
    integration = Integration.objects.filter(
        user=request.user, provider="gmail", status=Integration.Status.CONNECTED
    ).first()
    if integration is None:
        messages.warning(request, "Connect Gmail first before fetching messages.")
        return redirect("email_manager:home")
    try:
        token = get_valid_access_token(integration)
        items = fetch_gmail_metadata(token, max_results=15)
    except IntegrationError as exc:
        messages.error(request, str(exc))
        return redirect("email_manager:home")
    count = store_metadata(request.user, items)
    if get_settings(request.user).auto_categorize:
        for meta in EmailMessageMeta.objects.filter(owner=request.user)[:count]:
            categorize_email(meta, request.user)
    log_event(actor=request.user, action="email.metadata_fetched", request=request,
              metadata={"count": count})
    messages.success(request, f"Fetched metadata for {count} messages (read-only).")
    return redirect("email_manager:home")


@login_required
def message_detail(request, pk):
    meta = get_object_or_404(EmailMessageMeta, pk=pk, owner=request.user)
    return render(request, "email/detail.html", {"meta": meta})


@login_required
@require_POST
def summarize(request, pk):
    meta = get_object_or_404(EmailMessageMeta, pk=pk, owner=request.user)
    content = meta.body or meta.snippet or "(no body stored; using snippet only)"
    ok, text = ai_summarize(request.user, meta.subject, content)
    if not ok:
        messages.warning(request, f"AI unavailable: {text}")
    else:
        request.session["email_summary"] = text
        messages.success(request, "Summary generated.")
    return redirect("email_manager:detail", pk=pk)


@login_required
@require_POST
def draft_reply(request, pk):
    meta = get_object_or_404(EmailMessageMeta, pk=pk, owner=request.user)
    content = meta.body or meta.snippet or "(no body stored)"
    ok, error, draft_id = ai_draft_reply(request.user, meta.subject, content)
    if not ok:
        messages.warning(request, f"AI unavailable: {error}")
        return redirect("email_manager:detail", pk=pk)
    messages.success(request, "Draft created. Review and approve before sending.")
    return redirect("email_manager:draft", pk=draft_id)


@login_required
def draft_detail(request, pk):
    draft = get_object_or_404(EmailDraft, pk=pk, owner=request.user)
    form = DraftForm(instance=draft)
    return render(request, "email/draft.html", {
        "draft": draft, "form": form, "settings": get_settings(request.user),
    })


@login_required
@require_POST
def approve_send(request, pk):
    draft = get_object_or_404(EmailDraft, pk=pk, owner=request.user)
    approved = request.POST.get("approve") == "1"
    from .services import send_draft
    ok, message = send_draft(request.user, draft.pk, approved)
    if ok:
        draft.status = "sent"
        draft.save(update_fields=["status"])
        messages.success(request, message)
    else:
        messages.warning(request, message)
    log_event(actor=request.user, action="email.send_attempted", resource_type="draft",
              resource_id=draft.pk, request=request,
              outcome="success" if ok else "denied")
    return redirect("email_manager:draft", pk=pk)


@login_required
def email_settings(request):
    obj = get_settings(request.user)
    form = EmailSettingsForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Email settings updated.")
        return redirect("email_manager:settings")
    return render(request, "email/settings.html", {"form": form})


@login_required
@require_POST
def add_rule(request):
    form = CategorizationRuleForm(request.POST)
    if form.is_valid():
        rule = form.save(commit=False)
        rule.owner = request.user
        rule.save()
        messages.success(request, "Rule added.")
    else:
        messages.error(request, "Invalid rule.")
    return redirect("email_manager:home")
