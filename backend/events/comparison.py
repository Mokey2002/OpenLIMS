"""Field comparisons use recorded snapshots, never current record names."""
import re

from .presentation import humanize

TECHNICAL = {"id", "public_id", "checksum", "created_at", "updated_at", "schema_version",
             "password", "token", "confirmation_token", "idempotency_key", "labels"}
REFERENCES = {"location", "container", "project", "parent", "batch", "assigned_to", "custodian", "owner", "assignee"}
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f-]{27}$", re.I)


def mapping(value):
    return value if isinstance(value, dict) else {}


def display_value(snapshot, field, labels):
    value = snapshot.get(field)
    if field in labels:
        return labels[field], False
    base = field.removesuffix("_id")
    if base in REFERENCES:
        for suffix in ("_label", "_name", "_code", "_username"):
            if snapshot.get(base + suffix) is not None:
                return snapshot[base + suffix], False
        if isinstance(value, dict):
            for key in ("label", "name", "code", "username"):
                if key in value:
                    return value[key], False
        if value is not None and (isinstance(value, int) or UUID.fullmatch(str(value))):
            return "Historical name not recorded", True
    return value, False


def field_changes(event):
    payload = mapping(event.payload)
    before, after = mapping(payload.get("before")), mapping(payload.get("after"))
    old_labels, new_labels = mapping(payload.get("display_before")), mapping(payload.get("display_after"))
    keys = payload.get("changed_fields")
    if not isinstance(keys, list):
        keys = sorted(set(before) | set(after))
    keys = [key for key in keys if isinstance(key, str) and key not in TECHNICAL]
    # Name/code fields supplement the corresponding reference rather than
    # presenting the same location/container movement twice.
    companions = {key.removesuffix("_id") + suffix for key in keys
                  for suffix in ("_label", "_name", "_code", "_username")}
    changes = []
    for key in dict.fromkeys(keys):
        if key in companions or (key in before and key in after and before[key] == after[key]):
            continue
        old, missing_old = display_value(before, key, old_labels)
        new, missing_new = display_value(after, key, new_labels)
        changes.append({"field": key, "label": humanize(key.removesuffix("_id")),
                        "before": old, "after": new, "before_present": key in before,
                        "after_present": key in after, "historical_name_missing": missing_old or missing_new})
    if "location" in old_labels or "location" in new_labels:
        if old_labels.get("location") != new_labels.get("location") and not any(row["field"] in {"location", "location_id"} for row in changes):
            changes.append({"field": "location", "label": "Location", "before": old_labels.get("location"),
                            "after": new_labels.get("location"), "before_present": True, "after_present": True,
                            "historical_name_missing": False})
    return changes


def can_compare_revision(event):
    payload = mapping(event.payload)
    number = mapping(payload.get("after")).get("revision")
    return (str(event.entity_type).lower() == "experiment"
            and event.action in {"EXPERIMENT_REVISION_CREATED", "DRAFT_CREATED_FROM_RUN"}
            and type(number) is int and number > 0)
