"""Request-local progress and cooperative cancellation hooks."""
from contextlib import contextmanager
from contextvars import ContextVar

_callback = ContextVar("assistant_progress", default=None)
_answer_stream = ContextVar("assistant_answer_stream", default=False)


class ChatCancelled(Exception):
    pass


def emit(kind, **data):
    callback = _callback.get()
    if callback:
        callback(kind, data)


def check_cancelled():
    emit("checkpoint")


def answer_streaming():
    return _callback.get() is not None and _answer_stream.get()


def request_active():
    return _callback.get() is not None


@contextmanager
def progress_scope(callback):
    token = _callback.set(callback)
    try:
        yield
    finally:
        _callback.reset(token)


@contextmanager
def stream_answer(enabled):
    token = _answer_stream.set(enabled)
    try:
        yield
    finally:
        _answer_stream.reset(token)
