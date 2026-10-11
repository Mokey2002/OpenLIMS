import pytest

from assistant.workflow_query import context_filters, parse_filters


@pytest.mark.parametrize("text,modes,match", [
    ("Which samples are overdue and unassigned?", ["overdue", "unassigned"], "all"),
    ("Which samples are overdue or unassigned?", ["overdue", "unassigned"], "any"),
    ("Which samples failed QC or are missing results?", ["qc_failed", "missing"], "any"),
    ("¿Qué muestras están vencidas y sin asignar?", ["overdue", "unassigned"], "all"),
    ("muestras con QC rechazado o campos faltantes", ["qc_failed", "missing"], "any"),
    ("Also unassigned", ["unassigned"], "all"),
    ("También sin asignar", ["unassigned"], "all"),
    ("blocked, and why?", ["blocked"], "all"),
    ("Show samples workflow overview", ["all"], "all"),
    ("overdue and overdue", ["overdue"], "all"),
])
def test_supported_expressions(text, modes, match):
    assert parse_filters(text) == (modes, match, None)


@pytest.mark.parametrize("text", [
    "not overdue", "no están listas", "overdue but not unassigned",
    "overdue and unassigned or missing results", "overdue or unassigned and ready",
    "overdue, unassigned", "overdue within 7 days", "overdue assigned to maria",
    "overdue and concentration > 43", "overdue and (unassigned or ready)",
    "listas sin QC", "overdue and bananas", "workflow and overdue",
    "overdue and unassigned on the same step",
    "overdue or", "overdue and", "or overdue", "vencidas o",
    "both overdue or unassigned", "either overdue and unassigned",
])
def test_unsupported_conditions_are_not_silently_ignored(text):
    assert parse_filters(text)[2]


@pytest.mark.parametrize("state", [
    {}, {"filters": []}, {"filters": "overdue"}, {"filters": [None]},
    {"filters": [{}]}, {"filters": ["secret"]}, {"filters": ["overdue"] * 9},
    {"filters": ["overdue"], "match": []}, {"filters": ["overdue"], "match": "none"},
    {"filters": ["all", "overdue"]},
])
def test_invalid_client_context_fails_closed(state):
    assert context_filters(state)[2] == "context"


def test_legacy_context_still_supported():
    assert context_filters({"filter": "overdue"}) == (["overdue"], "all", None)


def test_and_is_sample_level_with_evidence_from_separate_steps():
    from assistant.project_workflows import _match_reasons
    evidence = [{"kind": "overdue", "step": 1}, {"kind": "unassigned", "step": 2}]
    assert _match_reasons(evidence, ["overdue", "unassigned"], "all") == (True, evidence)
    assert _match_reasons(evidence[:1], ["overdue", "unassigned"], "all")[0] is False
    assert _match_reasons(evidence[:1], ["overdue", "unassigned"], "any")[0] is True
