"""Account related service-layer helpers.

Business logic lives here rather than in views so that the same behaviour is
reusable from the REST API, management commands and background tasks.
"""
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import EmailVerification, LoginActivity

logger = logging.getLogger("nexamind.accounts")
User = get_user_model()


def _absolute_uri(request, path):
    if request is not None:
        return request.build_absolute_uri(path)
    base = settings.NEXAMIND.get("SITE_BASE_URL", "http://localhost:8000")
    return f"{base.rstrip('/')}{path}"


@transaction.atomic
def issue_email_verification(user, request=None, resend=False):
    """Create a fresh verification token and email the link to the user."""
    EmailVerification.objects.filter(user=user, verified_at__isnull=True).update(
        verified_at=timezone.now()
    )
    verification = EmailVerification.objects.create(user=user)
    link = _absolute_uri(
        request, reverse("accounts:verify_email", args=[verification.token])
    )
    subject = "Verify your NexaMind account"
    body = render_to_string(
        "accounts/emails/verify_email.txt",
        {"user": user, "link": link, "resend": resend},
    )
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=True)
    return verification


@transaction.atomic
def confirm_email_verification(token):
    """Mark a verification token as used and verify the user's email."""
    try:
        verification = EmailVerification.objects.select_related("user").get(token=token)
    except EmailVerification.DoesNotExist:
        return None, "invalid"

    if verification.verified_at is not None:
        return verification.user, "already"
    if timezone.now() >= verification.expires_at:
        return verification.user, "expired"

    verification.verified_at = timezone.now()
    verification.save(update_fields=["verified_at"])
    verification.user.is_email_verified = True
    verification.user.save(update_fields=["is_email_verified"])
    return verification.user, "verified"


def record_login(email, request, result, user=None):
    """Persist a login attempt for the activity history."""
    ip = None
    ua = ""
    if request is not None:
        ip = _client_ip(request)
        ua = (request.META.get("HTTP_USER_AGENT") or "")[:300]
    return LoginActivity.objects.create(
        user=user, email_attempted=(email or "")[:254], result=result,
        ip_address=ip, user_agent=ua,
    )


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def is_login_locked(email):
    key = f"login-lock:{email.lower()}"
    attempts = cache.get(key, 0)
    return attempts >= settings.NEXAMIND.get("LOGIN_MAX_ATTEMPTS", 8)


def register_failed_login(email):
    key = f"login-lock:{email.lower()}"
    attempts = cache.get(key, 0) + 1
    timeout = settings.NEXAMIND.get("LOGIN_LOCKOUT_MINUTES", 15) * 60
    cache.set(key, attempts, timeout)
    return attempts


def clear_login_attempts(email):
    cache.delete(f"login-lock:{email.lower()}")


@transaction.atomic
def delete_user_account(user):
    """Delete an account and all owned data (cascades handle related rows)."""
    email = user.email
    user.delete()
    logger.info("Account deleted: %s", email)
