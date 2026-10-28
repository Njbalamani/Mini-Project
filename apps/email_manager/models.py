"""Email assistant models.

By default only minimal message metadata is retained. Storing fuller email
content is opt-in per account. Email is never sent without explicit approval.
"""
from django.conf import settings
from django.db import models


class EmailSettings(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_settings"
    )
    store_message_bodies = models.BooleanField(default=False)
    sending_enabled = models.BooleanField(default=False)
    auto_categorize = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"EmailSettings<{self.user_id}>"


class EmailMessageMeta(models.Model):
    """Read-only metadata for a Gmail message (no body unless opted in)."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_metadata"
    )
    provider_message_id = models.CharField(max_length=191)
    subject = models.CharField(max_length=400, blank=True)
    sender = models.CharField(max_length=320, blank=True)
    received_at = models.CharField(max_length=120, blank=True)
    snippet = models.CharField(max_length=400, blank=True)
    category = models.CharField(max_length=60, blank=True)
    body = models.TextField(blank=True)  # only populated when explicitly enabled
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fetched_at"]
        unique_together = [("owner", "provider_message_id")]
        indexes = [models.Index(fields=["owner", "-fetched_at"])]

    def __str__(self):
        return self.subject or self.provider_message_id


class EmailDraft(models.Model):
    STATUS = [("draft", "Draft"), ("approved", "Approved"), ("sent", "Sent")]

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_drafts"
    )
    in_reply_to = models.CharField(max_length=191, blank=True)
    to = models.CharField(max_length=320, blank=True)
    subject = models.CharField(max_length=400, blank=True)
    body = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Draft<{self.subject}>"


class CategorizationRule(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_rules"
    )
    keyword = models.CharField(max_length=120)
    category = models.CharField(max_length=60)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.keyword} -> {self.category}"
