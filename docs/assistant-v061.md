# OpenLIMS v0.61: combined read-only answers

Use a semicolon between two to four complete read requests. Replace example identifiers with records you can access:

```text
Show evidence for sample S-100; show its history; show the SOP for concentration
Summarize project ALPHA; list samples in project ALPHA
Compare runs "Extraction run A" and "Extraction run B"; show failed QC results for sample S-100; show the SOP for concentration
```

The comparison describes notebook experiments. It does not resolve instrument `run_id` values as experiments, infer that a sample belongs to a compared run, or establish a scientific cause. Use exact experiment public IDs or unique quoted titles.

## Supported operations

| Operation | Required string arguments | Rules-only example |
| --- | --- | --- |
| `sample_summary` | `sample` | `Explain sample S-100` |
| `sample_evidence` | `sample` | `Show evidence for sample S-100` |
| `sample_failures` | `sample` | `Show failed QC results for sample S-100` |
| `sample_history` | `sample` | `Show history for sample S-100` |
| `project_summary` | `project` | `Summarize project ALPHA` |
| `project_samples` | `project` | `List samples in project ALPHA` |
| `compare_runs` | `left`, `right` | `Compare runs "Run A" and "Run B"` |
| `sop_search` | `question` | `Show the SOP for concentration` |

Common complete English clauses work in rules-only mode. `and show …` and `then show …` also separate requests. A quoted title can contain those words or a semicolon. Within a combined request involving exactly one explicit sample, `show its history`, `show the evidence` and `show its failed QC results` reuse that sample. Across turns, the existing single-record follow-ups remain available. Multiple selected samples/projects clear the active record rather than choose the last one for a follow-up.

When LLM routing is enabled, OpenAI and Ollama can interpret other wording into the same typed `read_plan` schema. Identifiers must occur in the current request, and the SOP question must be copied from it. This version does not resolve model-invented targets, cross-step references, arbitrary filters, charts, calculations, drafts, SQL, or actions in a plan. Plans have two to four steps and reject unknown fields/operations. A combined request requiring clarification cannot fall back to a single provider tool that silently executes only one part. Deterministic parsing requires every clause; the provider is instructed to preserve every condition and use `unknown` if it cannot. Model interpretation can still misunderstand wording: review the displayed operation list and scope.

## Sources and scope

Both chat surfaces show an expandable **Sources and scope / Fuentes y alcance** panel. It retains step order, completion/unavailability, comparison tables, source links, excerpt limits and a timestamp. Sample explanations also expose citations when used by themselves. Source links identify:

- Samples and displayed flagged work.
- Displayed result rows, with anchors in the sample page.
- Instrument import jobs linked to those displayed results.
- Accessible notebook experiments and current approved SOP sections.

Each operation checks access and queries current records independently. The combined answer is not one atomic database snapshot. An inaccessible/missing record is reported as unavailable without distinguishing the two cases. A missing SOP match makes the answer partial; it never supplies an invented instruction. Normal SOP-read audit events are retained, but no laboratory records, action proposals or approvals are created by the plan. Final answers come from the existing backend readers and are not rewritten by a second model call.

Existing sample evidence includes all current aggregate counts, at most five recent results, three flagged results and three flagged work items; flags may overlap. The explicit failed-result read shows at most 20 results, including failed checks or rejected reviews, with its total count. A failed check and an approved review can coexist; they remain separate fields. History shows the latest 50 audit/custody events and 10 current results, not reconstructed historical result values. Project lists/assignee tables retain their 100-row limits. Run comparison limits remain in its table notes. None of these summaries grants release approval or proves a root cause.

## SOP search and full sections

PostgreSQL ranks document code/title, section and content using weighted English full-text search. It handles word forms such as `concentration` and `concentrations`. Search is restricted in the database to current, approved, effective, accessible sections **before** ranking/limiting; project membership and allowed groups both apply. Three sections are returned at most. Search is lexical, not semantic equivalence or proof that an instruction applies. Non-PostgreSQL development installations use a deterministic keyword fallback.

Passages are selected around matches with PostgreSQL headlines, with bounded excerpts and a visible excerpt indicator. The SQLite fallback selects a dense keyword window. Each citation includes document code, version and section and opens `/sops/<id>` to read the full section. That page fetches the permission-filtered SOP detail API; revoked access produces an unavailable message. Content is rendered as text. No embeddings, new external service or schema migration is required.

## Repeatable answer-quality checks

The existing `evaluate_assistant` command continues to check deterministic routing. The additional command checks actual answers against facts you know about a prepared database:

```bash
python manage.py evaluate_assistant_answers --user technician --cases /path/to/cases.json
```

For example, after replacing IDs and expected values with known records:

```json
[
  {
    "name": "Recorded QC evidence and approved instructions",
    "message": "Show evidence for sample S-100; show the SOP for concentration",
    "expected": {
      "contains": ["45.0 ng/uL", "QC check: failed", "calibration control"],
      "excludes": ["The sample is approved for release"],
      "citation_kinds": ["result", "sop"],
      "operations": ["sample_evidence", "sop_search"],
      "partial": false,
      "clarification": false
    }
  }
]
```

Supported expectations are `contains`, `excludes`, `citation_kinds`, `operations`, `partial` and `clarification`. Fact/forbidden checks use case-insensitive substrings; source checks require the listed citation kinds; operations must match exactly in order. The report lists each check, case pass/fail, elapsed milliseconds and total cases passed, and returns a nonzero exit status if any case fails. It does not print the underlying answer or data records. The user must exist and be active. Cases run as that user; records must already exist. SOP reads retain their usual audit events. Cases are validated before any reads, and only the new bounded read path, sample explanations and SOP search are evaluated; action execution is unavailable.

Default evaluation makes no model calls. Use `--live-provider` explicitly to allow the configured routing provider to interpret otherwise unsupported compound wording. That requires LLM routing to be enabled, sends those questions to the configured provider, and can incur provider charges. Answers still come from the read-only backend. Compare results using the same database fixture, user, cases and provider configuration. Store reports outside the repository if they contain private case names.

The committed PostgreSQL tests exercise eight known-record quality scenarios: QC evidence/SOP, unknown QC, denied reads, missing SOP, project scope, run comparison, mixed changes, and unsupported exclusions. Additional tests cover malformed plans, source grounding, current values, provenance, excerpts and permissions. Provider adapter tests simulate both transports. Browser tests cover sources and full SOP access in both chat surfaces. These are expected-fact/source checks, not a general semantic accuracy score, live-model accuracy measurement, or scientific validation. No claim of improved live-model accuracy is made without running an appropriately prepared live benchmark.

## Release and deployment

`VERSION`, generated `frontend/src/version.js`, both READMEs and the footer report **v0.61.0**. Rebuild/restart API and frontend using the normal deployment procedure. No database migration is introduced. Upload retry/resume and saved conversation changes are separate future work.
