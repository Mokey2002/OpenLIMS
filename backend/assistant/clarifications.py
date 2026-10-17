import re

from .intent_matching import compact_command_text, normalize_intent_text


def _normalize(message):
    return normalize_intent_text(message)


def _is_bare_request(message, subjects):
    compact = compact_command_text(message)
    verbs = ["show", "list", "find", "which", "tell"]
    return compact in {
        f"{verb} {subject}"
        for verb in verbs
        for subject in subjects
    }


def _option(option_id, label, message, description):
    return {
        "id": option_id,
        "label": label,
        "message": message,
        "description": description,
    }


def _response(topic, question, options, context):
    return {
        "answer": question,
        "clarification": {
            "topic": topic,
            "question": question,
            "options": options,
        },
        "links": [],
        "suggestions": [],
        "context": {**dict(context or {}), "clarification_topic": topic},
        "skip_llm": True,
    }


# Rebuild choices from server-owned read commands; never replay client commands.
CHOICE_REQUESTS = {
    "qc_samples": "show qc samples", "qc_results": "show qc results",
    "sample_scope": "show samples", "result_scope": "show results",
    "failure_domain": "show failures", "inventory_scope": "show inventory",
}


def resume_clarification(message, context):
    topic = context.get("clarification_topic")
    if not isinstance(topic, str) or topic not in CHOICE_REQUESTS:
        return None, None
    text = _normalize(message)
    if text in {"cancel", "never mind", "start over", "forget that"}:
        return None, {"answer": "Okay, let's start fresh. What would you like to check?",
                      "context": {}, "replace_context": True, "skip_llm": True}
    question = route_assistant_clarification(CHOICE_REQUESTS[topic], context)
    options = question["clarification"]["options"]
    ordinals = ["first", "second", "third", "fourth"]
    for index, option in enumerate(options):
        labels = {_normalize(option["id"]), _normalize(option["label"]), str(index + 1),
                  f"option {index + 1}"}
        if index < len(ordinals):
            labels.update({ordinals[index], f"the {ordinals[index]} one"})
        if text in labels:
            return option["message"], None
    if text in {"yes", "no", "that one", "which ones", "not sure"} or text.isdigit():
        question["answer"] = "Which option do you mean? Reply with its name or number."
        return None, question
    return None, None


def _qc_scope_is_explicit(lower):
    return bool(
        re.search(
            r"\b(?:need|needs|needing|awaiting|waiting|pending|review|approval|"
            r"fail|failed|failing|failure|failures|passed|approved|rejected|"
            r"investigate|investigation|root cause|workflow|status)\b",
            lower,
        )
        or re.search(r"\b(?:in|at)\s+qc\b", lower)
        or re.search(
            r"\b(?:compare|graph|plot|chart|trend|rate|outlier|outliers|unusual)\b",
            lower,
        )
    )


def _qc_sample_clarification(lower, context):
    if not re.search(r"\bsamples?\b", lower):
        return None
    if not re.search(r"\b(?:qc|quality control)\b", lower):
        return None
    if _qc_scope_is_explicit(lower):
        return None
    return _response(
        "qc_samples",
        "Which QC sample group do you want to see?",
        [
            _option(
                "awaiting_review",
                "Awaiting QC review",
                "Show samples with results awaiting QC review",
                "Samples with pending or reopened results that require review.",
            ),
            _option(
                "failed_qc",
                "Failed QC",
                "Show samples that failed QC",
                "Samples with one or more recorded QC failures.",
            ),
            _option(
                "workflow_qc",
                "In QC workflow",
                "Show samples in QC",
                "Samples whose current workflow status is QC.",
            ),
        ],
        context,
    )


def _qc_result_clarification(lower, context):
    if not re.search(r"\bresults?\b", lower):
        return None
    if not re.search(r"\b(?:qc|quality control)\b", lower):
        return None
    if _qc_scope_is_explicit(lower):
        return None
    return _response(
        "qc_results",
        "Which QC result group do you want to see?",
        [
            _option(
                "awaiting_review",
                "Awaiting QC review",
                "Show results awaiting QC review",
                "Pending or reopened results that require a reviewer decision.",
            ),
            _option(
                "failed_qc",
                "Failed QC",
                "Show results that failed QC",
                "Results with a recorded failed QC evaluation.",
            ),
            _option(
                "approved",
                "Approved",
                "Show approved results",
                "Results that completed QC review and were approved.",
            ),
        ],
        context,
    )


def _bare_sample_clarification(lower, context):
    if not _is_bare_request(lower, ["sample", "samples"]):
        return None
    return _response(
        "sample_scope",
        "Which samples do you want to see?",
        [
            _option(
                "received_today",
                "Received today",
                "Show samples received today",
                "Samples received during the current local day.",
            ),
            _option(
                "awaiting_qc",
                "Awaiting QC review",
                "Show samples with results awaiting QC review",
                "Samples with results that still require QC review.",
            ),
            _option(
                "failed_qc",
                "Failed QC",
                "Show samples that failed QC",
                "Samples with one or more failed QC results.",
            ),
            _option(
                "workflow_qc",
                "In QC workflow",
                "Show samples in QC",
                "Samples whose current workflow status is QC.",
            ),
        ],
        context,
    )


def _bare_result_clarification(lower, context):
    if not _is_bare_request(lower, ["result", "results"]):
        return None
    return _response(
        "result_scope",
        "Which results do you want to see?",
        [
            _option(
                "awaiting_review",
                "Awaiting QC review",
                "Show results awaiting QC review",
                "Pending or reopened results that require review.",
            ),
            _option(
                "failed_qc",
                "Failed QC",
                "Show results that failed QC",
                "Results with a failed QC evaluation.",
            ),
            _option(
                "approved",
                "Approved",
                "Show approved results",
                "Results that completed QC review and were approved.",
            ),
        ],
        context,
    )


def _bare_failure_clarification(lower, context):
    if not _is_bare_request(lower, ["failed", "failures", "errors"]):
        return None
    return _response(
        "failure_domain",
        "Which type of failure do you want to review?",
        [
            _option(
                "qc_failures",
                "QC failures",
                "Show results that failed QC",
                "Laboratory results with failed QC evaluations.",
            ),
            _option(
                "failed_imports",
                "Failed imports",
                "Show failed migration jobs",
                "Migration or import jobs that ended in a failed state.",
            ),
            _option(
                "migration_errors",
                "Migration row errors",
                "Show failed migration rows",
                "Individual migration rows with recorded errors.",
            ),
        ],
        context,
    )


def _bare_inventory_clarification(lower, context):
    if not _is_bare_request(
        lower,
        [
            "inventory",
            "reagent",
            "reagents",
            "inventory item",
            "inventory items",
            "inventory lot",
            "inventory lots",
        ],
    ):
        return None
    return _response(
        "inventory_scope",
        "Which inventory view do you want to see?",
        [
            _option(
                "below_reorder",
                "Below reorder level",
                "Show inventory below its reorder level",
                "Inventory items whose available quantity is below their configured threshold.",
            ),
            _option(
                "expiring_soon",
                "Expiring soon",
                "Which reagents expire in the next 30 days?",
                "Active reagent lots that expire during the next 30 days.",
            ),
        ],
        context,
    )


def route_assistant_clarification(message, context=None):
    lower = _normalize(message)
    if not lower:
        return None
    for router in [
        _qc_sample_clarification,
        _qc_result_clarification,
        _bare_sample_clarification,
        _bare_result_clarification,
        _bare_failure_clarification,
        _bare_inventory_clarification,
    ]:
        result = router(lower, context)
        if result:
            return result
    return None
