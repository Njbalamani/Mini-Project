"""Integration connection and encrypted OAuth credential models."""
from django.conf import settings
from django.db import models


class Integration(models.Model):
    class Provider(models.TextChoices):
        GMAIL = "gmail", "Gmail"
        GOOGLE_CALENDAR = "google_calendar", "Google Calendar"
        GITHUB = "github", "GitHub"
        WHATSAPP = "whatsapp", "WhatsApp"
        LINKEDIN = "linkedin", "LinkedIn"
        FACEBOOK = "facebook", "Facebook"

    class Status(models.TextChoices):
        CONNECTED = "connected", "Connected"
        DISCONNECTED = "disconnected", "Disconnected"
        ERROR = "error", "Error"
        PENDING = "pending", "Pending authorization"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="integrations"
    )
    provider = models.CharField(max_length=24, choices=Provider.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DISCONNECTED)
    external_account = models.CharField(max_length=191, blank=True)
    scopes = models.JSONField(default=list, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "provider")]
        ordering = ["provider"]

    @property
    def label(self):
        return self.get_provider_display()

    def __str__(self):
        return f"{self.user_id}:{self.provider}:{self.status}"


class OAuthCredential(models.Model):
    """Encrypted OAuth tokens. Raw tokens are never exposed to the browser.

    The ciphertext is produced with Fernet (AES-128-CBC + HMAC). The key lives
    outside the database (environment/secret manager).
    """
    integration = models.OneToOneField(
        Integration, on_delete=models.CASCADE, related_name="credential"
    )
    access_token_encrypted = models.TextField(blank=True)
    refresh_token_encrypted = models.TextField(blank=True)
    token_type = models.CharField(max_length=40, blank=True, default="Bearer")
    expires_at = models.DateTimeField(null=True, blank=True)
    scope = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Credential<{self.integration_id}>"


class WhatsAppMessage(models.Model):
    """A sent or received WhatsApp message, scoped to its owner."""

    class Direction(models.TextChoices):
        INBOUND = "inbound", "Inbound"
        OUTBOUND = "outbound", "Outbound"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="whatsapp_messages"
    )
    integration = models.ForeignKey(
        Integration, on_delete=models.CASCADE, related_name="whatsapp_messages",
        null=True, blank=True,
    )
    direction = models.CharField(max_length=8, choices=Direction.choices)
    wa_id = models.CharField(max_length=32, blank=True)
    contact_name = models.CharField(max_length=120, blank=True)
    body = models.TextField(blank=True)
    message_type = models.CharField(max_length=24, default="text")
    raw = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "-created_at"])]

    def __str__(self):
        return f"{self.direction}:{self.wa_id}:{self.body[:30]}"


class ProviderConfig(models.Model):
    """Admin-entered provider credentials, stored encrypted at rest.

    Non-secret values (client ids, phone number ids, display numbers) live in
    `data`; secrets (client secrets, API tokens, app secrets) are Fernet-encrypted
    in ``secrets``. Values entered here override the environment defaults so an
    administrator can connect providers without editing server files.
    """

    provider = models.CharField(max_length=24, unique=True)
    data = models.JSONField(default=dict, blank=True)
    secrets = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="provider_configs_updated",
    )

    class Meta:
        ordering = ["provider"]

    def __str__(self):
        return f"ProviderConfig<{self.provider}>"
