import asyncio
import json
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from asgiref.sync import async_to_sync
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from assistant.chat_progress import ChatCancelled, emit, progress_scope, stream_answer
from assistant.llm import call_ollama, call_openai
from assistant.models import AssistantChatRequest


class ProviderStreamingTests(SimpleTestCase):
    def test_openai_deltas_are_streamed_and_stream_is_closed(self):
        client = MagicMock()
        stream = client.with_options.return_value.responses.create.return_value
        stream.__enter__.return_value = iter([SimpleNamespace(type="response.output_text.delta", delta="Hello "),
                                              SimpleNamespace(type="response.output_text.delta", delta="world"),
                                              SimpleNamespace(type="response.completed")])
        events = []
        with patch("assistant.llm.OpenAI", return_value=client), progress_scope(lambda kind, data: events.append((kind, data))), stream_answer(True):
            self.assertEqual(call_openai("Question"), "Hello world")
        self.assertEqual([data["text"] for kind, data in events if kind == "delta"], ["Hello ", "world"])
        stream.__exit__.assert_called_once()
        client.close.assert_called_once()

    def test_openai_partial_stream_without_completion_event_is_not_accepted(self):
        client = MagicMock()
        stream = client.with_options.return_value.responses.create.return_value
        stream.__enter__.return_value = iter([SimpleNamespace(type="response.output_text.delta", delta="Unfinished")])
        with patch("assistant.llm.OpenAI", return_value=client), progress_scope(lambda kind, data: None), stream_answer(True):
            with self.assertRaises(ValueError):
                call_openai("Question")
        stream.__exit__.assert_called_once()
        client.close.assert_called_once()

    def test_ollama_stream_and_cancellation_do_not_become_successful_fallback_answers(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.__iter__.return_value = iter([json.dumps({"message": {"content": "First "}}).encode(),
                                              json.dumps({"message": {"content": "second"}, "done": True}).encode()])
        with patch("assistant.llm.urllib.request.urlopen", return_value=response), progress_scope(lambda kind, data: None), stream_answer(True):
            self.assertEqual(call_ollama("Question"), "First second")
        response.__iter__.return_value = iter([json.dumps({"message": {"content": "Stop"}}).encode()])
        def cancelled(kind, data):
            raise ChatCancelled()
        with patch("assistant.llm.urllib.request.urlopen", return_value=response), progress_scope(cancelled), stream_answer(True):
            with self.assertRaises(ChatCancelled):
                call_ollama("Question")
        self.assertEqual(response.__exit__.call_count, 2)


class ChatStreamingTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="stream-owner")
        self.other = get_user_model().objects.create_user(username="stream-other")
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def consume(self, response):
        async def read():
            return "".join([(chunk.decode() if isinstance(chunk, bytes) else chunk) async for chunk in response.streaming_content])
        return async_to_sync(read)()

    def test_stream_reports_real_progress_and_a_complete_reply(self):
        request_id = uuid.uuid4()
        response = self.client.post("/api/assistant/chat/stream/", {"request_id": str(request_id), "message": "Who am I?"}, format="json")
        self.assertEqual(response.status_code, 200)
        body = self.consume(response)
        self.assertIn("event: progress", body)
        self.assertIn("event: complete", body)
        self.assertIn("stream-owner", body)
        self.assertEqual(response["X-Accel-Buffering"], "no")
        self.assertEqual(AssistantChatRequest.objects.get(pk=request_id).status, "COMPLETED")
        duplicate = self.client.post("/api/assistant/chat/stream/", {"request_id": str(request_id), "message": "Who am I?"}, format="json")
        self.assertEqual(duplicate.status_code, 409)

    def test_cancel_is_owner_only_and_prevents_later_steps(self):
        started, later_step = threading.Event(), threading.Event()
        def blocked(view, request):
            started.set()
            for _ in range(200):
                emit("checkpoint")
                threading.Event().wait(.01)
            later_step.set()
            raise AssertionError("Cancellation should have interrupted the request.")
        request_id = uuid.uuid4()
        with patch("assistant.streaming.AssistantChatView.post", new=blocked):
            response = self.client.post("/api/assistant/chat/stream/", {"request_id": str(request_id), "message": "Read records"}, format="json")
            self.assertTrue(started.wait(3))
            self.client.force_authenticate(self.other)
            self.assertEqual(self.client.post(f"/api/assistant/chat/requests/{request_id}/cancel/", {}, format="json").status_code, 404)
            self.client.force_authenticate(self.user)
            self.assertEqual(self.client.post(f"/api/assistant/chat/requests/{request_id}/cancel/", {}, format="json").status_code, 200)
            body = self.consume(response)
        self.assertIn("event: cancelled", body)
        self.assertNotIn("event: complete", body)
        self.assertFalse(later_step.is_set())
        self.assertEqual(AssistantChatRequest.objects.get(pk=request_id).status, "CANCELLED")

    def test_unauthenticated_stream_and_foreign_saved_chat_are_rejected_before_worker_start(self):
        self.client.force_authenticate(None)
        response = self.client.post("/api/assistant/chat/stream/", {"request_id": str(uuid.uuid4()), "message": "Who am I?"}, format="json")
        self.assertIn(response.status_code, [401, 403])
        self.assertEqual(AssistantChatRequest.objects.count(), 0)

    def test_stop_before_stream_claim_prevents_any_execution(self):
        request_id = uuid.uuid4()
        self.assertEqual(self.client.post(f"/api/assistant/chat/requests/{request_id}/cancel/", {}, format="json").status_code, 200)
        with patch("assistant.streaming.POOL.submit") as submit:
            reply = self.client.post("/api/assistant/chat/stream/", {"request_id": str(request_id), "message": "Who am I?"}, format="json")
        self.assertEqual(reply.status_code, 409)
        submit.assert_not_called()

    def test_cleanup_removes_expired_state_and_stops_stale_requests_without_touching_recent_ones(self):
        import io
        from datetime import timedelta
        from django.core.management import call_command
        from django.utils import timezone
        old = AssistantChatRequest.objects.create(owner=self.user, status="COMPLETED")
        stale = AssistantChatRequest.objects.create(owner=self.user)
        recent = AssistantChatRequest.objects.create(owner=self.user)
        AssistantChatRequest.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=8))
        AssistantChatRequest.objects.filter(pk=stale.pk).update(created_at=timezone.now() - timedelta(hours=2))
        call_command("cleanup_assistant_requests", stdout=io.StringIO())
        self.assertFalse(AssistantChatRequest.objects.filter(pk=old.pk).exists())
        stale.refresh_from_db()
        recent.refresh_from_db()
        self.assertEqual(stale.status, "CANCELLED")
        self.assertTrue(stale.cancel_requested)
        self.assertEqual(recent.status, "RUNNING")
