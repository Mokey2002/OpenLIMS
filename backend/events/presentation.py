"""Readable descriptions from the already-authorized audit snapshot, without lookups."""
import json
import re


ACTION_LABELS = {
    "EXPERIMENT_REVISION_CREATED": "Experiment saved",
    "DRAFT_CREATED_FROM_RUN": "Experiment draft created",
    "ASSISTANT_ACTION_PROPOSED": "Assistant action proposed",
    "ASSISTANT_ACTION_CONFIRMED": "Assistant action confirmed",
    "ASSISTANT_ACTION_COMPLETED": "Assistant task completed",
    "ASSISTANT_ACTION_FAILED": "Assistant action failed",
}


def humanize(value):
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(value or "")).replace("_", " ").strip().capitalize()


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _text(value):
    return " ".join(value.split())[:500] if isinstance(value, str) else ""


def _value(value):
    if value is None:
        return "not set"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)[:160]
    return str(value)[:160]


def event_presentation(event):
    payload = _mapping(event.payload)
    before, after = _mapping(payload.get("before")), _mapping(payload.get("after"))
    reference = _mapping(payload.get("entity"))
    kind = str(event.entity_type or "").replace("_", "").lower()
    fields = {
        "container": ("container_id", "name"), "location": ("name", "code"),
        "sample": ("sample_code", "sample_id"), "project": ("code", "name", "project_code"),
        "experiment": ("title",), "notebook": ("name",), "user": ("username",),
        "assistantaction": ("summary", "action_type"),
    }.get(kind, ("name", "title", "code", "sample_code", "run_id"))
    entity_label = _text(reference.get("label"))
    if not entity_label:
        entity_label = next((label for snapshot in [payload, after, before] for key in fields
                             if (label := _text(snapshot.get(key)))), "")
    if kind == "assistantaction" and entity_label == payload.get("action_type"):
        entity_label = humanize(entity_label)
    entity_label = entity_label or f"{humanize(event.entity_type) or 'Record'} (name unavailable)"
    action_label = ACTION_LABELS.get(event.action, humanize(event.action))
    source = "Assistant" if kind == "assistantaction" or payload.get("assistant_action_id") else "Application"
    if source == "Application" and _text(payload.get("reason")) in {"Autosave", "Notebook autosave"}:
        source = "Notebook autosave"
    description = f"{action_label}: {entity_label}"
    revision = after.get("revision")
    if isinstance(revision, int) and not isinstance(revision, bool):
        previous = before.get("revision")
        description = f"Revision {previous} → {revision}" if isinstance(previous, int) and not isinstance(previous, bool) else f"Initial revision {revision}"
        changes = _mapping(_mapping(payload.get("details")).get("changes"))
        counts = [f"{value} {key.replace('_', ' ') if value != 1 else key.replace('_', ' ').replace('blocks', 'block').replace('links', 'link')}" for key, value in changes.items()
                  if key in {f"{kind}_{action}" for kind in ["blocks", "links"] for action in ["added", "removed", "modified"]}
                  and isinstance(value, int) and not isinstance(value, bool) and value > 0]
        if counts:
            description += "; " + ", ".join(counts)
    elif isinstance(payload.get("changed_fields"), list):
        changes = [f"{humanize(field)}: {_value(before.get(field))} → {_value(after.get(field))}"
                   for field in payload["changed_fields"] if isinstance(field, str)][:20]
        if changes:
            description = "; ".join(changes)
    elif kind == "assistantaction":
        description = _text(payload.get("summary")) or _text(_mapping(payload.get("result")).get("message")) or action_label
    return {"entity_label": entity_label, "action_label": action_label, "description": description, "source": source}


def spreadsheet_text(value):
    """Keep snapshot names as text when a spreadsheet opens the CSV export."""
    text = str(value or "")
    return "'" + text if re.match(r"^[\s\ufeff]*[=+\-@]", text) else text
