"""Tests for real-time notifications (Channels WebSocket) and AI streaming."""
import asyncio
import json

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.test import Client

from apps.ai_assistant.models import Conversation
from apps.notifications.consumers import NotificationConsumer
from apps.notifications.services import notify


@pytest.mark.django_db(transaction=True)
def test_websocket_pushes_live_notification(user):
    async def scenario():
        communicator = WebsocketCommunicator(
            NotificationConsumer.as_asgi(), "/ws/notifications/"
        )
        communicator.scope["user"] = user
        connected, _ = await communicator.connect()
        assert connected

        @database_sync_to_async
        def create_notif():
            return notify(
                user, type="system", title="Live!", message="hello from channels",
                url="/app/", dedupe_key="ws-live-test",
            )

        created = await create_notif()
        assert created is not None

        msg = await asyncio.wait_for(communicator.receive_json_from(), timeout=3)
        assert msg["key"] == "nm-notif"
        assert msg["title"] == "Live!"
        assert msg["url"] == "/app/"
        await communicator.disconnect()

    asyncio.run(scenario())


@pytest.mark.django_db
def test_websocket_rejects_anonymous():
    async def scenario():
        communicator = WebsocketCommunicator(
            NotificationConsumer.as_asgi(), "/ws/notifications/"
        )
        communicator.scope["user"] = None
        connected, _ = await communicator.connect()
        assert not connected

    asyncio.run(scenario())


@pytest.mark.django_db
def test_send_message_streams_sse(user, settings):
    settings.NEXAMIND = dict(settings.NEXAMIND, AI_PROVIDER="mock")
    convo = Conversation.objects.create(owner=user, title="Test stream")
    client = Client()
    client.force_login(user)
    response = client.post(
        f"/assistant/c/{convo.pk}/send/",
        {"message": "hello"},
        headers={"Accept": "text/event-stream"},
    )
    assert response.status_code == 200
    assert response["Content-Type"] == "text/event-stream"
    body = b"".join(response.streaming_content).decode()
    events = [
        json.loads(line[5:].strip())
        for line in body.split("\n")
        if line.startswith("data:")
    ]
    types = [e["type"] for e in events]
    assert types[0] == "start"
    assert "delta" in types
    assert types[-1] == "done"
    final = events[-1]
    assert final["assistant_message"]["content"]
    assert final["assistant_message"]["id"]


@pytest.mark.django_db
def test_send_message_non_stream_json_fallback(user, settings):
    settings.NEXAMIND = dict(settings.NEXAMIND, AI_PROVIDER="mock")
    convo = Conversation.objects.create(owner=user, title="Test json")
    client = Client()
    client.force_login(user)
    response = client.post(f"/assistant/c/{convo.pk}/send/", {"message": "hello"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["assistant_message"]["content"]


@pytest.mark.django_db
def test_theme_endpoint_persists(user):
    client = Client()
    client.force_login(user)
    response = client.post("/accounts/theme/", {"theme": "light"})
    assert response.status_code == 200
    assert response.json() == {"ok": True, "theme": "light"}
    user.profile.refresh_from_db()
    assert user.profile.theme == "light"
    bad = client.post("/accounts/theme/", {"theme": "neon"})
    assert bad.status_code == 400