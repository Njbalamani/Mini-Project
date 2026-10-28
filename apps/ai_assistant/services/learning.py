"""Online learning for the local assistant.

The assistant improves over time without any external service by turning user
feedback and explicit corrections into labelled training examples. These are
persisted in :class:`AssistantTrainingExample` and folded back into the
classifier on every request, so a 👍 reinforces the recognised intent and a
correction teaches a new one.
"""
from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from ..models import AssistantFeedback, AssistantTrainingExample, Message

MIN_WEIGHT = 0.5
MAX_EXAMPLES = 400


def record_example(user, text, intent, source="feedback", weight=1.0):
    """Create or update a labelled training example (idempotent)."""
    text = (text or "").strip()
    if not text or not intent:
        return None
    example, created = AssistantTrainingExample.objects.get_or_create(
        user=user, text=text[:1000], intent=intent,
        defaults={"source": source, "weight": weight},
    )
    if not created and example.weight != weight:
        example.weight = weight
        example.source = source
        example.save(update_fields=["weight", "source"])
    return example


def _classify(text):
    from .local_ml import LocalAssistant
    assistant = LocalAssistant(timezone.now())
    return assistant.classify(text)[0]


def learn_from_feedback(message, rating):
    """Reinforce or discourage the intent that produced an assistant message."""
    if not isinstance(message, Message) or message.role != Message.Role.ASSISTANT:
        return None
    user_message = (
        Message.objects.filter(
            conversation=message.conversation, role=Message.Role.USER,
            created_at__lte=message.created_at,
        ).order_by("-created_at").first()
    )
    if user_message is None:
        return None
    intent = _classify(user_message.content)
    weight = 1.0 if rating > 0 else 0.0
    return record_example(message.conversation.owner, user_message.content, intent,
                          source="feedback", weight=weight)


def learn_correction(user, text, corrected_intent):
    """Teach an explicit correction, overriding any earlier label for the text."""
    text = (text or "").strip()
    if not text or not corrected_intent:
        return None
    AssistantTrainingExample.objects.filter(user=user, text=text[:1000]).exclude(
        intent=corrected_intent
    ).update(weight=0.0)
    return record_example(user, text, corrected_intent, source="correction", weight=1.0)


def examples_for(user, min_weight=MIN_WEIGHT, limit=MAX_EXAMPLES):
    """Return (intent, text) pairs the classifier should learn from."""
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    rows = (
        AssistantTrainingExample.objects
        .filter(Q(user=user) | Q(user__isnull=True), weight__gte=min_weight)
        .order_by("-created_at")[:limit]
    )
    return [(row.intent, row.text) for row in rows]


def corpus_for(user, limit=200):
    """Recent user utterances used to train the n-gram language model."""
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    return list(
        Message.objects.filter(conversation__owner=user, role=Message.Role.USER)
        .order_by("-created_at")
        .values_list("content", flat=True)[:limit]
    )


def training_stats(user):
    """Aggregate statistics about the learned model for the insights page."""
    examples = AssistantTrainingExample.objects.filter(
        Q(user=user) | Q(user__isnull=True), weight__gte=MIN_WEIGHT
    )
    by_intent: dict = {}
    for row in examples:
        by_intent[row.intent] = by_intent.get(row.intent, 0) + 1
    feedback = AssistantFeedback.objects.filter(user=user)
    positive = feedback.filter(rating=1).count()
    negative = feedback.filter(rating=-1).count()
    return {
        "total_examples": examples.count(),
        "learned_examples": AssistantTrainingExample.objects.filter(
            user=user, weight__gte=MIN_WEIGHT
        ).count(),
        "corrections": AssistantTrainingExample.objects.filter(
            user=user, source="correction", weight__gte=MIN_WEIGHT
        ).count(),
        "by_intent": dict(sorted(by_intent.items(), key=lambda kv: kv[1], reverse=True)),
        "feedback_positive": positive,
        "feedback_negative": negative,
        "accuracy_estimate": round(positive / (positive + negative), 2)
        if (positive + negative) else None,
    }
