"""Provider-agnostic AI abstraction.

Concrete providers translate the NexaMind request/response contract to a
specific vendor API. Credentials are read only from settings/environment and
never from the database or the browser.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("nexamind.ai")


class AIError(Exception):
    """Base error for AI provider failures."""


class AINotConfigured(AIError):
    """Raised when no provider credentials are available."""


class AIProviderUnavailable(AIError):
    """Raised when the upstream provider cannot be reached or errors out."""


@dataclass
class AIResponse:
    text: str
    structured: dict = field(default_factory=dict)
    provider: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self):
        return self.prompt_tokens + self.completion_tokens


def _extract_json(text: str) -> dict:
    """Best-effort extraction of a JSON object embedded in model output."""
    if not text:
        return {}
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}


def _build_messages(messages, system):
    payload_messages = []
    if system:
        payload_messages.append({"role": "system", "content": system})
    payload_messages.extend(messages)
    return payload_messages


class BaseProvider:
    name = "base"

    def __init__(self, api_key="", model="", base_url="", timeout=None, max_tokens=None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout = timeout or settings.NEXAMIND.get("AI_TIMEOUT", 45)
        self.max_tokens = max_tokens or settings.NEXAMIND.get("AI_MAX_TOKENS", 1024)

    def complete(self, messages, system="", response_format=None) -> AIResponse:
        raise NotImplementedError

    def stream_chunks(self, messages, system=""):
        """Yield text deltas for a streaming reply.

        Default implementation falls back to the non-streaming completion and
        yields the whole text in one chunk, so every provider can stream.
        """
        response = self.complete(messages, system=system)
        if response.text:
            yield response.text


class OpenAICompatibleProvider(BaseProvider):
    """Works with OpenAI and any OpenAI-compatible chat completions endpoint."""

    name = "openai"

    def complete(self, messages, system="", response_format=None) -> AIResponse:
        if not self.api_key:
            raise AINotConfigured("No API key configured for the OpenAI provider.")
        base = (self.base_url or "https://api.openai.com/v1").rstrip("/")
        url = f"{base}/chat/completions"
        payload = self._payload(messages, system=system, response_format=response_format)
        try:
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise AIProviderUnavailable(f"Could not reach the AI provider: {exc}") from exc
        if resp.status_code >= 400:
            raise AIProviderUnavailable(
                f"AI provider returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content", "")
        usage = data.get("usage") or {}
        return AIResponse(
            text=text,
            structured=_extract_json(text),
            provider=self.name,
            model=data.get("model", self.model),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )

    def _payload(self, messages, system="", response_format=None, stream=False):
        payload = {
            "model": self.model or "gpt-4o-mini",
            "messages": _build_messages(messages, system),
            "temperature": 0.4,
            "max_tokens": self.max_tokens,
            "stream": stream,
        }
        if response_format:
            payload["response_format"] = response_format
        return payload

    def stream_chunks(self, messages, system=""):
        if not self.api_key:
            raise AINotConfigured("No API key configured for the OpenAI provider.")
        base = (self.base_url or "https://api.openai.com/v1").rstrip("/")
        url = f"{base}/chat/completions"
        payload = self._payload(messages, system=system, stream=True)
        try:
            resp = requests.post(
                url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
                stream=True,
            )
        except requests.RequestException as exc:
            raise AIProviderUnavailable(f"Could not reach the AI provider: {exc}") from exc
        if resp.status_code >= 400:
            raise AIProviderUnavailable(
                f"AI provider returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data_json = line[len("data:"):].strip()
            if data_json == "[DONE]":
                break
            try:
                chunk = json.loads(data_json)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = (choices[0].get("delta") or {}).get("content")
            if delta:
                yield delta


class GeminiProvider(BaseProvider):
    name = "gemini"

    def complete(self, messages, system="", response_format=None) -> AIResponse:
        if not self.api_key:
            raise AINotConfigured("No API key configured for the Gemini provider.")
        model = self.model or "gemini-1.5-flash"
        base = (self.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        url = f"{base}/models/{model}:generateContent?key={self.api_key}"
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        payload = {"contents": contents}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout)
        except requests.RequestException as exc:
            raise AIProviderUnavailable(f"Could not reach Gemini: {exc}") from exc
        if resp.status_code >= 400:
            raise AIProviderUnavailable(
                f"Gemini returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        data = resp.json()
        text = ""
        for candidate in data.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                text += part.get("text", "")
        usage = data.get("usageMetadata") or {}
        return AIResponse(
            text=text, structured=_extract_json(text), provider=self.name, model=model,
            prompt_tokens=usage.get("promptTokenCount", 0),
            completion_tokens=usage.get("candidatesTokenCount", 0),
        )

    def stream_chunks(self, messages, system=""):
        if not self.api_key:
            raise AINotConfigured("No API key configured for the Gemini provider.")
        model = self.model or "gemini-1.5-flash"
        base = (self.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        url = (f"{base}/models/{model}:streamGenerateContent?alt=sse&key={self.api_key}")
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        payload = {"contents": contents}
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        try:
            resp = requests.post(url, json=payload, timeout=self.timeout, stream=True)
        except requests.RequestException as exc:
            raise AIProviderUnavailable(f"Could not reach Gemini: {exc}") from exc
        if resp.status_code >= 400:
            raise AIProviderUnavailable(
                f"Gemini returned HTTP {resp.status_code}: {resp.text[:200]}"
            )
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data_json = line[len("data:"):].strip()
            try:
                chunk = json.loads(data_json)
            except json.JSONDecodeError:
                continue
            for candidate in chunk.get("candidates", []):
                for part in candidate.get("content", {}).get("parts", []):
                    text = part.get("text")
                    if text:
                        yield text


class LocalMLProvider(BaseProvider):
    """Fully offline assistant backed by the pure-Python NLP/ML engine.

    Uses TF-IDF retrieval, a Naive Bayes intent classifier and rule-based
    entity extraction over the user's own workspace. No network access and no
    API key are required, so it produces real (if simple) answers offline.
    """

    name = "local"

    def __init__(self, user=None, api_key="", model="", base_url="", timeout=None,
                 max_tokens=None):
        super().__init__(api_key=api_key, model=model, base_url=base_url,
                         timeout=timeout, max_tokens=max_tokens)
        self.user = user
        self.model = model or "nexamind-local-nlp"
        self.last_structured = None

    def _engine(self):
        from .local_ml import LocalAssistant
        from .learning import corpus_for, examples_for
        return LocalAssistant(
            timezone.now(),
            extra_examples=examples_for(self.user),
            corpus=corpus_for(self.user),
        )

    def _items(self):
        if self.user is None:
            return []
        from .context import build_workspace_items
        return build_workspace_items(self.user)

    def _reply(self, messages):
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        reply = self._engine().respond(last_user, self._items())
        return last_user, reply

    def complete(self, messages, system="", response_format=None) -> AIResponse:
        _last_user, reply = self._reply(messages)
        self.last_structured = {"actions": reply.actions}
        return AIResponse(
            text=reply.text, structured={"actions": reply.actions} if reply.actions else {},
            provider=self.name, model=self.model,
            prompt_tokens=len(reply.text.split()), completion_tokens=len(reply.text.split()),
        )

    def stream_chunks(self, messages, system=""):
        _last_user, reply = self._reply(messages)
        self.last_structured = {"actions": reply.actions}
        words = reply.text.split(" ")
        buffer = []
        for word in words:
            buffer.append(word)
            if len(buffer) >= 5:
                yield " ".join(buffer) + " "
                buffer = []
        if buffer:
            yield " ".join(buffer)


class OfflineDemoProvider(BaseProvider):
    """Deterministic provider used only when explicitly selected.

    It performs simple extractive work over the real, authorized context that
    is supplied to it. It is clearly labelled as an offline demo and never
    claims to be a live model.
    """

    name = "mock"

    def complete(self, messages, system="", response_format=None) -> AIResponse:
        last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        context = system or ""
        text = (
            "[Offline demo mode] No external AI provider is configured. "
            "NexaMind processed your request locally against your own data.\n\n"
            f"You asked: \"{last_user.strip()[:300]}\"\n\n"
            "To enable real AI responses, set AI_PROVIDER and AI_API_KEY in your "
            "environment and restart the server.\n\n"
            "Here is what I can see in your workspace right now:\n"
        )
        # Append a factual digest drawn from the injected context lines.
        digest = [line.strip("- ").strip() for line in context.splitlines()
                  if line.strip().startswith("- ")]
        if digest:
            text += "\n".join(f"{i + 1}. {d}" for i, d in enumerate(digest[:10]))
        else:
            text += "No summary data was available in the current context."
        return AIResponse(text=text, structured={}, provider=self.name, model="offline-demo",
                          prompt_tokens=0, completion_tokens=0)

    def stream_chunks(self, messages, system=""):
        response = self.complete(messages, system=system)
        words = response.text.split(" ")
        buffer = []
        for word in words:
            buffer.append(word)
            if len(buffer) >= 6:
                yield " ".join(buffer) + " "
                buffer = []
        if buffer:
            yield " ".join(buffer) + " "


def get_provider(user=None) -> BaseProvider:
    """Resolve the provider for a user, honouring per-user overrides.

    Raises AINotConfigured when nothing usable is available so callers can show
    a clear configuration message instead of fabricating a response.
    """
    cfg = settings.NEXAMIND
    provider_name = (cfg.get("AI_PROVIDER") or "").strip().lower()
    api_key = cfg.get("AI_API_KEY") or ""
    model = cfg.get("AI_MODEL") or ""
    base_url = cfg.get("AI_BASE_URL") or ""

    override = None
    if user is not None and getattr(user, "is_authenticated", False):
        override = getattr(user, "ai_config", None)

    if override and override.provider != "env":
        if override.provider == "mock":
            return OfflineDemoProvider(api_key="demo", model="offline-demo")
        if override.provider == "local":
            return LocalMLProvider(user=user, api_key="local", model=override.model)
        provider_name = override.provider
        model = override.model or model

    if provider_name == "local":
        return LocalMLProvider(user=user, api_key="local", model=model)
    if provider_name == "mock":
        return OfflineDemoProvider(api_key="demo", model="offline-demo")
    if provider_name in {"openai", "openai-compatible"}:
        return OpenAICompatibleProvider(api_key=api_key, model=model, base_url=base_url)
    if provider_name == "gemini":
        return GeminiProvider(api_key=api_key, model=model, base_url=base_url)

    if api_key:
        # Auto-detect a sensible provider from the key shape.
        return OpenAICompatibleProvider(api_key=api_key, model=model, base_url=base_url)

    raise AINotConfigured(
        "The AI assistant is not configured. Set AI_PROVIDER and AI_API_KEY, "
        "or select the offline demo provider in settings."
    )
