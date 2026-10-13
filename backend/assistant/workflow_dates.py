"""Server-resolved deadline windows; never trust dates from chat context."""
from datetime import timedelta, timezone as datetime_timezone

from django.utils import timezone


DEADLINE_LABELS = {
    "due_today": ("due today", "vencen hoy"),
    "due_tomorrow": ("due tomorrow", "vencen mañana"),
    "due_soon": ("due within 7 days", "vencen en los próximos 7 días"),
}


def deadline_windows(now, filters):
    """Half-open calendar days in the active Django timezone, or next 168h."""
    local = timezone.localtime(now)
    today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    utc_now = now.astimezone(datetime_timezone.utc)
    windows = {
        "due_today": (today, today + timedelta(days=1)),
        "due_tomorrow": (today + timedelta(days=1), today + timedelta(days=2)),
        "due_soon": (utc_now, utc_now + timedelta(days=7)),
    }
    return {key: windows[key] for key in filters if key in windows}


def describe_deadlines(windows, spanish):
    zone = timezone.get_current_timezone_name()
    records = []
    for mode, (start, end) in windows.items():
        records.append({"filter": mode, "start": start.isoformat(), "end": end.isoformat(),
                        "timezone": zone, "start_inclusive": True, "end_exclusive": True})
    details = "; ".join(
        f"{DEADLINE_LABELS[mode][int(spanish)]}: {timezone.localtime(start).isoformat()} ≤ due < {timezone.localtime(end).isoformat()}"
        for mode, (start, end) in windows.items())
    if spanish:
        text = f"Ventanas de vencimiento ({zone}): {details}. Hoy/mañana usan días de esta zona, no la zona del navegador. Los próximos 7 días son 168 horas desde esta consulta. Solo trabajo activo disponible; no es una previsión de finalización."
    else:
        text = f"Due-date windows ({zone}): {details}. Today/tomorrow use calendar days in this timezone, not the browser timezone. The next 7 days are 168 hours from this request. Active available work only; this is not a completion forecast."
    return records, text
