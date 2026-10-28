"""Conversation, message, provider configuration and usage models."""
from django.conf import settings
from django.db import models


class Conversation(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations"
    )
    title = models.CharField(max_length=200, default="New conversation")
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["owner", "-updated_at"])]

    def __str__(self):
        return self.title

    def auto_title(self):
        first = self.messages.filter(role=Message.Role.USER).order_by("created_at").first()
        if first:
            self.title = (first.content[:57] + "...") if len(first.content) > 60 else first.content
            self.save(update_fields=["title"])


class Message(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        SYSTEM = "system", "System"
        TOOL = "tool", "Tool"

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=12, choices=Role.choices)
    content = models.TextField()
    # Structured payload returned by the assistant (proposed actions, etc.)
    structured = models.JSONField(default=dict, blank=True)
    token_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["conversation", "created_at"])]

    def __str__(self):
        return f"{self.role}: {self.content[:40]}"


class AIProviderConfiguration(models.Model):
    """Optional per-user provider override. Falls back to environment config."""

    PROVIDERS = [
        ("env", "Environment default"),
        ("local", "Local ML (offline, no key)"),
        ("openai", "OpenAI-compatible"),
        ("gemini", "Google Gemini"),
        ("mock", "Offline demo"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_config"
    )
    provider = models.CharField(max_length=16, choices=PROVIDERS, default="env")
    model = models.CharField(max_length=80, blank=True)
    temperature = models.FloatField(default=0.4)
    system_prompt = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"AI config<{self.user_id}:{self.provider}>"


class AIUsageRecord(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ai_usage"
    )
    conversation = models.ForeignKey(
        Conversation, on_delete=models.SET_NULL, null=True, blank=True
    )
    provider = models.CharField(max_length=24)
    model = models.CharField(max_length=80, blank=True)
    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    total_tokens = models.PositiveIntegerField(default=0)
    success = models.BooleanField(default=True)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Usage<{self.user_id}:{self.total_tokens} tokens>"


class AssistantTrainingExample(models.Model):
    """Labelled examples the local ML engine learns from (seeded from feedback
    and explicit corrections). Persisted so learning survives restarts."""

    SOURCES = [
        ("seed", "Seed"),
        ("feedback", "User feedback"),
        ("correction", "User correction"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
        related_name="ai_training_examples",
    )
    text = models.TextField()
    intent = models.CharField(max_length=32)
    weight = models.FloatField(default=1.0)
    source = models.CharField(max_length=16, choices=SOURCES, default="feedback")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("user", "text", "intent")
        indexes = [models.Index(fields=["user", "intent"])]

    def __str__(self):
        return f"Example<{self.intent}:{self.text[:30]}>"


class AssistantFeedback(models.Model):
    message = models.OneToOneField(
        Message, on_delete=models.CASCADE, related_name="feedback"
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    rating = models.SmallIntegerField(choices=[(1, "Helpful"), (-1, "Not helpful")])
    comment = models.CharField(max_length=400, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Feedback<{self.message_id}:{self.rating}>"
