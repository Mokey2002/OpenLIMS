import pytest

from assistant.workflow_query import context_filters, context_scope, extract_scope, parse_filters


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


@pytest.mark.parametrize("phrase,scope", [
    ("on the same step", "step"), ("in the same step", "step"),
    ("en el mismo paso", "step"), ("across the sample", "sample"),
    ("en toda la muestra", "sample"),
])
def test_scope_extraction(phrase, scope):
    text, result, conflict = extract_scope(f"overdue and unassigned {phrase}")
    assert text == "overdue and unassigned"
    assert result == scope
    assert not conflict
    assert parse_filters(text) == (["overdue", "unassigned"], "all", None)


def test_conflicting_scope_is_not_guessed():
    assert extract_scope("on the same step across the sample")[2]
    assert context_scope({}) == "sample"
    for scope in (None, [], {}, "anything", True):
        assert context_scope({"scope": scope}) is None


def test_scoped_matching_does_not_mix_steps_or_runs():
    from assistant.project_workflows import _match_scoped_reasons
    overdue = {"kind": "overdue", "run_id": 1, "step": 1}
    other_step = {"kind": "unassigned", "run_id": 1, "step": 2}
    other_run = {"kind": "unassigned", "run_id": 2, "step": 1}
    same_step = {"kind": "unassigned", "run_id": 1, "step": 1}
    for other in (other_step, other_run):
        assert not _match_scoped_reasons([overdue, other], ["overdue", "unassigned"], "all", "step")[0]
        assert _match_scoped_reasons([overdue, other], ["overdue", "unassigned"], "all", "sample")[0]
    accepted, reasons = _match_scoped_reasons([overdue, other_step, same_step], ["overdue", "unassigned"], "all", "step")
    assert accepted
    assert reasons == [overdue, same_step]
    assert _match_scoped_reasons([overdue, other_step], ["overdue", "unassigned"], "any", "step")[1] == [overdue, other_step]
    assert not _match_scoped_reasons([{"kind": "run_blocked", "run_id": 1, "step": None}], ["blocked"], "all", "step")[0]


@pytest.mark.parametrize("text,match", [
    ("Match any condition", "any"), ("Match all conditions!", "all"),
    ("Require all conditions", "all"),
    ("Cumplir cualquier condición", "any"),
    ("Cumplir todas las condiciones", "all"),
])
def test_edit_match_mode(text, match):
    from assistant.workflow_query import edit_filters
    assert edit_filters(text, {"filters": ["overdue", "unassigned"]}) == (["overdue", "unassigned"], match, None)


@pytest.mark.parametrize("text", [
    "Remove the overdue filter", "Remove overdue filter!", "Quitar el filtro de vencidas",
])
def test_remove_filter_preserves_existing_operator(text):
    from assistant.workflow_query import edit_filters
    assert edit_filters(text, {"filters": ["overdue", "unassigned"], "match": "any"}) == (["unassigned"], "any", None)


def test_edits_are_complete_commands_and_do_not_modify_input():
    from assistant.workflow_query import edit_filters
    state = {"filters": ["overdue", "unassigned"]}
    for text in ("Remove the overdue filter and delete samples", "Match any condition in project OTHER", "assign work item 1"):
        assert edit_filters(text, state) is None
    assert edit_filters("Remove the not overdue filter", state)[2]
    assert state == {"filters": ["overdue", "unassigned"]}
