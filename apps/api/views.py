"""REST API viewsets. Every resource is scoped to the authenticated user."""
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai_assistant.models import AIUsageRecord, Conversation
from apps.calendar_manager.models import CalendarEvent, EventReminder
from apps.documents.models import Document
from apps.integrations.models import Integration
from apps.notifications.models import Notification
from apps.tasks.models import SavedTaskFilter, Tag, Task, TaskComment
from apps.workflow_automation.models import Workflow, WorkflowExecution

from .permissions import IsOwner, IsOwnerThroughTask, IsOwnerThroughWorkflow
from .serializers import (
    AIUsageSerializer,
    CalendarEventSerializer,
    ConversationDetailSerializer,
    ConversationSerializer,
    DocumentSerializer,
    IntegrationSerializer,
    NotificationSerializer,
    SavedTaskFilterSerializer,
    TagSerializer,
    TaskCommentSerializer,
    TaskSerializer,
    UserSerializer,
    WorkflowExecutionSerializer,
    WorkflowSerializer,
)

User = get_user_model()


class HealthView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({
            "service": "NexaMind API",
            "status": "ok",
            "time": timezone.now().isoformat(),
        })


class DashboardView(APIView):
    def get(self, request):
        from apps.dashboard.selectors import build_dashboard

        data = build_dashboard(request.user)
        for key in ("events", "activity"):
            data[key] = [dict(item.__dict__) for item in data[key][:5]]
        return Response(data)


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        qs = Task.objects.filter(owner=self.request.user)
        params = self.request.query_params
        status_v = params.get("status")
        priority_v = params.get("priority")
        category_v = params.get("category")
        tag_v = params.get("tag")
        search = params.get("q")
        if status_v:
            qs = qs.filter(status=status_v)
        if priority_v:
            qs = qs.filter(priority=priority_v)
        if category_v:
            qs = qs.filter(category__iexact=category_v)
        if tag_v:
            qs = qs.filter(tags__name__iexact=tag_v)
        if search:
            qs = qs.filter(title__icontains=search)
        return qs.prefetch_related("tags")

    def perform_create(self, serializer):
        serializer.save()


class TagViewSet(viewsets.ModelViewSet):
    serializer_class = TagSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        return Tag.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        from apps.tasks.services import _tag_color

        name = serializer.validated_data["name"]
        serializer.save(owner=self.request.user, color=_tag_color(name))


class TaskCommentViewSet(viewsets.ModelViewSet):
    serializer_class = TaskCommentSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerThroughTask]

    def get_queryset(self):
        qs = TaskComment.objects.filter(task__owner=self.request.user)
        task_id = self.request.query_params.get("task")
        if task_id:
            qs = qs.filter(task_id=task_id)
        return qs.select_related("author")


class SavedTaskFilterViewSet(viewsets.ModelViewSet):
    serializer_class = SavedTaskFilterSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        return SavedTaskFilter.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class CalendarEventViewSet(viewsets.ModelViewSet):
    serializer_class = CalendarEventSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        qs = CalendarEvent.objects.filter(owner=self.request.user)
        upcoming = self.request.query_params.get("upcoming")
        if upcoming:
            qs = qs.filter(end__gte=timezone.now())
        return qs

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user,
                        timezone=str(timezone.get_current_timezone()))

    @action(detail=False, methods=["get"])
    def free_slots(self, request):
        from datetime import date
        from apps.calendar_manager.services import find_free_slots

        raw = request.query_params.get("date")
        try:
            day = date.fromisoformat(raw or timezone.localdate().isoformat())
        except ValueError:
            day = timezone.localdate()
        slots = find_free_slots(request.user, day)
        return Response([
            {"start": s[0].isoformat(), "end": s[1].isoformat()} for s in slots
        ])


class ConversationViewSet(viewsets.ModelViewSet):
    serializer_class = ConversationSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        return Conversation.objects.filter(owner=self.request.user)

    def get_serializer_class(self):
        if self.action in {"retrieve", "create"}:
            return ConversationDetailSerializer
        return ConversationSerializer

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        conversation = self.get_object()
        from apps.ai_assistant.services import AINotConfigured, generate_reply

        text = (request.data.get("message") or "").strip()
        if not text:
            return Response({"error": "message is required."}, status=400)
        result = generate_reply(request.user, conversation, text)
        return Response({
            "ok": result["ok"],
            "configured": result.get("configured", True),
            "error": result.get("error", ""),
            "actions": result.get("actions", []),
        }, status=200)


class WorkflowViewSet(viewsets.ModelViewSet):
    serializer_class = WorkflowSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        return Workflow.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=["post"])
    def run(self, request, pk=None):
        workflow = self.get_object()
        from apps.workflow_automation.tasks import execute_workflow_task

        import uuid
        idempotency_key = f"api-{workflow.pk}-{uuid.uuid4().hex}"
        result = execute_workflow_task.apply(
            args=[workflow.pk, "api", {}, idempotency_key]
        )
        execution_id = result.get()
        if execution_id is None:
            return Response({"error": "Workflow did not produce an execution."}, status=500)
        execution = WorkflowExecution.objects.get(pk=execution_id)
        return Response(WorkflowExecutionSerializer(execution).data)


class WorkflowExecutionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = WorkflowExecutionSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerThroughWorkflow]

    def get_queryset(self):
        return WorkflowExecution.objects.filter(workflow__owner=self.request.user)


class IntegrationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = IntegrationSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        return Integration.objects.filter(user=self.request.user)

    @action(detail=True, methods=["post"])
    def disconnect(self, request, pk=None):
        integration = self.get_object()
        from apps.integrations.services import disconnect_integration

        disconnect_integration(request, integration)
        return Response(status=status.HTTP_204_NO_CONTENT)


class DocumentViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = DocumentSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        return Document.objects.filter(owner=self.request.user)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        note = self.get_object()
        if not note.is_read:
            from apps.notifications.models import Notification as N
            note.is_read = True
            note.read_at = timezone.now()
            note.save(update_fields=["is_read", "read_at"])
        return Response({"ok": True})

    @action(detail=False, methods=["post"])
    def read_all(self, request):
        from apps.notifications.services import mark_all_read

        count = mark_all_read(request.user)
        return Response({"ok": True, "marked": count})


class AnalyticsView(APIView):
    def get(self, request):
        from datetime import timedelta
        from apps.analytics.selectors import build_report

        end = timezone.now()
        start = end - timedelta(days=30)
        raw_start = request.query_params.get("start")
        raw_end = request.query_params.get("end")
        if raw_start:
            from django.utils.dateparse import parse_datetime
            parsed = parse_datetime(raw_start)
            if parsed:
                start = parsed
        if raw_end:
            from django.utils.dateparse import parse_datetime
            parsed = parse_datetime(raw_end)
            if parsed:
                end = parsed
        report = build_report(request.user, start, end)
        report["range"] = {"start": start.isoformat(), "end": end.isoformat()}
        return Response(report)


class AIUsageViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AIUsageSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get_queryset(self):
        return AIUsageRecord.objects.filter(user=self.request.user)