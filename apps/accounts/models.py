"""Account and identity models.

A custom user model is used from the outset so that additional fields and
behaviour (email login, verification state, preferences) can be added safely.
"""
import secrets
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from .managers import UserManager


def _default_verification_expiry():
    return timezone.now() + timezone.timedelta(hours=48)


class User(AbstractUser):
    """Email-based user account."""

    username = None
    email = models.EmailField("email address", unique=True, db_index=True)
    full_name = models.CharField(max_length=160, blank=True)
    is_email_verified = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        ordering = ["-date_joined"]
        indexes = [models.Index(fields=["email"])]

    def __str__(self):
        return self.email

    @property
    def display_name(self):
        return self.full_name or self.email.split("@")[0]

    @property
    def initials(self):
        source = self.full_name or self.email
        parts = [p for p in source.replace("@", " ").split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[-1][0]).upper()


class UserProfile(models.Model):
    """Extended profile information kept separate from the auth table."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    avatar = models.ImageField(upload_to="avatars/%Y/%m/", blank=True, null=True)
    bio = models.TextField(max_length=500, blank=True)
    job_title = models.CharField(max_length=120, blank=True)
    company = models.CharField(max_length=120, blank=True)
    timezone = models.CharField(max_length=64, default="UTC")
    language = models.CharField(max_length=16, default="en-us")
    theme = models.CharField(
        max_length=16,
        choices=[("royal", "Royal"), ("midnight", "Midnight"), ("light", "Light")],
        default="royal",
    )
    # Two-factor authentication (TOTP). The secret is encrypted at rest using
    # the same Fernet key as OAuth tokens (see apps.integrations.crypto).
    totp_secret = models.TextField(blank=True)
    totp_enabled = models.BooleanField(default=False)
    totp_backup_codes = models.TextField(blank=True)  # JSON list of hashed codes
    totp_confirmed_at = models.DateTimeField(null=True, blank=True)
    # Secret token used to build a private, read-only calendar feed URL.
    calendar_feed_token = models.CharField(
        max_length=64, unique=True, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile<{self.user.email}>"


class UserPreference(models.Model):
    """Notification and product preferences."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="preferences"
    )
    email_notifications = models.BooleanField(default=True)
    in_app_notifications = models.BooleanField(default=True)
    task_reminders = models.BooleanField(default=True)
    workflow_notifications = models.BooleanField(default=True)
    integration_alerts = models.BooleanField(default=True)
    weekly_digest = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Preferences<{self.user.email}>"


class EmailVerification(models.Model):
    """One-time email verification token."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="verifications"
    )
    token = models.CharField(max_length=64, unique=True, default=secrets.token_urlsafe)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_default_verification_expiry)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def is_valid(self):
        return self.verified_at is None and timezone.now() < self.expires_at

    def __str__(self):
        return f"Verification<{self.user.email}>"


class LoginActivity(models.Model):
    """Recorded login attempts for the user activity history."""

    RESULT_CHOICES = [("success", "Success"), ("failed", "Failed")]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="login_activity", null=True, blank=True,
    )
    email_attempted = models.EmailField(blank=True)
    result = models.CharField(max_length=10, choices=RESULT_CHOICES)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "Login activity"

    def __str__(self):
        return f"{self.email_attempted or self.user} {self.result}"


class OAuthIdentity(models.Model):
    """Links a user to an external OAuth provider (e.g. Google sign-in)."""

    PROVIDERS = [("google", "Google"), ("github", "GitHub")]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="oauth_identities"
    )
    provider = models.CharField(max_length=24, choices=PROVIDERS)
    provider_user_id = models.CharField(max_length=191)
    email = models.EmailField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("provider", "provider_user_id")]

    def __str__(self):
        return f"{self.provider}:{self.provider_user_id}"


def avatar_upload_path(instance, filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
    return f"avatars/{instance.user_id}/{uuid.uuid4().hex}.{ext}"
