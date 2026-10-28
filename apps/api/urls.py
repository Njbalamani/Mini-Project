from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("tasks/comments", views.TaskCommentViewSet, basename="task-comment")
router.register("saved-task-filters", views.SavedTaskFilterViewSet, basename="saved-task-filter")
router.register("tags", views.TagViewSet, basename="tag")
router.register("tasks", views.TaskViewSet, basename="task")
router.register("calendar/events", views.CalendarEventViewSet, basename="event")
router.register("assistant/conversations", views.ConversationViewSet, basename="conversation")
router.register("workflows", views.WorkflowViewSet, basename="workflow")
router.register("workflows/executions", views.WorkflowExecutionViewSet, basename="workflow-execution")
router.register("integrations", views.IntegrationViewSet, basename="integration")
router.register("documents", views.DocumentViewSet, basename="document")
router.register("notifications", views.NotificationViewSet, basename="notification")
router.register("ai/usage", views.AIUsageViewSet, basename="ai-usage")

urlpatterns = [
    path("", include(router.urls)),
    path("health/", views.HealthView.as_view(), name="health"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("accounts/me/", views.MeView.as_view(), name="me"),
    path("analytics/", views.AnalyticsView.as_view(), name="analytics"),
]