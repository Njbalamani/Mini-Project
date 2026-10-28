"""Task views: list (table & kanban), detail, create, edit, status, delete."""
import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.audit_logs.services import log_event

from .forms import SavedTaskFilterForm, TagForm, TaskCommentForm, TaskForm
from .models import SavedTaskFilter, Tag, Task, TaskActivity, TaskComment
from .services import (
    TaskTransitionError,
    create_task,
    set_status,
    set_task_tags,
    update_task,
)

FILTER_KEYS = ("q", "status", "priority", "category", "tag", "sort", "view")


def _user_tasks(request):
    return Task.objects.filter(owner=request.user)


@login_required
def task_list(request):
    qs = _user_tasks(request)

    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    priority = request.GET.get("priority", "").strip()
    category = request.GET.get("category", "").strip()
    tag = request.GET.get("tag", "").strip()
    sort = request.GET.get("sort", "-created_at")

    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))
    if status in dict(Task.Status.choices):
        qs = qs.filter(status=status)
    if priority in dict(Task.Priority.choices):
        qs = qs.filter(priority=priority)
    if category:
        qs = qs.filter(category__iexact=category)
    if tag:
        qs = qs.filter(tags__name__iexact=tag)

    qs = qs.prefetch_related("tags")
    sort_map = {
        "due": "due_date", "-due": "-due_date",
        "priority": "priority", "-priority": "-priority",
        "created": "created_at", "-created": "-created_at",
    }
    qs = qs.order_by(sort_map.get(sort, "-created_at"))
    if tag:
        qs = qs.distinct()

    counts = _user_tasks(request).aggregate(
        total=Count("id"),
        done=Count("id", filter=Q(status=Task.Status.DONE)),
        open=Count("id", filter=~Q(status=Task.Status.DONE)),
    )
    categories = (
        _user_tasks(request).exclude(category="")
        .values_list("category", flat=True).distinct().order_by("category")
    )

    view_mode = request.GET.get("view", "list")
    context = {
        "tasks": qs, "counts": counts, "categories": categories,
        "current_q": q, "current_status": status, "current_priority": priority,
        "current_category": category, "current_tag": tag, "current_sort": sort, "view_mode": view_mode,
        "status_choices": Task.Status.choices, "priority_choices": Task.Priority.choices,
        "saved_filters": SavedTaskFilter.objects.filter(owner=request.user),
        "filter_form": SavedTaskFilterForm(),
        "all_tags": Tag.objects.filter(owner=request.user),
        "current_filters": {k: request.GET.get(k, "") for k in FILTER_KEYS if request.GET.get(k)},
    }
    if view_mode == "kanban":
        buckets = {choice: [] for choice, _ in Task.Status.choices}
        for task in qs[:200]:
            buckets[task.status].append(task)
        columns = [
            {"value": choice, "label": label, "tasks": buckets[choice],
             "count": len(buckets[choice])}
            for choice, label in Task.Status.choices
        ]
        context["kanban_columns"] = columns
    else:
        context["page_obj"] = Paginator(qs, 20).get_page(request.GET.get("page"))
    return render(request, "tasks/list.html", context)


@login_required
def task_detail(request, pk):
    task = get_object_or_404(Task, pk=pk, owner=request.user)
    activity = task.activity.select_related("actor")[:30]
    comments = task.comments.select_related("author")
    return render(request, "tasks/detail.html", {
        "task": task, "activity": activity, "comments": comments,
        "comment_form": TaskCommentForm(),
        "status_choices": Task.Status.choices,
    })


@login_required
def task_create(request):
    form = TaskForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        task = create_task(
            owner=request.user, title=data["title"], description=data.get("description", ""),
            status=data["status"], priority=data["priority"],
            category=data.get("category", ""), due_date=data.get("due_date"),
            actor=request.user, recurrence=data.get("recurrence", Task.Recurrence.NONE),
            recurrence_until=data.get("recurrence_until"),
        )
        set_task_tags(task, data.get("tags", ""))
        log_event(actor=request.user, action="task.created", resource_type="task",
                  resource_id=task.pk, request=request)
        messages.success(request, "Task created.")
        return redirect("tasks:detail", pk=task.pk)
    if request.method == "POST":
        messages.error(request, "Please correct the errors below.")
    return render(request, "tasks/form.html", {"form": form, "mode": "create"})


@login_required
def task_edit(request, pk):
    task = get_object_or_404(Task, pk=pk, owner=request.user)
    form = TaskForm(request.POST or None, instance=task, user=request.user)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            update_task(
                task, actor=request.user, title=data["title"], description=data.get("description", ""),
                status=data["status"], priority=data["priority"],
                category=data.get("category", ""), due_date=data.get("due_date"),
                recurrence=data.get("recurrence", Task.Recurrence.NONE),
                recurrence_until=data.get("recurrence_until"),
            )
        except TaskTransitionError as exc:
            messages.error(request, "; ".join(exc.messages))
            return render(request, "tasks/form.html", {"form": form, "mode": "edit", "task": task})
        set_task_tags(task, data.get("tags", ""))
        log_event(actor=request.user, action="task.updated", resource_type="task",
                  resource_id=task.pk, request=request)
        messages.success(request, "Task updated.")
        return redirect("tasks:detail", pk=task.pk)
    return render(request, "tasks/form.html", {"form": form, "mode": "edit", "task": task})


@login_required
@require_POST
def task_set_status(request, pk):
    task = get_object_or_404(Task, pk=pk, owner=request.user)
    new_status = request.POST.get("status")
    try:
        set_status(task, new_status, actor=request.user)
        log_event(actor=request.user, action="task.status_changed", resource_type="task",
                  resource_id=task.pk, request=request, metadata={"status": new_status})
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"ok": True, "status": task.status,
                                 "is_overdue": task.is_overdue})
        messages.success(request, "Task status updated.")
    except (TaskTransitionError, ValidationError) as exc:
        msg = "; ".join(getattr(exc, "messages", [str(exc)]))
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"ok": False, "error": msg}, status=400)
        messages.error(request, msg)
    return redirect(request.POST.get("next") or "tasks:list")


@login_required
def task_delete(request, pk):
    task = get_object_or_404(Task, pk=pk, owner=request.user)
    if request.method == "POST":
        log_event(actor=request.user, action="task.deleted", resource_type="task",
                  resource_id=task.pk, request=request)
        task.delete()
        messages.success(request, "Task deleted.")
        return redirect("tasks:list")
    return render(request, "tasks/confirm_delete.html", {"task": task})


@login_required
def task_activity(request, pk):
    task = get_object_or_404(Task, pk=pk, owner=request.user)
    activity = task.activity.select_related("actor")
    return render(request, "tasks/activity.html", {"task": task, "activity": activity})


@login_required
@require_POST
def task_bulk_action(request):
    """Apply one action to many tasks selected in the list/board view."""
    from django.utils.dateparse import parse_datetime

    ids = request.POST.getlist("ids")
    action = request.POST.get("action", "")
    tasks = Task.objects.filter(owner=request.user, pk__in=ids)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    errors = []

    if not ids:
        errors.append("No tasks selected.")
    elif action == "complete":
        for task in tasks:
            try:
                set_status(task, Task.Status.DONE, actor=request.user)
            except (TaskTransitionError, ValidationError) as exc:
                errors.append(f"{task.title}: {'; '.join(exc.messages)}")
    elif action == "reopen":
        for task in tasks:
            try:
                set_status(task, Task.Status.TODO, actor=request.user)
            except (TaskTransitionError, ValidationError) as exc:
                errors.append(f"{task.title}: {'; '.join(exc.messages)}")
    elif action == "priority":
        priority = request.POST.get("priority", "")
        if priority not in dict(Task.Priority.choices):
            errors.append("Unknown priority.")
        else:
            for task in tasks:
                update_task(task, actor=request.user, priority=priority)
    elif action == "reschedule":
        due = parse_datetime(request.POST.get("due_date", ""))
        if due is None:
            errors.append("Enter a valid date and time.")
        else:
            for task in tasks:
                update_task(task, actor=request.user, due_date=due)
    elif action == "delete":
        count = tasks.count()
        log_event(actor=request.user, action="task.bulk_deleted", resource_type="task",
                  request=request, detail=f"Deleted {count} tasks")
        tasks.delete()
    else:
        errors.append("Unknown action.")

    affected = 0 if action == "delete" else len(ids)
    if is_ajax:
        return JsonResponse({"ok": not errors, "errors": errors, "count": affected})
    if errors:
        messages.error(request, " ".join(errors))
    else:
        messages.success(request, "Bulk action applied.")
    return redirect(request.POST.get("next") or "tasks:list")


@login_required
@require_POST
def task_comment_add(request, pk):
    task = get_object_or_404(Task, pk=pk, owner=request.user)
    form = TaskCommentForm(request.POST)
    if form.is_valid():
        comment = form.save(commit=False)
        comment.task = task
        comment.author = request.user
        comment.save()
        TaskActivity.objects.create(
            task=task, actor=request.user, action="commented",
            detail=comment.body[:280],
        )
        log_event(actor=request.user, action="task.commented", resource_type="task",
                  resource_id=task.pk, request=request)
        messages.success(request, "Comment added.")
    else:
        messages.error(request, "Comment cannot be empty.")
    return redirect("tasks:detail", pk=pk)


@login_required
@require_POST
def task_comment_delete(request, pk, comment_pk):
    task = get_object_or_404(Task, pk=pk, owner=request.user)
    comment = get_object_or_404(TaskComment, pk=comment_pk, task=task, author=request.user)
    comment.delete()
    messages.success(request, "Comment removed.")
    return redirect("tasks:detail", pk=pk)


@login_required
@require_POST
def task_saved_filter_save(request):
    source = request.POST or request.GET
    filters = {
        key: source.get(key, "").strip()
        for key in FILTER_KEYS if source.get(key, "").strip()
    }
    form = SavedTaskFilterForm({"name": request.POST.get("name", "")})
    if not form.is_valid():
        messages.error(request, "; ".join(form.errors.get("name", ["Invalid name."])))
        return redirect(request.POST.get("next") or "tasks:list")
    SavedTaskFilter.objects.update_or_create(
        owner=request.user, name=form.cleaned_data["name"], defaults={"query": filters},
    )
    messages.success(request, f"Saved view \u201c{form.cleaned_data['name']}\u201d.")
    return redirect(request.POST.get("next") or "tasks:list")


@login_required
@require_POST
def task_saved_filter_delete(request, pk):
    saved = get_object_or_404(SavedTaskFilter, pk=pk, owner=request.user)
    saved.delete()
    messages.success(request, "Saved view removed.")
    return redirect(request.POST.get("next") or "tasks:list")


@login_required
def task_export_csv(request):
    """Download the current user's tasks as a CSV file."""
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="nexamind-tasks.csv"'
    writer = csv.writer(response)
    writer.writerow([
        "Title", "Status", "Priority", "Category", "Tags", "Due date",
        "Recurrence", "Created", "Completed",
    ])
    for task in _user_tasks(request).prefetch_related("tags").order_by("-created_at"):
        writer.writerow([
            task.title,
            task.get_status_display(),
            task.get_priority_display(),
            task.category,
            ", ".join(task.tags.values_list("name", flat=True)),
            task.due_date.isoformat() if task.due_date else "",
            task.get_recurrence_display(),
            task.created_at.isoformat(),
            task.completed_at.isoformat() if task.completed_at else "",
        ])
    return response


@login_required
def tag_list(request):
    """Manage tags: list with usage counts and create new ones inline."""
    tags = (
        Tag.objects.filter(owner=request.user)
        .annotate(task_count=Count("tasks"))
        .order_by("name")
    )
    form = TagForm(request.POST or None, user=request.user)
    if request.method == "POST":
        if form.is_valid():
            tag = form.save(commit=False)
            tag.owner = request.user
            tag.save()
            log_event(actor=request.user, action="task.tag_created",
                      resource_type="tag", resource_id=tag.pk, request=request)
            messages.success(request, f"Tag \u201c{tag.name}\u201d created.")
            return redirect("tasks:tags")
        messages.error(request, "Please correct the errors below.")
    return render(request, "tasks/tags.html", {"tags": tags, "form": form})


@login_required
def tag_edit(request, pk):
    tag = get_object_or_404(Tag, pk=pk, owner=request.user)
    form = TagForm(request.POST or None, instance=tag, user=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        log_event(actor=request.user, action="task.tag_updated",
                  resource_type="tag", resource_id=tag.pk, request=request)
        messages.success(request, "Tag updated.")
        return redirect("tasks:tags")
    return render(request, "tasks/tag_form.html", {"form": form, "tag": tag})


@login_required
@require_POST
def tag_delete(request, pk):
    tag = get_object_or_404(Tag, pk=pk, owner=request.user)
    name = tag.name
    tag.delete()
    log_event(actor=request.user, action="task.tag_deleted",
              resource_type="tag", request=request, metadata={"name": name})
    messages.success(request, f"Tag \u201c{name}\u201d deleted.")
    return redirect("tasks:tags")
