from django.contrib import admin

from .models import (
    Workflow,
    WorkflowAction,
    WorkflowCondition,
    WorkflowExecution,
    WorkflowExecutionStep,
    WorkflowTrigger,
)


class TriggerInline(admin.TabularInline):
    model = WorkflowTrigger
    extra = 0


class ConditionInline(admin.TabularInline):
    model = WorkflowCondition
    extra = 0


class ActionInline(admin.TabularInline):
    model = WorkflowAction
    extra = 0


@admin.register(Workflow)
class WorkflowAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "is_enabled", "run_count", "last_run_at")
    list_filter = ("is_enabled",)
    search_fields = ("name",)
    inlines = [TriggerInline, ConditionInline, ActionInline]


class StepInline(admin.TabularInline):
    model = WorkflowExecutionStep
    extra = 0


@admin.register(WorkflowExecution)
class WorkflowExecutionAdmin(admin.ModelAdmin):
    list_display = ("workflow", "status", "trigger_reason", "started_at", "finished_at")
    list_filter = ("status",)
    inlines = [StepInline]
