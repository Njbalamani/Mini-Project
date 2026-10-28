"""Small template helpers for the assistant workspace."""
import json

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter(name="jsonify")
def jsonify(value):
    """Serialize a value to JSON so it can be embedded in a data attribute."""
    return json.dumps(value, default=str)


@register.filter(name="action_label")
def action_label(action_type):
    return {
        "create_task": "Create task",
        "create_event": "Create event",
        "create_workflow": "Create workflow",
    }.get(action_type, "Proposed action")


@register.filter(name="action_icon")
def action_icon(action_type):
    return {
        "create_task": "check",
        "create_event": "calendar",
        "create_workflow": "bolt",
    }.get(action_type, "spark")
