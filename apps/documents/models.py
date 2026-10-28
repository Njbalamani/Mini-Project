"""Document intelligence models."""
import uuid
from pathlib import Path

from django.conf import settings
from django.db import models


def document_upload_path(instance, filename):
    ext = Path(filename).suffix.lower()
    return f"documents/{instance.owner_id}/{uuid.uuid4().hex}{ext}"


class Document(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="documents"
    )
    title = models.CharField(max_length=200)
    file = models.FileField(upload_to=document_upload_path)
    original_name = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    size_bytes = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    extracted_text = models.TextField(blank=True)
    page_count = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["owner", "-created_at"])]

    @property
    def is_ready(self):
        return self.status == self.Status.READY

    @property
    def size_kb(self):
        return round(self.size_bytes / 1024, 1)

    def __str__(self):
        return self.title


class DocumentProcessingJob(models.Model):
    STATUS = [("queued", "Queued"), ("running", "Running"), ("done", "Done"), ("failed", "Failed")]

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="jobs"
    )
    status = models.CharField(max_length=12, choices=STATUS, default="queued")
    detail = models.CharField(max_length=300, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"Job<{self.document_id}:{self.status}>"


class DocumentAnalysis(models.Model):
    KIND = [
        ("summary", "Summary"),
        ("keywords", "Keywords"),
        ("dates", "Important dates"),
        ("action_items", "Action items"),
        ("qa", "Question & answer"),
    ]

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="analyses"
    )
    kind = models.CharField(max_length=16, choices=KIND)
    question = models.CharField(max_length=400, blank=True)
    result = models.TextField(blank=True)
    # Evidence: page numbers / excerpts supporting the result.
    evidence = models.JSONField(default=list, blank=True)
    ai_generated = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.kind}<doc={self.document_id}>"
