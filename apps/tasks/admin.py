from django.contrib import admin

from .models import SavedTaskFilter, Tag, Task, TaskActivity, TaskComment


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "color", "created_at")
    list_filter = ("owner",)
    search_fields = ("name",)


class TaskActivityInline(admin.TabularInline):
    model = TaskActivity
    extra = 0
    readonly_fields = ("actor", "action", "detail", "created_at")


class TaskCommentInline(admin.TabularInline):
    model = TaskComment
    extra = 0
    readonly_fields = ("author", "body", "created_at", "updated_at")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "status", "priority", "due_date", "created_at")
    list_filter = ("status", "priority", "category")
    search_fields = ("title", "description")
    inlines = [TaskActivityInline, TaskCommentInline]


admin.site.register(TaskActivity)
admin.site.register(TaskComment)
admin.site.register(SavedTaskFilter)
