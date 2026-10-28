"""Background document processing."""
import logging

from celery import shared_task

from apps.notifications.services import notify

from .models import Document
from .services import process_document

logger = logging.getLogger("nexamind.documents")


@shared_task(bind=True, max_retries=2, ignore_result=True)
def process_document_task(self, document_id):
    document = Document.objects.filter(pk=document_id).first()
    if document is None:
        return None
    try:
        process_document(document)
    except Exception as exc:  # pragma: no cover
        logger.exception("Document processing failed")
        raise self.retry(exc=exc, countdown=20)
    notify(
        document.owner, type="ai_completed", level="success",
        title=f"Document ready: {document.title}",
        message=f"Processed {document.page_count} page(s).",
        url=f"/documents/{document.pk}/",
        dedupe_key=f"doc-ready-{document.pk}",
    )
    return document.pk
