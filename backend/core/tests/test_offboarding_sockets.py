from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase, override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from config.asgi import application

User = get_user_model()


@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class OffboardingSocketTests(TransactionTestCase):
    def test_offboarding_closes_open_sockets_and_old_tokens_cannot_reconnect_after_reactivation(self):
        admin = User.objects.create_superuser("socket-director", password=None)
        target = User.objects.create_user("socket-departure", password=None)
        access = str(RefreshToken.for_user(target).access_token)
        client = APIClient()
        client.force_authenticate(admin)
        base = f"/api/admin-users/{target.pk}/offboarding"
        preview = client.post(base + "/preview/", {"reason": "Reviewed departure for websocket test"}, format="json")
        self.assertEqual(preview.status_code, 201, preview.data)

        @database_sync_to_async
        def offboard():
            response = client.post(base + "/confirm/", {"preview_id": preview.data["preview_id"], "confirmed": True}, format="json")
            self.assertEqual(response.status_code, 200, response.data)

        @database_sync_to_async
        def reactivate():
            User.objects.filter(pk=target.pk).update(is_active=True)

        async def scenario():
            communicator = WebsocketCommunicator(application, f"/ws/jobs/?token={access}")
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            self.assertEqual((await communicator.receive_json_from())["type"], "connection_ack")
            await offboard()
            output = await communicator.receive_output(timeout=3)
            self.assertEqual(output, {"type": "websocket.close", "code": 4001})
            await communicator.disconnect()
            await reactivate()
            rejected = WebsocketCommunicator(application, f"/ws/jobs/?token={access}")
            connected, code = await rejected.connect()
            self.assertFalse(connected)
            self.assertEqual(code, 4001)
            await rejected.disconnect()

        async_to_sync(scenario)()
