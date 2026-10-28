"""Account views: registration, login, verification, profile, security."""
import json

from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import (
    LoginView,
    LogoutView,
    PasswordResetCompleteView,
    PasswordResetConfirmView,
    PasswordResetDoneView,
    PasswordResetView,
)
from django.contrib.sessions.models import Session
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.audit_logs.services import log_event

from . import twofactor as tfa
from .export import build_export_json, build_export_zip
from .forms import (
    NexaAuthenticationForm,
    NexaPasswordChangeForm,
    NexaPasswordResetForm,
    NexaSetPasswordForm,
    PreferenceForm,
    ProfileForm,
    RegistrationForm,
    TwoFactorDisableForm,
    TwoFactorVerifyForm,
)
from .models import LoginActivity, UserPreference, UserProfile
from .services import (
    clear_login_attempts,
    confirm_email_verification,
    delete_user_account,
    is_login_locked,
    issue_email_verification,
    record_login,
    register_failed_login,
)

User = get_user_model()


@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        issue_email_verification(user, request)
        log_event(actor=user, action="account.register", resource_type="user",
                  resource_id=user.pk, request=request)
        messages.success(request, "Account created. Check your email to verify your address.")
        return redirect("accounts:verification_sent")
    return render(request, "accounts/register.html", {"form": form})


class NexaLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = NexaAuthenticationForm

    def post(self, request, *args, **kwargs):
        email = (request.POST.get("username") or "").lower().strip()
        if email and is_login_locked(email):
            messages.error(
                request,
                "Too many failed attempts. Please wait a few minutes and try again.",
            )
            record_login(email, request, "failed")
            return render(request, self.template_name, {"form": self.get_form()})
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        email = (form.cleaned_data.get("username") or "").lower().strip()
        clear_login_attempts(email)
        response = super().form_valid(form)
        profile, _ = UserProfile.objects.get_or_create(user=self.request.user)
        self.request.session["totp_passed"] = not profile.totp_enabled
        log_event(actor=self.request.user, action="account.login",
                  request=self.request, resource_type="user", resource_id=self.request.user.pk)
        return response

    def form_invalid(self, form):
        email = (self.request.POST.get("username") or "").lower().strip()
        if email:
            register_failed_login(email)
            record_login(email, self.request, "failed")
        return super().form_invalid(form)


class NexaLogoutView(LogoutView):
    next_page = reverse_lazy("landing:home")

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            log_event(actor=request.user, action="account.logout", request=request)
        return super().dispatch(request, *args, **kwargs)


@login_required
def verification_sent(request):
    return render(request, "accounts/verification_sent.html")


@login_required
def verify_email(request, token):
    user, status = confirm_email_verification(token)
    if status == "verified":
        log_event(actor=user, action="account.email_verified", request=request)
        messages.success(request, "Your email has been verified. Welcome aboard!")
        return redirect("dashboard:home")
    if status == "already":
        messages.info(request, "This email was already verified.")
    elif status == "expired":
        messages.error(request, "This verification link has expired. Request a new one below.")
    else:
        messages.error(request, "This verification link is not valid.")
    return render(request, "accounts/verification_result.html", {"status": status})


@login_required
def resend_verification(request):
    if request.user.is_email_verified:
        messages.info(request, "Your email is already verified.")
    else:
        issue_email_verification(request.user, request, resend=True)
        messages.success(request, "A new verification email has been sent.")
    return redirect("dashboard:home")


@login_required
def profile(request):
    profile_obj, _ = UserProfile.objects.get_or_create(user=request.user)
    form = ProfileForm(request.POST or None, request.FILES or None, instance=profile_obj)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_event(actor=request.user, action="account.profile_updated", request=request)
        messages.success(request, "Profile updated.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form, "profile": profile_obj})


@login_required
def preferences(request):
    pref, _ = UserPreference.objects.get_or_create(user=request.user)
    form = PreferenceForm(request.POST or None, instance=pref)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Preferences saved.")
        return redirect("accounts:preferences")
    return render(request, "accounts/preferences.html", {"form": form})


@login_required
@require_http_methods(["POST"])
def set_theme(request):
    """Persist the user's light/dark theme preference (AJAX)."""
    theme = (request.POST.get("theme") or "").strip()
    if theme not in {"royal", "midnight", "light"}:
        return JsonResponse({"ok": False, "error": "invalid theme"}, status=400)
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if profile.theme != theme:
        profile.theme = theme
        profile.save(update_fields=["theme", "updated_at"])
    return JsonResponse({"ok": True, "theme": theme})


@login_required
def change_password(request):
    form = NexaPasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        update_session_auth_hash(request, form.user)
        log_event(actor=request.user, action="account.password_changed", request=request)
        messages.success(request, "Password updated successfully.")
        return redirect("accounts:profile")
    return render(request, "accounts/change_password.html", {"form": form})


@login_required
def activity(request):
    attempts = LoginActivity.objects.filter(user=request.user)[:50]
    return render(request, "accounts/activity.html", {"attempts": attempts})


def _active_sessions(user, current_key):
    """Return the user's live database-backed sessions (current first)."""
    from django.conf import settings

    age = int(getattr(settings, "SESSION_COOKIE_AGE", 1209600))
    sessions = []
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        data = session.get_decoded()
        if data.get("_auth_user_id") == str(user.pk):
            sessions.append({
                "key": session.session_key,
                "short": session.session_key[:8],
                "started": session.expire_date - timezone.timedelta(seconds=age),
                "expire_date": session.expire_date,
                "is_current": session.session_key == current_key,
            })
    sessions.sort(key=lambda item: (not item["is_current"], item["expire_date"]))
    return sessions


@login_required
def sessions(request):
    data = _active_sessions(request.user, request.session.session_key)
    return render(request, "accounts/sessions.html", {"sessions": data})


@login_required
@require_POST
def session_revoke(request, key):
    if key == request.session.session_key:
        messages.warning(request, "That is your current session. Use \u201cSign out\u201d instead.")
        return redirect("accounts:sessions")
    Session.objects.filter(session_key=key).delete()
    log_event(actor=request.user, action="account.session_revoked", request=request)
    messages.success(request, "Session signed out.")
    return redirect("accounts:sessions")


@login_required
@require_POST
def sessions_revoke_others(request):
    current = request.session.session_key
    removed = 0
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        if session.session_key == current:
            continue
        if session.get_decoded().get("_auth_user_id") == str(request.user.pk):
            session.delete()
            removed += 1
    log_event(actor=request.user, action="account.sessions_revoked_others",
              request=request, metadata={"revoked": removed})
    messages.success(request, f"Signed out {removed} other session(s).")
    return redirect("accounts:sessions")


@login_required
@require_http_methods(["POST"])
def delete_account(request):
    user = request.user
    log_event(actor=user, action="account.deleted", request=request, outcome="success")
    delete_user_account(user)
    logout(request)
    messages.success(request, "Your account and all associated data have been deleted.")
    return redirect("landing:home")


# --- Password reset flow (thin wrappers selecting our templates/forms) --------
class NexaPasswordResetView(PasswordResetView):
    template_name = "accounts/password_reset.html"
    form_class = NexaPasswordResetForm
    email_template_name = "accounts/emails/password_reset.txt"
    subject_template_name = "accounts/emails/password_reset_subject.txt"
    success_url = reverse_lazy("accounts:password_reset_done")


class NexaPasswordResetDoneView(PasswordResetDoneView):
    template_name = "accounts/password_reset_done.html"


class NexaPasswordResetConfirmView(PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    form_class = NexaSetPasswordForm
    success_url = reverse_lazy("accounts:password_reset_complete")


class NexaPasswordResetCompleteView(PasswordResetCompleteView):
    template_name = "accounts/password_reset_complete.html"


# --- Two-factor authentication (TOTP) ----------------------------------------
@login_required
def twofactor(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return render(request, "accounts/twofactor.html", {"profile": profile})


@login_required
def twofactor_setup(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if profile.totp_enabled:
        messages.info(request, "Two-factor authentication is already enabled.")
        return redirect("accounts:twofactor")

    if request.method == "POST":
        if tfa.verify_totp(profile, request.POST.get("code", "")):
            profile.totp_enabled = True
            profile.totp_confirmed_at = timezone.now()
            profile.save(update_fields=["totp_enabled", "totp_confirmed_at", "updated_at"])
            codes = tfa.generate_backup_codes(profile)
            request.session["totp_passed"] = True
            log_event(actor=request.user, action="account.2fa_enabled", request=request)
            messages.success(request, "Two-factor authentication is now enabled.")
            return render(request, "accounts/twofactor_backup_codes.html", {"codes": codes})
        messages.error(request, "That code did not match. Scan the QR code again and retry.")

    secret = tfa.generate_secret()
    profile.totp_secret = tfa.encrypt_secret(secret)
    profile.totp_enabled = False
    profile.save(update_fields=["totp_secret", "totp_enabled", "updated_at"])
    uri = tfa.provisioning_uri(profile, secret)
    return render(request, "accounts/twofactor_setup.html", {
        "profile": profile,
        "qr": tfa.qr_data_uri(uri),
    })


@login_required
def twofactor_verify(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.totp_enabled or request.session.get("totp_passed"):
        return redirect("dashboard:home")
    form = TwoFactorVerifyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if tfa.verify_any(profile, form.cleaned_data["code"]):
            request.session["totp_passed"] = True
            log_event(actor=request.user, action="account.2fa_passed", request=request)
            messages.success(request, "Verified. Welcome back.")
            return redirect(request.GET.get("next") or "dashboard:home")
        form.add_error("code", "That code is not valid. Try again or use a backup code.")
    return render(request, "accounts/twofactor_verify.html", {"form": form})


@login_required
def twofactor_disable(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.totp_enabled:
        messages.info(request, "Two-factor authentication is not enabled.")
        return redirect("accounts:twofactor")
    form = TwoFactorDisableForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        profile.totp_enabled = False
        profile.totp_secret = ""
        profile.totp_backup_codes = ""
        profile.totp_confirmed_at = None
        profile.save(update_fields=[
            "totp_enabled", "totp_secret", "totp_backup_codes", "totp_confirmed_at", "updated_at",
        ])
        request.session["totp_passed"] = True
        log_event(actor=request.user, action="account.2fa_disabled", request=request)
        messages.success(request, "Two-factor authentication has been disabled.")
        return redirect("accounts:twofactor")
    return render(request, "accounts/twofactor_disable.html", {"form": form})


@login_required
def twofactor_backup_codes(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not profile.totp_enabled:
        return redirect("accounts:twofactor")
    codes = tfa.generate_backup_codes(profile)
    log_event(actor=request.user, action="account.2fa_backup_codes", request=request)
    return render(request, "accounts/twofactor_backup_codes.html", {"codes": codes})


# --- API tokens ---------------------------------------------------------------
@login_required
def api_tokens(request):
    from rest_framework.authtoken.models import Token as TokenModel

    token, created = TokenModel.objects.get_or_create(user=request.user)
    return render(request, "accounts/api_tokens.html", {
        "token": token, "api_base": request.build_absolute_uri("/api/v1/"),
    })


@login_required
@require_http_methods(["POST"])
def api_token_regenerate(request):
    from rest_framework.authtoken.models import Token as TokenModel

    TokenModel.objects.filter(user=request.user).delete()
    token = TokenModel.objects.create(user=request.user)
    log_event(actor=request.user, action="account.api_token_regenerated", request=request)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "key": token.key})
    messages.success(request, "A new API token was generated.")
    return redirect("accounts:api_tokens")


@login_required
@require_http_methods(["POST"])
def api_token_revoke(request):
    from rest_framework.authtoken.models import Token as TokenModel

    TokenModel.objects.filter(user=request.user).delete()
    log_event(actor=request.user, action="account.api_token_revoked", request=request)
    messages.success(request, "Your API token was revoked.")
    return redirect("accounts:api_tokens")


# --- Data export / portability ------------------------------------------------
@login_required
def data_privacy(request):
    from apps.documents.models import Document

    return render(request, "accounts/export.html", {
        "document_count": Document.objects.filter(owner=request.user).count(),
    })


@login_required
def data_export(request):
    fmt = request.GET.get("format", "json").lower()
    if fmt == "zip":
        payload = build_export_zip(request.user)
        response = HttpResponse(payload, content_type="application/zip")
        response["Content-Disposition"] = 'attachment; filename="nexamind-export.zip"'
        return response
    data = json.dumps(build_export_json(request.user), indent=2, default=str)
    response = HttpResponse(data, content_type="application/json")
    response["Content-Disposition"] = 'attachment; filename="nexamind-export.json"'
    return response
