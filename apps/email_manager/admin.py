from django.contrib import admin

from .models import CategorizationRule, EmailDraft, EmailMessageMeta, EmailSettings


@admin.register(EmailMessageMeta)
class EmailMessageMetaAdmin(admin.ModelAdmin):
    list_display = ("owner", "subject", "sender", "category", "fetched_at")
    search_fields = ("subject", "sender")
    list_filter = ("category",)


@admin.register(EmailDraft)
class EmailDraftAdmin(admin.ModelAdmin):
    list_display = ("owner", "subject", "status", "updated_at")


admin.site.register(EmailSettings)
admin.site.register(CategorizationRule)
