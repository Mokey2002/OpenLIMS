"""Complete-match result-filter grammar shared by initial queries and follow-ups."""
import re
from datetime import date, timedelta

from django.utils import timezone

PERIOD = r"today|yesterday|last week|this week|last 7 days"
IDENTIFIER = r"[\w.@+:/-]{1,128}"
KEY = r"[\w.:/-]{1,64}"
WEEKDAYS = "monday tuesday wednesday thursday friday saturday sunday".split()


def parse_filters(text):
    remaining, filters = text.strip(), {}
    patterns = [
        ("dates", r"from (\d{4}-\d{2}-\d{2}) (?:until|before) (\d{4}-\d{2}-\d{2})"),
        ("since", r"since (\d{4}-\d{2}-\d{2}|" + "|".join(WEEKDAYS) + r")"),
        ("instrument", rf"(?:only |from |on )?instrument ({IDENTIFIER})"),
        ("operator", rf"(?:only |by )?operator ({IDENTIFIER})"),
        ("exclude_keys", rf"(?:exclude|excluding|except|without) (?:the )?(?:result )?keys? ({KEY}(?:\s*,\s*{KEY})*)"),
        ("keys", rf"only (?:the )?(?:result )?keys? ({KEY}(?:\s*,\s*{KEY})*)"),
        ("qc", r"only (failed|passed|pending|rejected|approved|all)(?: QC)?(?: (?:ones|results|checks))?"),
        ("period", rf"(?:only from |only |from |for )?({PERIOD})"),
    ]
    while remaining:
        for kind, pattern in patterns:
            match = re.match(r"(?:" + pattern + r")(?=\s|$)", remaining, re.I)
            if not match:
                continue
            values = {}
            if kind == "dates":
                values = {"created_from": match[1], "created_before": match[2]}
            elif kind == "since":
                today = timezone.localdate()
                value = match[1].lower()
                start = today - timedelta(days=(today.weekday() - WEEKDAYS.index(value)) % 7) if value in WEEKDAYS else date.fromisoformat(value)
                values = {"created_from": start.isoformat(), "created_before": (today + timedelta(days=1)).isoformat()}
            elif kind in {"keys", "exclude_keys"}:
                values[kind] = [value.strip() for value in match[1].split(",")]
            elif kind in {"period", "qc"}:
                values[kind] = match[1].lower().replace(" ", "_")
            else:
                values[kind] = match[1]
            if filters.keys() & values.keys():
                return None
            filters.update(values)
            remaining = remaining[match.end():].strip()
            if remaining.lower().startswith("and "):
                remaining = remaining[4:].strip()
                if not remaining:
                    return None
            break
        else:
            return None
    return filters
