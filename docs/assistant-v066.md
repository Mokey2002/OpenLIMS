# OpenLIMS v0.66: natural requests and dependable follow-ups

This release fixes conversational routing bugs rather than changing the model. Supported lab conversations work with OpenLIMS Rules, including polite requests, short follow-ups, corrections and filtered questions about a loaded page. OpenAI/Ollama remain optional for free-form interpretation and general conversation.

## A conversation to try

Replace the sample ID with an accessible record. Each result query reads current data and rechecks access.

| Say | What happens |
| --- | --- |
| `Could you show me the results for sample S-100 yesterday?` | Selects this sample and the application's local-calendar yesterday. |
| `Just the failed ones, please` | Adds failed QC while keeping the sample and date. |
| `Thanks!` | Keeps the investigation without adding a model exchange. |
| `Could you compare those with last week?` | Adds the comparison window without dropping the selected filters. |
| `Please explain the numeric differences` | Selects the numeric comparison focus, with the existing unit and evidence limits. |
| `Can you explain the first result?` | Opens the first displayed result identity after rechecking access. |
| `Could you go back to the comparison?` | Reloads the comparison and its earlier filters/focus. |
| `No, I meant S-102` | Corrects the sample within that signed result query, keeping filters and focus. |

Other supported forms include `Can I see the failed results for project ALPHA from yesterday?`, `I'd like to see the results for project ALPHA`, `What about last month?`, `And last month?`, `Sorry, I meant last month`, and `No, I meant failed ones`.

An explicit new read such as `Actually, show me the results for sample S-102` starts a new selection with its stated filters. To keep the earlier filters, use the correction form instead. A bare corrected identifier requires **I meant** and one valid signed result query; it does not infer a record kind from client display fields. For multiple result queries, name the task and target explicitly. Quote identifiers containing spaces. Unknown/inaccessible targets never broaden the search.

## Ask about the open page with filters

With **Use this sample/project** enabled, try:

```text
Could you show me the failed results for this sample from yesterday?
Can I see the results for this project last month excluding key control?
```

Page results use the same validated date, QC, exact key, instrument and operator filters as explicit queries. Every condition must be recognized and valid before any read runs. Unknown scientific conditions such as “that look unusual”, conflicting date windows, invalid dates and embedded writes require clarification. Clarification preserves the earlier conversation so you can correct the wording; it does not silently execute the recognizable portion. Permission-denied page reads still clear stale record context.

Saved page turns retain the stable reference, task and validated filters, without laboratory answer values. Reopening reloads accessible current data after record renames and permission changes. Relative periods such as `yesterday` and `last month` are recalculated when reopened; these are saved queries, not frozen historical snapshots. Page context never selects a write target. Existing opt-out, full-chat handoff and confirmation rules remain in place.

## Fluency checks and limits

Acceptance tests exercise full authenticated conversations, not just individual regex matches. Coverage includes the eight-turn investigation above, alternate polite forms, new-topic changes, short date and status corrections, filter retention, page-filter save/reopen, renames, revoked access, forged/cross-user context, and rejection of mixed mutations without partial queries. A real authenticated HTTP/ASGI streaming test exercises a filtered page read and conversational follow-ups. Existing browser tests cover both chat interfaces.

General-chat follow-ups share the courtesy normalizer, so `Hi, could you please explain that more simply?` and `Thanks! Can you tell me more?` reuse verified general-chat history. Both OpenAI and Ollama adapter tests check history and role boundaries using simulated provider responses.

When a verified general-chat topic exists on a lab page, a bare follow-up such as `Could you explain this?` continues that topic. An explicit `Explain this sample` still selects the page record. This prevents the visible page from unexpectedly replacing a general explanation.

The development environment used for this release has **Rules mode** enabled and no active language model. These checks verify deterministic application behavior; they do **not** establish live-model answer quality, unrestricted language understanding or a conversational fluency score. The documented new direct phrases are in English. Arbitrary phrasing, misspelled identifiers and scientific inference are not guaranteed. General free-form answers require a configured provider; the assistant should not invent an answer when it is unavailable. For live validation, use the existing answer-quality command with reviewed cases and `--live-provider --force-provider --require-provider` as described in the [v0.63 evaluation guide](assistant-v063.md).

## Upgrade and documentation

No new migration, dependency, model download or scheduled automation is required. Rebuild the frontend and restart/reload the API. `VERSION` and the generated footer report **v0.66.0**. Both READMEs now retain **exactly three release-update sections and table rows: v0.66.0, v0.65.0 and v0.64.0**. Older update sections were removed; historical commits and versioned guides remain available. Stale development-version labels were corrected.
