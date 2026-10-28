from django.contrib import admin

from .models import Integration, OAuthCredential, ProviderConfig, WhatsAppMessage


class OAuthCredentialInline(admin.StackedInline):
    model = OAuthCredential
    extra = 0
    readonly_fields = ("created_at", "updated_at")
    exclude = ("access_token_encrypted", "refresh_token_encrypted")
    can_delete = False


@admin.register(Integration)
class IntegrationAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "status", "external_account", "last_synced_at")
    list_filter = ("provider", "status")
    search_fields = ("external_account",)
    inlines = [OAuthCredentialInline]


@admin.register(ProviderConfig)
class ProviderConfigAdmin(admin.ModelAdmin):
    list_display = ("provider", "updated_by", "updated_at")
    readonly_fields = ("secrets",)


@admin.register(WhatsAppMessage)
class WhatsAppMessageAdmin(admin.ModelAdmin):
    list_display = ("user", "direction", "wa_id", "contact_name", "created_at")
    list_filter = ("direction",)
    search_fields = ("wa_id", "contact_name", "body")
