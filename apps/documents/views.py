"""Document intelligence views."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit_logs.services import log_event
from apps.subscriptions.services import check_limit, increment_usage

from .forms import DocumentUploadForm, QuestionForm
from .models import Document, DocumentAnalysis
from .services import (
    analyze_with_ai,
    extract_action_items,
    extract_dates,
    extract_keywords,
    process_document,
)


@login_required
def document_list(request):
    qs = Document.objects.filter(owner=request.user)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(extracted_text__icontains=q))
    paginator = Paginator(qs, 20)
    return render(request, "documents/list.html", {
        "page_obj": paginator.get_page(request.GET.get("page")), "q": q,
    })


@login_required
def document_upload(request):
    form = DocumentUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        allowed, reason = check_limit(request.user, "documents")
        if not allowed:
            messages.error(request, reason)
            return redirect("subscriptions:home")
        document = form.save(commit=False)
        document.owner = request.user
        document.original_name = form.cleaned_data["file"].name[:255]
        document.size_bytes = form.cleaned_data["file"].size
        document.content_type = getattr(form.cleaned_data["file"], "content_type", "")[:100]
        document.save()
        increment_usage(request.user, "documents")
        log_event(actor=request.user, action="document.uploaded", resource_type="document",
                  resource_id=document.pk, request=request)
        # Process inline; a worker would normally pick this up.
        process_document(document)
        messages.success(request, "Document uploaded and processed.")
        return redirect("documents:detail", pk=document.pk)
    return render(request, "documents/upload.html", {
        "form": form, "max_mb": settings.NEXAMIND.get("MAX_DOCUMENT_UPLOAD_MB", 10),
    })


@login_required
def document_detail(request, pk):
    document = get_object_or_404(Document, pk=pk, owner=request.user)
    analyses = document.analyses.all()[:20]
    return render(request, "documents/detail.html", {
        "document": document,
        "analyses": analyses,
        "question_form": QuestionForm(),
        "keywords": extract_keywords(document.extracted_text) if document.is_ready else [],
        "dates": extract_dates(document.extracted_text) if document.is_ready else [],
        "action_items": extract_action_items(document.extracted_text) if document.is_ready else [],
    })


@login_required
@require_POST
def document_reprocess(request, pk):
    document = get_object_or_404(Document, pk=pk, owner=request.user)
    process_document(document)
    messages.success(request, "Document reprocessed.")
    return redirect("documents:detail", pk=pk)


@login_required
@require_POST
def document_analyze(request, pk):
    document = get_object_or_404(Document, pk=pk, owner=request.user)
    kind = request.POST.get("kind", "summary")
    if not document.is_ready:
        messages.warning(request, "Wait for processing to finish first.")
        return redirect("documents:detail", pk=pk)
    analysis, error = analyze_with_ai(request.user, document, kind)
    if analysis is None:
        messages.warning(request, f"AI unavailable: {error}")
    else:
        messages.success(request, "Analysis complete.")
    return redirect("documents:detail", pk=pk)


@login_required
@require_POST
def document_ask(request, pk):
    document = get_object_or_404(Document, pk=pk, owner=request.user)
    form = QuestionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Enter a question first.")
        return redirect("documents:detail", pk=pk)
    if not document.is_ready:
        messages.warning(request, "Wait for processing to finish first.")
        return redirect("documents:detail", pk=pk)
    analysis, error = analyze_with_ai(
        request.user, document, "qa", question=form.cleaned_data["question"]
    )
    if analysis is None:
        messages.warning(request, f"AI unavailable: {error}")
    else:
        messages.success(request, "Answer generated.")
    return redirect("documents:detail", pk=pk)


@login_required
def document_delete(request, pk):
    document = get_object_or_404(Document, pk=pk, owner=request.user)
    if request.method == "POST":
        log_event(actor=request.user, action="document.deleted", resource_type="document",
                  resource_id=document.pk, request=request)
        document.file.delete(save=False)
        document.delete()
        messages.success(request, "Document deleted.")
        return redirect("documents:list")
    return render(request, "documents/confirm_delete.html", {"document": document})


@login_required
def analysis_delete(request, pk):
    analysis = get_object_or_404(DocumentAnalysis, pk=pk, document__owner=request.user)
    document_pk = analysis.document_id
    if request.method == "POST":
        analysis.delete()
        messages.success(request, "Analysis removed.")
        return redirect("documents:detail", pk=document_pk)
    return redirect("documents:detail", pk=document_pk)
