# OpenLIMS v0.63 assistant guide

This release improves result explanations, investigation follow-ups, editable filters, descriptive comparisons, optional offline SOP retrieval, and provider evaluation. The documented direct commands are in English; an optional routing model can interpret other wording. Every laboratory read still checks current access. No new database migration is required beyond the v0.62 migrations.

## Explain a result and return to the investigation

Try this with an accessible project:

```text
Show failed QC results for project ALPHA yesterday
Compare those with last week
Explain the first result
Back to comparison
Apply the same filters to project BETA
```

The result overview now shows the actual recorded value and unit, configured reference bounds, the numerical comparison when possible, automated QC status, human review status, recorded reasons/notes, and linked instrument/run/import provenance. Reasons and notes remain recorded statements, not independently established scientific causes. Missing reasons, unevaluated checks and unavailable reference comparisons are identified. Long notes remain labeled excerpts. The source links to the selected result.

`Back to results`, `Back to comparison` and `Go back` reload a prior query. `Apply the same filters to sample S-102` or `Same filters for project BETA` changes the target while keeping dates, QC, keys, instrument, operator and comparison period. In a detail view, filter changes apply to its parent result query. Multiple candidate result queries require clarification.

The signed, user-bound investigation token retains up to four earlier plans and displayed result IDs, not laboratory values, for one hour. Revisited queries run again. Saved drill-downs also retain the parent query with stable project/sample references, so renamed targets can be reopened. Inaccessible parents are omitted on saved-chat restoration. None of this state grants access or authorizes a change.

## Filters you can inspect and edit

```text
Show results for project ALPHA since Friday from instrument SEQ-1 by operator alice
Only yesterday
Only key concentration
Excluding key control
From 2026-10-01 until 2026-11-01
Clear operator filter
Clear comparison filter
```

Supported filters are QC (`failed`, `passed`, `pending`, `rejected`, `approved`, `all`), the existing named periods, inclusive start/exclusive end dates, exact included/excluded result keys, exact instrument profile code, and exact result entered-by username. Instrument and operator matching is case-sensitive. The operator is **Result.entered_by**, not the work assignee, reviewer or instrument's physical operator. The instrument comes from **WorkItem.source_import_job.instrument**; results without a linked import do not match an instrument filter.

`Since Friday` means the most recent Friday on or before today, through the end of today in `OPENLIMS_TIME_ZONE`. `Since YYYY-MM-DD` uses the same end boundary. Calendar days include daylight-saving transitions. Dates describe **result creation time**, not acquisition, import upload, or QC review time. A `since` window is resolved to absolute dates when asked; named periods are reevaluated when refreshed. Start dates after the end are rejected.

Both chat views display removable filter buttons and **Edit result filters** with QC, instrument, entered-by username, exact key and date controls. A result drill-down includes a return button. These controls submit normal supported requests with signed server context; display labels supplied by a client cannot authorize a query. Unsupported or conflicting conditions require clarification, without running a broader query.

## Comparisons with meaningful denominators and units

Period comparisons retain the original result-count table and add two tables in **Sources and scope**:

- **QC failure rates among assessed checks:** failures divided by results whose `qc_passed` is true or false. Unassessed counts are separate. A zero assessed denominator has no rate. Both windows retain date, instrument, operator and key filters; the QC status filter is removed for this denominator so a failure-only request cannot manufacture a 100% rate. Human review rejection is not an automated QC failure. Differences are percentage points.
- **Numeric results in compatible units:** finite `NUMBER` values only, with count, mean, minimum and maximum for each window. This table keeps the selected QC filter. Groups share analysis code, work type and result key. Known mass, volume and mass-concentration units are converted to common units; unknown units retain their exact case and spelling. Missing units show finite-value counts only; means and bounds are withheld because compatibility cannot be established. No concentration-to-molarity, temperature, assay calibration or other inferred conversion is performed.

For example, `10 ng/uL`, `20 ug/mL`, and `20000 ng/mL` yield three values in `ng/µL`, with mean approximately `16.666667`. A result in `mM` or a different analysis stays in another group. Each table displays up to 40 groups; every matching record contributes to each displayed group. Missing, nonnumeric and nonfinite exclusions are disclosed. Descriptive differences do not establish a cause, significance, equivalence, or release approval. Windows can overlap and have unequal durations.

## Optional local SOP embeddings

Default SOP retrieval continues to use PostgreSQL full-text search (portable keyword fallback) and the inspectable `lab-concepts-1` vocabulary. Broader semantic paraphrases can use an **optional local Sentence Transformers model**. No model weights are bundled or downloaded at runtime, and no SOP text is sent to an external embedding service.

To enable this deployment option:

1. Install `backend/requirements-sop-embeddings.txt` in a custom API image. The normal image stays lightweight.
2. Prepare an approved Sentence Transformers model in a local directory and mount it read-only into the API container, for example `/models/sop-encoder`. Use a model whose supported languages and domain fit your SOPs. Models requiring remote custom code are unsupported.
3. Set `OPENLIMS_SOP_EMBEDDING_MODEL_PATH=/models/sop-encoder` and optionally `OPENLIMS_SOP_EMBEDDING_MIN_SCORE=0.35`; restart the API. Tune the cosine threshold with reviewed examples for that model. Restart after replacing model files in the same directory.

The CPU model loads only from the existing absolute local directory (`local_files_only=True`, `trust_remote_code=False`). Retrieval filters for approval, current status, effective date, project and allowed groups **before** embedding documents. It inspects the 100 most recently updated accessible sections, with up to 32 overlapping 100-word chunks per section (20-word overlap). Scores combine cosine similarity with small lexical/concept tie-breakers, retaining known opposite-concentration protections. Top three sections link to their full current versions, and citation metadata includes the matched character offsets and similarity. Candidate/section limits are disclosed when reached; this is bounded retrieval, not an exhaustive corpus index.

A bounded in-process cache avoids recomputing unchanged section vectors. Edits invalidate the content hash; current permissions are checked before every cache use. A missing dependency, unavailable model or invalid vector falls back to the existing approved lexical/concept search and reports `embedding_fallback` in retrieval metadata. An active model call finishes before cooperative cancellation is checked again. Evaluate paraphrases and contradictory instructions against your actual chosen model before relying on retrieval quality.

## Provider evaluation without silent rules-only passes

The existing `evaluate_assistant_answers` command now accepts up to 30 turns per case, exact nested `facts` expectations, and `overview_excludes` checks. Existing case files continue to work. `facts` paths start at the first result query, for example:

```json
[
  {
    "name": "Recorded result explanation",
    "turns": [
      {"message": "Show results for project ALPHA yesterday"},
      {"message": "Explain the first result"}
    ],
    "expected": {
      "operations": ["result_detail"],
      "overview_contains": ["QC check:", "Configured reference:"],
      "facts": {"total": 1}
    }
  }
]
```

Replace the project and expectations with reviewed facts from a dedicated evaluation database. Include known values, exact source URLs, empty results, ambiguous requests, inaccessible targets, corrections and longer investigations. The generic example is not a scientific truth set.

To exercise the actual configured model even on recognized requests:

```bash
python manage.py evaluate_assistant_answers --cases /path/reviewed-cases.json --user evaluation-user \
  --live-provider --provider openai --model YOUR_OPENAI_MODEL --force-provider --require-provider

python manage.py evaluate_assistant_answers --cases /path/reviewed-cases.json --user evaluation-user \
  --live-provider --provider ollama --model YOUR_OLLAMA_MODEL --force-provider --require-provider
```

Both commands require an enabled, reachable provider and its normal configuration. They may incur inference costs. Every forced turn asks the provider to classify a read plan; validated reads still execute in the backend. A short follow-up can reuse signed context only when its predicted steps match the supported server-resolved continuation. Writes and arbitrary provider tools are never executed by this evaluator. It measures read-plan interpretation and grounded answers, not unrestricted generated conversation.

Reports distinguish attempted provider requests, valid provider responses, read plans, per-case facts/source checks, and p50/p95 case latency. `--require-provider` fails a case when no provider was used or any provider attempt failed to return a valid route, avoiding rules-only benchmark passes. `--force-provider` and `--require-provider` require `--live-provider`; without them the deterministic/default behavior remains available. Store reports from the same reviewed cases/database for each model to compare accuracy and latency. SOP searches can record their usual audit events.

## Upgrade and verification

Run the normal migrations, restart the API, and rebuild the frontend. No v0.63 schema change is introduced. Optional embeddings require the extra package/model setup above; otherwise the new core features work with OpenLIMS Rules. `VERSION`, the generated footer module, and both READMEs report **v0.63.0**.

Regression coverage includes fresh result explanations, revoked access, bounded/tampered/cross-user memory, saved renamed-target navigation, weekday/date/instrument/operator filters, explicit rejection of unsupported filters, assessed-check denominators, zero denominators, compatible/incompatible units, missing/nonfinite/extreme numeric values, and offline embedding adapter/fallback/cache permissions. Browser coverage exercises filter edits, return navigation and statistic tables in both chat views.

Provider protocols and embedding vectors are simulated in automated tests. This environment has no enabled live LLM or provisioned embedding model, so these checks do not establish actual model accuracy. Use the explicit live commands and a reviewed local retrieval set for that measurement.
