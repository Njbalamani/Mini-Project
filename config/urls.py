"""Root URL configuration for NexaMind."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.dashboard.urls_landing")),
    path("accounts/", include("apps.accounts.urls")),
    path("app/", include("apps.dashboard.urls")),
    path("assistant/", include("apps.ai_assistant.urls")),
    path("tasks/", include("apps.tasks.urls")),
    path("calendar/", include("apps.calendar_manager.urls")),
    path("email/", include("apps.email_manager.urls")),
    path("workflows/", include("apps.workflow_automation.urls")),
    path("integrations/", include("apps.integrations.urls")),
    path("documents/", include("apps.documents.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("analytics/", include("apps.analytics.urls")),
    path("settings/", include("apps.subscriptions.urls")),
    path("audit/", include("apps.audit_logs.urls")),
    # REST API
    path("api/v1/", include("apps.api.urls")),
    path("api/schema/", SpectacularAPIView.as_view(), name="api-schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="api-schema"),
        name="api-docs",
    ),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

handler404 = "apps.dashboard.views.error_404"
handler500 = "apps.dashboard.views.error_500"
