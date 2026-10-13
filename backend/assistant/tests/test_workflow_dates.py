from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from assistant.workflow_dates import deadline_windows
from assistant.workflow_query import parse_filters, normalize_deadline_phrases


@pytest.mark.parametrize("phrase,mode", [
    ("due today", "due_today"), ("due tomorrow", "due_tomorrow"),
    ("due within 7 days", "due_soon"), ("due in the next 7 days", "due_soon"),
    ("vencen hoy", "due_today"), ("vencen mañana", "due_tomorrow"),
    ("vencen en los próximos 7 días", "due_soon"),
])
def test_deadline_phrases_are_bounded(phrase, mode):
    assert parse_filters(phrase) == ([mode], "all", None)
    assert parse_filters(f"{phrase} and unassigned") == ([mode, "unassigned"], "all", None)


@pytest.mark.parametrize("phrase", [
    "due today at 3pm", "due tomorrow before noon", "due within 7 days but not overdue",
    "due today or tomorrow", "due today in PST", "due today and due in 3 days",
])
def test_unsupported_deadline_qualifiers_are_not_ignored(phrase):
    assert parse_filters(phrase)[2]


def test_calendar_windows_handle_dst_and_rolling_window_is_168_hours():
    for month, day, hours in [(3, 8, 23), (11, 1, 25)]:
        with timezone.override("America/Los_Angeles"):
            now = datetime(2026, month, day, 1, tzinfo=ZoneInfo("America/Los_Angeles"))
            windows = deadline_windows(now, ["due_today", "due_tomorrow", "due_soon"])
            start, end = windows["due_today"]
            assert (end.astimezone(dt_timezone.utc) - start.astimezone(dt_timezone.utc)) == timedelta(hours=hours)
            assert windows["due_tomorrow"][0] == end
            assert windows["due_soon"][1] - windows["due_soon"][0] == timedelta(hours=168)


def test_deadline_in_phrase_is_protected_from_project_parsing():
    assert normalize_deadline_phrases("samples in project P due in the next 7 days") == "samples in project P due soon"
    assert normalize_deadline_phrases("muestras en proyecto P vencen en los próximos 7 días") == "muestras en proyecto P vencen pronto"
