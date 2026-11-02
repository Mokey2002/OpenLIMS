# OpenLIMS v0.62 assistant guide

This release adds conversational result filters, concise evidence-based overviews, stronger answer checks, local semantic SOP matching, streamed progress/answers, cancellation, retries and personal saved conversations. These features share the existing authenticated Django API and permission-filtered records.

## Result conversations

Try these requests with actual accessible identifiers:

```text
Show QC failures for project ALPHA
Only yesterday
Compare those with last week
Explain the largest difference and link the supporting results
Explain the second result
```

Other supported forms:

```text
Show results for sample S-100
Show approved results for project ALPHA today
Show results for project ALPHA from 2026-10-01 until 2026-11-01
Show failed QC results for project ALPHA yesterday excluding key purity
Only key Concentration
Excluding keys purity, qc_flag
Only pending results
```

Keys are exact and case-sensitive. The same typed schema is used for samples, projects, rules and provider interpretation. Ordinary combined reads from v0.61 remain available. Result reads can also form a one-step plan. Other tools retain their existing validated command adapters; arbitrary filters are not accepted by every feature.

Supported result filters are `qc` (`all`, `failed`, `passed`, `pending`, `rejected`, `approved`), `period` (`today`, `yesterday`, `this_week`, `last_week`, `last_7_days`), `created_from`, `created_before`, `keys` and `exclude_keys`. A period cannot be combined with absolute boundaries. Comparison operations require `compare_period`. No SQL, arbitrary field names, permission overrides, unrecorded control labels or scientific causes can be supplied by a model.

Dates filter the result's **creation timestamp**, not an instrument acquisition timestamp or the date of its latest QC decision. Boundaries use `OPENLIMS_TIME_ZONE` (default `UTC`), start inclusive/end exclusive. `last_week` is the previous Monday through the next Monday; `last_7_days` includes today and the previous six dates. `this_week` includes Monday through today. Daylight-saving transitions use local calendar boundaries, including repeated hours. Windows may overlap or have different durations. The answer states the exact window, timezone and filters.

`failed` means a failed QC check **or** a rejected review. Checks and review decisions remain separate fields: a failed check and an approved review can coexist. Lists display at most 20 result rows; overall counts include all matching accessible results. Period comparisons count records by result key and show up to 20 keys ranked by absolute count difference, with up to 20 cited result rows from each window. Counts are not failure rates, and differences do not establish their causes. No averages across incompatible units are calculated.

Follow-ups use a signed, user-bound one-hour reference to the preceding read plan and displayed result IDs. They preserve scope and existing filters, fetch current records, and recheck access. Numbered results refer to the numbered selected-window list, not a new global search or comparison-window citations. Changing filters requires one unambiguous result query; multiple result queries ask which one to change. Invalid, expired, tampered or another user's state cannot authorize a lookup. These are bounded supported follow-ups, not unrestricted conversational memory.

## Concise answers with inspectable evidence

Both chat views display a backend-authored overview: findings, explicit unknowns and a suggested next check. Source links are derived from records returned by the authorized readers. Numeric counts and comparisons are computed in the backend. Expand **Sources and scope** for the original step answers, tables, record links and SOP passages. The full `answer` remains available in the API alongside `answer_overview`; tools are not silently rewritten by a second model call.

Each step reads independently. The overview does not imply a single database snapshot, scientific causality or release approval. Empty lists and unavailable information are distinct. Historical results, excerpt limits and overlapping QC flags retain their existing scope notes.

## Local semantic SOP retrieval

PostgreSQL full-text search is combined with local concept-vector similarity and lexical coverage to rerank up to 24 candidate sections; three sections are returned at most. The versioned `lab-concepts-1` vocabulary connects phrases such as:

| User wording | Related SOP wording |
| --- | --- |
| DNA too dilute | Low concentration |
| Run again / rerun | Repeat measurement |
| Freezer | Cold storage |
| Too warm | Temperature excursion |
| Sample handoff | Chain of custody |

Low and high concentration are separate concepts; an exclusively opposite instruction is excluded from that match. The vocabulary is deliberately limited and inspectable. It is not a general-purpose embedding model or a scientific interpretation engine. Out-of-vocabulary requests still use lexical search. No document or embedding is sent to an external service, and no model download is required.

Approval, effective dates, current status, project membership and allowed groups filter the database query before candidate retrieval. Archived, future, unapproved or inaccessible documents are excluded. Citations show document/version/section and matching passages and open the full permission-checked section. Search relevance does not establish that an instruction applies to a particular sample.

## Progress, streaming, Stop and Retry

Both chat views show actual step progress. General OpenAI/Ollama answers emit provider text chunks as received; deterministic laboratory answers arrive as a complete evidence-backed result after lookup. Routing JSON and internal model reasoning are never displayed as answer text.

**Stop** aborts the browser request and registers authenticated, owner-bound cancellation. Cancellation state is shared in PostgreSQL, including early stops received before stream registration. Subsequent steps and provider chunks check cancellation. An active database/provider call may finish before cancellation is observed; this is cooperative cancellation, not a promise to terminate every underlying operation instantly. Provider calls in streamed requests use a 30-second network timeout; OpenAI automatic retries are disabled there. Late output is discarded. Stop does not undo an already completed action or audit event; supported laboratory changes continue to require their existing explicit confirmation.

**Retry last question** is explicit and uses a fresh request UUID. Incomplete or errored streams are not accepted as completed answers. Each API process admits four running workers and eight total running/queued requests; additional requests return `429`. Duplicate retained request IDs return `409`. Nginx respects `X-Accel-Buffering: no`, and SSE responses disable caching. Older clients can continue to use the ordinary JSON endpoint. Clients connected to an older API use its JSON transport; aborting a legacy request does not provide the new server cancellation guarantees.

## Personal saved conversations

Expand **Saved conversations**, enter a name and choose **Save as new chat**. Existing server-issued turns can be included, and subsequent successful turns in the selected chat are saved. You can open, rename, delete or start an unsaved chat. There is a limit of 50 conversations per account and the last 20 question/answer exchanges per conversation. Nothing is written to a saved conversation until the user opts in.

Saved chats belong to the authenticated account. Laboratory turns store the user's question and validated query references, not historical tool answers, result values, permission grants or confirmation tokens. Sample/project references survive renaming; experiment comparisons retain public IDs. Opening a conversation reruns the supported reads with current access and current values. Relative dates are reevaluated when reopened. An inaccessible record yields an unavailable message. Action previews and unsupported legacy turns are not replayed; the user must ask again. General-chat answers are retained as historical conversation text, separately from laboratory evidence.

Temporary browser save tokens are signed, user-bound and expire after 24 hours. They authorize saving only server-issued turns; clients cannot submit an arbitrary assistant transcript. Signing is not encryption. Questions manually containing laboratory information remain part of the opted-in personal history. Deleting a conversation removes its application record. Existing short general-chat and task memory limits remain in effect for active model context.

## Quality checks and model comparisons

The original routing evaluator remains available. The answer evaluator now accepts multi-turn cases and checks exact returned result identities, exact source URLs, computed counts and displayed overview facts, in addition to required/forbidden text, citation kinds, ordered operations, clarification and partial results.

```json
[
  {
    "name": "QC follow-up keeps scope",
    "turns": [
      {"message": "Show QC failures for project ALPHA"},
      {"message": "Only yesterday", "expected": {"counts": {"total": 2}}},
      {"message": "Excluding key purity"}
    ],
    "expected": {
      "counts": {"total": 1},
      "result_ids": [123],
      "citation_urls": ["/samples/10#result-123"],
      "overview_contains": ["1 matching results"],
      "operations": ["project_results"]
    }
  }
]
```

Replace examples with known records and facts in your prepared test database. Up to 200 cases, ten turns per case, and the documented expectation limits are accepted. Exact URL/ID checks compare complete sets. Count checks compare backend numbers; overview checks verify the text actually displayed. Case and turn checks must pass. The report includes median/p95 whole-case elapsed time, configured model and the number of attempted provider routing requests, and fails with a nonzero exit status on a failed expectation.

```bash
python manage.py evaluate_assistant
python manage.py evaluate_assistant_answers --user technician --cases /path/to/cases.json
python manage.py evaluate_assistant_answers --user technician --cases /path/to/cases.json --live-provider --provider openai --model YOUR_CONFIGURED_MODEL
python manage.py evaluate_assistant_answers --user technician --cases /path/to/cases.json --live-provider --provider ollama --model YOUR_INSTALLED_MODEL
```

Default evaluation makes no provider calls. Live evaluation explicitly requires an enabled configured routing provider and can incur provider charges. It sends otherwise unmatched compound wording for interpretation, then evaluates the actual backend answers. Deterministically understood cases need no model call even in live mode; inspect the routing-attempt count. This benchmarks the supported record-answering task, not arbitrary model prose or scientific correctness. Compare models with the same prepared database, user and cases. Provider protocol tests simulate both transports; they do not establish live-model accuracy.

To turn negative feedback into reviewed regression cases:

```bash
python manage.py export_assistant_feedback_cases --user technician --output /path/to/new-feedback-review.json
```

The export uses only that user's negative feedback whose question was explicitly saved in a personal chat. Unsaved questions remain absent from telemetry and are counted as skipped. The output file is created without overwriting an existing file, with owner-only permissions. It includes review notes and **requires review**: expected facts are not invented, and the export cannot itself pass as an evaluation case list. Verify the records and write meaningful expectations before copying selected cases into a benchmark. Automated evaluation is not scientific validation.

## API and upgrade

New authenticated endpoints under `/api/v1/`:

| Endpoint | Purpose |
| --- | --- |
| `POST assistant/chat/stream/` | SSE progress, answer deltas and final response; requires a fresh UUID `request_id`, `message`, optional `context` and `conversation_id` |
| `POST assistant/chat/requests/<uuid>/cancel/` | Owner-bound cancellation, including an early cancellation tombstone |
| `GET/POST assistant/conversations/` | List/create personal named conversations; optional server-issued `turn_tokens` when creating |
| `GET/PATCH/DELETE assistant/conversations/<uuid>/` | Reopen with refreshed reads, rename with `name`, or delete |

The JSON chat endpoint additionally accepts optional `conversation_id`. Chat replies expose `save_turn_token`; result reads expose `answer_overview`, `read_plan` evidence and user-bound continuation context. Existing cookie/CSRF and Bearer JWT authentication apply. Conversations cannot be selected by another user's ID.

Apply the new schema before serving the updated API:

```bash
python manage.py migrate
python manage.py check
```

`assistant.0009` adds personal conversation storage and cancellation state; it does not alter laboratory result tables. Rebuild/restart API and frontend through the normal deployment procedure. Optional `OPENLIMS_TIME_ZONE=America/Los_Angeles` changes relative calendar windows; `UTC` preserves the existing default. Use a valid IANA timezone. The version, generated footer and English/Spanish READMEs report **v0.62.0**.

Schedule this maintenance command periodically:

```bash
python manage.py cleanup_assistant_requests
```

It marks running requests older than an hour as cancelled and removes terminal request state older than seven days. It does not delete saved conversations, lab records or interaction feedback. Request UUIDs must be fresh; cancellation rows are operational state, not a durable instrument-delivery receipt.

Validation includes PostgreSQL unit/integration and permission tests, date boundaries across daylight-saving time, mocked provider streams and cancellation, browser checks in both chat surfaces, and a real authenticated HTTP/ASGI round trip covering streamed lookup, saved-chat refresh and revoked access. Run backend checks and the frontend unit/build/browser suites before release. Use a configured provider and prepared live benchmark before claiming improved live-model accuracy.
