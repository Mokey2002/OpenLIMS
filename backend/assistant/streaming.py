"""SSE chat transport with bounded workers and cross-process cancellation."""
import asyncio
import json
import logging
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema

from .chat_progress import ChatCancelled, progress_scope
from .models import AssistantChatRequest
from .views import AssistantChatSerializer, AssistantChatView

logger = logging.getLogger(__name__)
POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="assistant-chat")
SLOTS = threading.BoundedSemaphore(8)
POOL_PID = os.getpid()


def _process_pool():
    # A prefork server/test process must not reuse vanished parent threads.
    global POOL, SLOTS, POOL_PID
    if POOL_PID != os.getpid():
        POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="assistant-chat")
        SLOTS = threading.BoundedSemaphore(8)
        POOL_PID = os.getpid()


class StreamChatSerializer(AssistantChatSerializer):
    request_id = serializers.UUIDField()


def _cancel(request_id, owner_id):
    close_old_connections()
    try:
        AssistantChatRequest.objects.filter(pk=request_id, owner_id=owner_id, status="RUNNING").update(cancel_requested=True)
    finally:
        close_old_connections()


def _worker(data, owner_id, request_id, events, stopped):
    close_old_connections()
    last_check = 0
    def callback(kind, payload):
        nonlocal last_check
        if stopped.is_set():
            raise ChatCancelled()
        now = time.monotonic()
        if now - last_check > .15 or kind == "checkpoint":
            if not AssistantChatRequest.objects.filter(pk=request_id, owner_id=owner_id, cancel_requested=False, status="RUNNING").exists():
                raise ChatCancelled()
            last_check = now
        if kind != "checkpoint":
            try:
                events.put((kind, payload), timeout=1)
            except queue.Full as exc:
                raise ChatCancelled() from exc
    terminal, terminal_event = "FAILED", ("error", {"message": "The request could not be completed. Please retry."})
    try:
        user = get_user_model().objects.get(pk=owner_id, is_active=True)
        with progress_scope(callback):
            callback("checkpoint", {})
            reply = AssistantChatView().post(SimpleNamespace(data=data, user=user))
            callback("checkpoint", {})
        if reply.status_code >= 400:
            raise ValueError("Chat request could not be completed.")
        terminal_event = ("complete", reply.data)
        terminal = "COMPLETED"
    except ChatCancelled:
        terminal = "CANCELLED"
        terminal_event = ("cancelled", {"message": "Request stopped."})
    except Exception:
        logger.exception("Assistant streamed request failed")
    finally:
        try:
            AssistantChatRequest.objects.filter(pk=request_id, owner_id=owner_id).update(status=terminal, finished_at=timezone.now())
        finally:
            close_old_connections()
            SLOTS.release()
    try:
        events.put(terminal_event, timeout=1)
    except queue.Full:
        pass


class AssistantChatStreamView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=StreamChatSerializer, responses={(200, "text/event-stream"): OpenApiTypes.STR})
    def post(self, request):
        _process_pool()
        serializer = StreamChatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        request_id = data.pop("request_id")
        conversation_id = data.get("conversation_id")
        if conversation_id:
            from .models import AssistantConversation
            get_object_or_404(AssistantConversation, pk=conversation_id, owner=request.user)
        if not SLOTS.acquire(blocking=False):
            return Response({"detail": "The assistant is busy. Please retry shortly."}, status=429)
        try:
            run, created = AssistantChatRequest.objects.get_or_create(pk=request_id, defaults={"owner": request.user})
            if not created:
                SLOTS.release()
                return Response({"detail": "This request ID has already been used. Start a new request."}, status=409)
            events, stopped = queue.Queue(maxsize=256), threading.Event()
            future = POOL.submit(_worker, data, request.user.pk, request_id, events, stopped)
        except Exception:
            SLOTS.release()
            raise

        async def stream():
            completed = False
            try:
                yield "event: started\ndata: " + json.dumps({"request_id": str(request_id)}) + "\n\n"
                while not future.done() or not events.empty():
                    try:
                        kind, payload = await asyncio.to_thread(events.get, True, .25)
                    except queue.Empty:
                        continue
                    yield f"event: {kind}\ndata: {json.dumps(payload, default=str)}\n\n"
                    if kind in {"complete", "cancelled", "error"}:
                        completed = True
                        break
            finally:
                if not completed:
                    stopped.set()
                    await asyncio.to_thread(_cancel, request_id, request.user.pk)
        response = StreamingHttpResponse(stream(), content_type="text/event-stream")
        response["Cache-Control"] = "no-cache, no-store"
        response["X-Accel-Buffering"] = "no"
        return response


class AssistantChatCancelView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses=OpenApiTypes.OBJECT)
    def post(self, request, pk):
        # Register an early Stop even if the corresponding stream has not yet
        # claimed its ID. Other users' existing IDs remain inaccessible.
        run, created = AssistantChatRequest.objects.get_or_create(pk=pk, defaults={
            "owner": request.user, "status": "CANCELLED", "cancel_requested": True, "finished_at": timezone.now()})
        if run.owner_id != request.user.pk:
            from django.http import Http404
            raise Http404()
        AssistantChatRequest.objects.filter(pk=run.pk, owner=request.user, status="RUNNING").update(cancel_requested=True)
        return Response({"request_id": str(pk), "status": "stop_requested" if run.status == "RUNNING" else run.status.lower()})
