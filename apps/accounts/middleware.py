"""Session security middleware and request helpers."""
import time

from django.conf import settings
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse


class SessionSecurityMiddleware:
    """Enforce an optional idle timeout and rotate nothing sensitive.

    When NEXAMIND['SESSION_IDLE_MINUTES'] is greater than zero, an authenticated
    session that has been idle for longer than that is logged out.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.idle_limit = settings.NEXAMIND.get("SESSION_IDLE_MINUTES", 0)

    def __call__(self, request):
        if self.idle_limit and request.user.is_authenticated:
            now = int(time.time())
            last = request.session.get("_last_activity")
            if last and now - last > self.idle_limit * 60:
                logout(request)
                if request.path.startswith("/api/"):
                    from django.http import JsonResponse
                    return JsonResponse({"detail": "Session expired."}, status=401)
                return redirect(f"{reverse('accounts:login')}?expired=1")
            request.session["_last_activity"] = now
        return self.get_response(request)


class TwoFactorMiddleware:
    """Require a second factor before an authenticated session is fully usable.

    When a user has TOTP enabled but has not yet passed the challenge in this
    session, every request is redirected to the verification view (API calls
    receive 401). A small allowlist avoids redirect loops.
    """

    ALLOWED_PREFIXES = (
        "/accounts/login/",
        "/accounts/logout/",
        "/accounts/two-factor/",
        "/static/",
        "/media/",
        "/admin/jsi18n/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated and not request.session.get("totp_passed"):
            profile = getattr(user, "profile", None)
            if profile is not None and profile.totp_enabled:
                path = request.path
                if not path.startswith(self.ALLOWED_PREFIXES):
                    if path.startswith("/api/"):
                        from django.http import JsonResponse

                        return JsonResponse(
                            {"detail": "Two-factor authentication required."}, status=401
                        )
                    return redirect(reverse("accounts:twofactor_verify"))
        return self.get_response(request)
