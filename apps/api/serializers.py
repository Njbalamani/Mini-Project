"""DRF serializers for the NexaMind API."""
from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.ai_assistant.models import AIUsageRecord, Conversation, Message
from apps.calendar_manager.models import CalendarEvent
from apps.documents.models import Document
from apps.integrations.models import Integration
from apps.notifications.models import Notification
from apps.tasks.models import SavedTaskFilter, Tag, Task, TaskComment
from apps.workflow_automation.models import Workflow, WorkflowExecution

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "full_name", "is_email_verified", "date_joined"]
        read_only_fields = fields


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name", "color", "created_at"]
        read_only_fields = ["color", "created_at"]


class TaskSerializer(serializers.ModelSerializer):
    is_overdue = serializers.BooleanField(read_only=True)
    tags = serializers.SerializerMethodField()
    tag_names = serializers.ListField(
        child=serializers.CharField(max_length=40), required=False, write_only=True
    )

    class Meta:
        model = Task
        fields = ["id", "title", "description", "status", "priority", "category",
                  "due_date", "completed_at", "is_overdue", "tags", "tag_names",
                  "created_at", "updated_at"]
        read_only_fields = ["completed_at", "created_at", "updated_at"]

    def get_tags(self, obj):
        return [{"name": tag.name, "color": tag.color} for tag in obj.tags.all()]

    def create(self, validated_data):
        from apps.tasks.services import create_task, set_task_tags
        tag_names = validated_data.pop("tag_names", None)
        task = create_task(self.context["request"].user, **validated_data)
        if tag_names:
            set_task_tags(task, tag_names)
        return task

    def update(self, instance, validated_data):
        from apps.tasks.services import set_task_tags
        tag_names = validated_data.pop("tag_names", None)
        instance = super().update(instance, validated_data)
        if tag_names is not None:
            set_task_tags(instance, tag_names)
        return instance


class TaskCommentSerializer(serializers.ModelSerializer):
    author_name = serializers.CharField(source="author.display_name", read_only=True)

    class Meta:
        model = TaskComment
        fields = ["id", "task", "author", "author_name", "body", "created_at", "updated_at"]
        read_only_fields = ["author", "created_at", "updated_at"]

    def validate_task(self, task):
        if task.owner_id != self.context["request"].user.pk:
            raise serializers.ValidationError("Task not found.")
        return task

    def create(self, validated_data):
        return TaskComment.objects.create(
            author=self.context["request"].user, **validated_data
        )


class SavedTaskFilterSerializer(serializers.ModelSerializer):
    query_string = serializers.CharField(read_only=True)

    class Meta:
        model = SavedTaskFilter
        fields = ["id", "name", "query", "pinned", "query_string", "created_at"]
        read_only_fields = ["query_string", "created_at"]


class CalendarEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = CalendarEvent
        fields = ["id", "title", "description", "location", "start", "end", "all_day",
                  "recurrence", "source", "created_at", "updated_at"]
        read_only_fields = ["source", "created_at", "updated_at"]

    def validate(self, attrs):
        start = attrs.get("start", getattr(self.instance, "start", None))
        end = attrs.get("end", getattr(self.instance, "end", None))
        if start and end and end < start:
            raise serializers.ValidationError({"end": "End must be after start."})
        return attrs


class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ["id", "role", "content", "structured", "token_count", "created_at"]
        read_only_fields = fields


class ConversationSerializer(serializers.ModelSerializer):
    message_count = serializers.IntegerField(source="messages.count", read_only=True)

    class Meta:
        model = Conversation
        fields = ["id", "title", "is_archived", "message_count", "created_at", "updated_at"]
        read_only_fields = ["created_at", "updated_at"]


class ConversationDetailSerializer(ConversationSerializer):
    messages = MessageSerializer(many=True, read_only=True)

    class Meta(ConversationSerializer.Meta):
        fields = ConversationSerializer.Meta.fields + ["messages"]


class WorkflowExecutionSerializer(serializers.ModelSerializer):
    workflow_name = serializers.CharField(source="workflow.name", read_only=True)

    class Meta:
        model = WorkflowExecution
        fields = ["id", "workflow", "workflow_name", "status", "trigger_reason",
                  "error", "started_at", "finished_at"]
        read_only_fields = ["status", "error", "started_at", "finished_at"]


class WorkflowSerializer(serializers.ModelSerializer):
    trigger_type = serializers.CharField(write_only=True, required=True)
    condition_type = serializers.CharField(write_only=True, required=True)
    action_type = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = Workflow
        fields = ["id", "name", "description", "is_enabled", "run_count", "last_run_at",
                  "trigger_type", "condition_type", "action_type", "created_at"]
        read_only_fields = ["run_count", "last_run_at", "created_at"]

    def create(self, validated_data):
        from apps.workflow_automation.models import (
            WorkflowAction, WorkflowCondition, WorkflowTrigger,
        )
        trigger_type = validated_data.pop("trigger_type")
        condition_type = validated_data.pop("condition_type")
        action_type = validated_data.pop("action_type")
        workflow = Workflow.objects.create(owner=self.context["request"].user, **validated_data)
        WorkflowTrigger.objects.create(workflow=workflow, trigger_type=trigger_type)
        WorkflowCondition.objects.create(workflow=workflow, condition_type=condition_type)
        WorkflowAction.objects.create(workflow=workflow, action_type=action_type, order=1)
        return workflow


class IntegrationSerializer(serializers.ModelSerializer):
    label = serializers.CharField(read_only=True)

    class Meta:
        model = Integration
        fields = ["id", "provider", "label", "status", "external_account", "scopes",
                  "last_synced_at", "last_error", "updated_at"]
        read_only_fields = fields


class DocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Document
        fields = ["id", "title", "original_name", "size_bytes", "status", "page_count",
                  "error", "created_at"]
        read_only_fields = ["status", "page_count", "error", "created_at", "size_bytes"]


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "type", "level", "title", "message", "url", "is_read", "created_at"]
        read_only_fields = ["type", "level", "title", "message", "url", "created_at"]


class AIUsageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIUsageRecord
        fields = ["id", "provider", "model", "total_tokens", "success", "created_at"]
        read_only_fields = fields
