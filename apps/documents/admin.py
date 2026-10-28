from django.contrib import admin

from .models import Document, DocumentAnalysis, DocumentProcessingJob


class AnalysisInline(admin.TabularInline):
    model = DocumentAnalysis
    extra = 0
    readonly_fields = ("kind", "question", "result", "ai_generated", "created_at")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "status", "page_count", "size_kb", "created_at")
    list_filter = ("status",)
    search_fields = ("title", "extracted_text")
    inlines = [AnalysisInline]


@admin.register(DocumentProcessingJob)
class DocumentProcessingJobAdmin(admin.ModelAdmin):
    list_display = ("document", "status", "started_at", "finished_at")
    list_filter = ("status",)
