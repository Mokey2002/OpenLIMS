"""Real HTTP/ASGI smoke test, separate from browser response mocks."""
import json
import html
import re
import uuid
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from channels.testing import ChannelsLiveServerTestCase
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import override_settings
from django.conf import settings
from django.db import connections
from rest_framework_simplejwt.tokens import AccessToken

from projects.models import Project
from samples.models import Sample
from results.models import WorkItem, Result


@override_settings(DEBUG=True, SECRET_KEY="live-http-test-secret-key-longer-than-thirty-two-characters")
class AssistantLiveHTTPTests(ChannelsLiveServerTestCase):
    serve_static = False

    @classmethod
    def setUpClass(cls):
        # pytest-django has already selected the test database. Tell Channels
        # its explicit name so the child does not add a second "test_" prefix.
        cls._test_name = settings.DATABASES["default"]["TEST"].get("NAME")
        settings.DATABASES["default"]["TEST"]["NAME"] = connections["default"].settings_dict["NAME"]
        try:
            super().setUpClass()
        except Exception:
            settings.DATABASES["default"]["TEST"]["NAME"] = cls._test_name
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            settings.DATABASES["default"]["TEST"]["NAME"] = cls._test_name

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="live-chat-owner")
        self.user.groups.add(Group.objects.get_or_create(name="tech")[0])
        self.project = Project.objects.create(code="LIVE-CHAT", name="Live chat test")
        self.project.members.add(self.user)
        sample = Sample.objects.create(sample_id="LIVE-CHAT-1", project=self.project, created_by=self.user)
        work = WorkItem.objects.create(sample=sample, name="Live HTTP test")
        self.result = Result.objects.create(work_item=work, key="concentration", value_type="NUMBER", value_number=45, qc_passed=False)
        self.token = str(AccessToken.for_user(self.user))
        self.opener = build_opener(ProxyHandler({}))

    def http(self, path, data=None):
        request = Request(self.live_server_url + path, data=json.dumps(data).encode() if data is not None else None,
                          headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        try:
            return self.opener.open(request, timeout=15)
        except HTTPError as error:
            if error.code != 500:
                raise
            body = error.read().decode()
            values = re.findall(r'<pre class="exception_value">(.*?)</pre>', body, re.S)
            raise AssertionError("HTTP 500: " + html.unescape(" ".join(values))[:1000]) from error

    def test_real_http_stream_filters_save_and_permission_refresh(self):
        with self.http("/api/v1/assistant/chat/stream/", {"message": "Show QC failures for project LIVE-CHAT", "request_id": str(uuid.uuid4())}) as response:
            self.assertIn("text/event-stream", response.headers["Content-Type"])
            text = response.read().decode()
        self.assertLess(text.index("event: progress"), text.index("event: complete"))
        complete = text.split("event: complete\ndata: ", 1)[1].split("\n\n", 1)[0]
        reply = json.loads(complete)
        self.assertEqual(reply["read_plan"]["steps"][0]["result_query"]["total"], 1)
        self.assertIn("45.0", reply["answer"])
        with self.http("/api/v1/assistant/conversations/", {"name": "Real HTTP review", "turn_tokens": [reply["save_turn_token"]]}) as response:
            conversation_id = json.load(response)["id"]
        Result.objects.filter(pk=self.result.pk).update(value_number=17)
        with self.http(f"/api/v1/assistant/conversations/{conversation_id}/") as response:
            restored = json.load(response)
        self.assertIn("17.0", restored["history"][1]["reply"]["answer"])
        self.project.members.remove(self.user)
        with self.http(f"/api/v1/assistant/conversations/{conversation_id}/") as response:
            denied = json.load(response)
        self.assertNotIn("17.0", str(denied))
        request_id = str(uuid.uuid4())
        with self.http(f"/api/v1/assistant/chat/requests/{request_id}/cancel/", {}):
            pass
        with self.assertRaises(HTTPError) as error:
            self.http("/api/v1/assistant/chat/stream/", {"message": "Who am I?", "request_id": request_id})
        self.assertEqual(error.exception.code, 409)
