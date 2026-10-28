from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", views.NexaLoginView.as_view(), name="login"),
    path("logout/", views.NexaLogoutView.as_view(), name="logout"),
    path("verification-sent/", views.verification_sent, name="verification_sent"),
    path("verify/<str:token>/", views.verify_email, name="verify_email"),
    path("resend-verification/", views.resend_verification, name="resend_verification"),
    path("profile/", views.profile, name="profile"),
    path("preferences/", views.preferences, name="preferences"),
    path("theme/", views.set_theme, name="set_theme"),
    path("password/change/", views.change_password, name="change_password"),
    path("activity/", views.activity, name="activity"),
    path("sessions/", views.sessions, name="sessions"),
    path("sessions/revoke-others/", views.sessions_revoke_others, name="sessions_revoke_others"),
    path("sessions/<str:key>/revoke/", views.session_revoke, name="session_revoke"),
    path("delete/", views.delete_account, name="delete_account"),
    # Two-factor authentication
    path("two-factor/", views.twofactor, name="twofactor"),
    path("two-factor/setup/", views.twofactor_setup, name="twofactor_setup"),
    path("two-factor/verify/", views.twofactor_verify, name="twofactor_verify"),
    path("two-factor/disable/", views.twofactor_disable, name="twofactor_disable"),
    path("two-factor/backup-codes/", views.twofactor_backup_codes, name="twofactor_backup_codes"),
    # API access & data export
    path("api-tokens/", views.api_tokens, name="api_tokens"),
    path("api-tokens/regenerate/", views.api_token_regenerate, name="api_token_regenerate"),
    path("api-tokens/revoke/", views.api_token_revoke, name="api_token_revoke"),
    path("export/", views.data_export, name="data_export"),
    path("data/", views.data_privacy, name="data_privacy"),
    # Password reset
    path("password/reset/", views.NexaPasswordResetView.as_view(), name="password_reset"),
    path("password/reset/done/", views.NexaPasswordResetDoneView.as_view(), name="password_reset_done"),
    path("password/reset/<uidb64>/<token>/", views.NexaPasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("password/reset/complete/", views.NexaPasswordResetCompleteView.as_view(), name="password_reset_complete"),
]
