import json

from channels.generic.websocket import AsyncWebsocketConsumer


class JobStatusConsumer(AsyncWebsocketConsumer):
    group_name = "job_updates"

    async def connect(self):
        user = self.scope.get("user")

        if not user or user.is_anonymous:
            await self.close(code=4001)
            return

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )

        await self.accept()

        await self.send_json(
            {
                "type": "connection_ack",
                "message": "Connected to OpenLIMS real-time job updates.",
            }
        )

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name,
        )

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return

        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send_json(
                {
                    "type": "error",
                    "message": "Invalid JSON message.",
                }
            )
            return

        if data.get("type") == "ping":
            await self.send_json(
                {
                    "type": "pong",
                    "message": "OpenLIMS real-time socket is alive.",
                }
            )

    async def job_update(self, event):
        await self.send_json(event.get("payload", {}))

    async def send_json(self, data):
        await self.send(text_data=json.dumps(data))
