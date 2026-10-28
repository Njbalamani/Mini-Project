"""Task service layer: creation, status transitions, and activity logging."""
import calendar
import hashlib

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import TAG_PALETTE, Tag, Task, TaskActivity

MAX_TAGS_PER_TASK = 8
MAX_TAG_NAME = 40


class TaskTransitionError(ValidationError):
    pass


def _tag_color(name):
    digest = hashlib.sha1(name.lower().encode("utf-8")).hexdigest()
    return TAG_PALETTE[int(digest[:8], 16) % len(TAG_PALETTE)]


def get_or_create_tag(owner, name):
    """Fetch (or create) a user-owned tag, deriving a stable colour."""
    name = (name or "").strip()[:MAX_TAG_NAME]
    if not name:
        return None
    tag, created = Tag.objects.get_or_create(
        owner=owner, name=name, defaults={"color": _tag_color(name)},
    )
    return tag


def parse_tag_names(raw):
    """Split a comma-separated string into unique, trimmed tag names."""
    if not raw:
        return []
    names = []
    for part in raw.replace(";", ",").split(","):
        name = part.strip()[:MAX_TAG_NAME]
        if name and name not in names:
            names.append(name)
    return names[:MAX_TAGS_PER_TASK]


def set_task_tags(task, raw):
    """Replace a task's tags from a comma-separated string (or list)."""
    names = parse_tag_names(raw) if isinstance(raw, str) else [
        n.strip()[:MAX_TAG_NAME] for n in raw if n and n.strip()
    ][:MAX_TAGS_PER_TASK]
    tags = [get_or_create_tag(task.owner, name) for name in names]
    task.tags.set([tag for tag in tags if tag is not None])
    return task.tags.all()


def _advance(dt, recurrence):
    """Return the next due datetime for a recurrence rule."""
    if recurrence == Task.Recurrence.DAILY:
        return dt + timezone.timedelta(days=1)
    if recurrence == Task.Recurrence.WEEKLY:
        return dt + timezone.timedelta(days=7)
    if recurrence == Task.Recurrence.MONTHLY:
        year = dt.year + (dt.month // 12)
        month = dt.month % 12 + 1
        day = min(dt.day, calendar.monthrange(year, month)[1])
        return dt.replace(year=year, month=month, day=day)
    return None


@transaction.atomic
def create_task(owner, *, title, description="", priority=Task.Priority.MEDIUM,
                status=Task.Status.TODO, category="", due_date=None, actor=None,
                recurrence=Task.Recurrence.NONE, recurrence_until=None):
    task = Task(
        owner=owner, title=title.strip(), description=description, priority=priority,
        status=status, category=category.strip(), due_date=due_date,
        recurrence=recurrence, recurrence_until=recurrence_until,
    )
    task.full_clean(exclude=["owner"])
    task.save()
    if status == Task.Status.DONE:
        task.completed_at = timezone.now()
        task.save(update_fields=["completed_at"])
    TaskActivity.objects.create(task=task, actor=actor or owner, action="created")
    return task


def spawn_next_occurrence(task, actor=None):
    """Create the next instance of a recurring task once it is completed."""
    if task.recurrence == Task.Recurrence.NONE:
        return None
    base = task.due_date or timezone.now()
    next_due = _advance(base, task.recurrence)
    if next_due is None:
        return None
    if task.recurrence_until and next_due.date() > task.recurrence_until:
        return None
    nxt = create_task(
        task.owner, title=task.title, description=task.description,
        priority=task.priority, status=Task.Status.TODO, category=task.category,
        due_date=next_due, actor=actor, recurrence=task.recurrence,
        recurrence_until=task.recurrence_until,
    )
    set_task_tags(nxt, list(task.tags.values_list("name", flat=True)))
    TaskActivity.objects.create(
        task=task, actor=actor, action="updated",
        detail=f"Recurring: next occurrence scheduled for {next_due:%Y-%m-%d}.",
    )
    return nxt


@transaction.atomic
def update_task(task, actor=None, **fields):
    if "status" in fields and fields["status"] != task.status:
        new_status = fields["status"]
        if not task.can_transition_to(new_status):
            raise TaskTransitionError(
                f"Cannot move a task from '{task.get_status_display()}' "
                f"to '{dict(Task.Status.choices).get(new_status, new_status)}'."
            )
    old_status = task.status
    for field, value in fields.items():
        setattr(task, field, value)
    task.full_clean(exclude=["owner"])
    task.save()
    if task.status == Task.Status.DONE and old_status != Task.Status.DONE:
        task.completed_at = timezone.now()
        task.save(update_fields=["completed_at"])
        TaskActivity.objects.create(task=task, actor=actor, action="completed")
        spawn_next_occurrence(task, actor=actor)
    elif old_status == Task.Status.DONE and task.status != Task.Status.DONE:
        task.completed_at = None
        task.save(update_fields=["completed_at"])
        TaskActivity.objects.create(task=task, actor=actor, action="reopened")
    else:
        TaskActivity.objects.create(
            task=task, actor=actor, action="updated",
        )
    return task


@transaction.atomic
def set_status(task, new_status, actor=None):
    return update_task(task, actor=actor, status=new_status)
