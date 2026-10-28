"""WebSocket consumer pushing live notifications to connected users."""
from channels.generic.websocket import AsyncJsonWebsocketConsumer

GROUP_PREFIX = "user_notifications"


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope.get("user")
        if not self.user or not self.user.is_authenticated:
            await self.close()
            return
        self.group_name = f"{GROUP_PREFIX}_{self.user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notify(self, event):
        """Handler for group_send events with type="notify"."""
        await self.send_json(
            {
                "id": event.get("id"),
                "type": event.get("notif_type", "system"),
                "level": event.get("level", "info"),
                "title": event.get("title", ""),
                "message": event.get("message", ""),
                "url": event.get("url", ""),
                "created_at": event.get("created_at"),
                "key": event.get("key"),
            }
        )