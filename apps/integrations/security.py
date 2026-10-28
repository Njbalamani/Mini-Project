"""Step-up identity confirmation for sensitive integration actions.

Connecting or disconnecting a third-party account changes what NexaMind can
reach on the user's behalf, so it is gated behind a fresh identity check: a TOTP
code when two-factor is enabled, otherwise the account password. A successful
check is remembered in the session for a short window so the user is not prompted
on every click.
"""
from __future__ import annotations

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from apps.accounts import twofactor as tfa
from apps.accounts.models import UserProfile

STEP_UP_SESSION_KEY = "integration_step_up_at"
STEP_UP_NEXT_KEY = "integration_step_up_next"
STEP_UP_TTL_SECONDS = 300


def _now_ts():
    return timezone.now().timestamp()


def is_verified(request):
    """True when the user confirmed their identity recently enough."""
    stamp = request.session.get(STEP_UP_SESSION_KEY)
    if not stamp:
        return False
    try:
        return (_now_ts() - float(stamp)) <= STEP_UP_TTL_SECONDS
    except (TypeError, ValueError):
        return False


def mark_verified(request):
    request.session[STEP_UP_SESSION_KEY] = _now_ts()


def clear_verified(request):
    request.session.pop(STEP_UP_SESSION_KEY, None)


def remember_next(request, next_url):
    request.session[STEP_UP_NEXT_KEY] = next_url


def pop_next(request, default_name="integrations:center"):
    return request.session.pop(STEP_UP_NEXT_KEY, None) or reverse(default_name)


def verify_challenge(request, password=None, code=None):
    """Validate the user's step-up challenge.

    Returns (ok, message). Uses TOTP when enabled, else the account password.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if profile.totp_enabled:
        if code and tfa.verify_any(profile, code):
            return True, ""
        return False, "That verification code did not match."
    if password and request.user.check_password(password):
        return True, ""
    return False, "Incorrect password."


def require_verified(request, next_url):
    """Return a redirect to the step-up page, or None if already verified."""
    if is_verified(request):
        return None
    remember_next(request, next_url)
    messages.info(request, "Confirm it's you before changing connected accounts.")
    return redirect("integrations:step_up")
