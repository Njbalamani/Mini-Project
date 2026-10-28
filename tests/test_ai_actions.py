"""Tests for AI provider gating and structured-action validation."""
import pytest

from apps.ai_assistant.services import AINotConfigured, get_provider, validate_action
from apps.ai_assistant.services.schemas import ActionValidationError


def test_unknown_action_type_is_rejected():
    with pytest.raises(ActionValidationError):
        validate_action({"type": "drop_database", "payload": {}})


def test_short_task_title_is_rejected():
    with pytest.raises(ActionValidationError):
        validate_action({"type": "create_task", "payload": {"title": "a"}})


def test_valid_task_action_is_normalised():
    action = validate_action(
        {"type": "create_task", "payload": {"title": "Do it", "priority": "high"}}
    )
    assert action["type"] == "create_task"
    assert action["payload"]["title"] == "Do it"
    assert action["payload"]["priority"] == "high"


@pytest.mark.django_db
def test_provider_not_configured_raises(user):
    # With no provider configured (env blank and no stored config), the adapter
    # must refuse to fabricate a response. Force a blank AI config so the test
    # is independent of any developer .env file.
    from copy import deepcopy

    from django.conf import settings
    from django.test import override_settings

    cfg = deepcopy(settings.NEXAMIND)
    cfg.update({"AI_PROVIDER": "", "AI_API_KEY": "", "AI_MODEL": "", "AI_BASE_URL": ""})
    with override_settings(NEXAMIND=cfg), pytest.raises(AINotConfigured):
        get_provider(user)
