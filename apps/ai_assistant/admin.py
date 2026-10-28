from django.contrib import admin

from .models import (
    AIProviderConfiguration,
    AIUsageRecord,
    AssistantFeedback,
    Conversation,
    Message,
)


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ("role", "content", "token_count", "created_at")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "updated_at", "is_archived")
    list_filter = ("is_archived",)
    search_fields = ("title",)
    inlines = [MessageInline]


@admin.register(AIProviderConfiguration)
class AIConfigAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "model", "updated_at")


@admin.register(AIUsageRecord)
class AIUsageAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "model", "total_tokens", "success", "created_at")
    list_filter = ("provider", "success")


admin.site.register(Message)
admin.site.register(AssistantFeedback)
