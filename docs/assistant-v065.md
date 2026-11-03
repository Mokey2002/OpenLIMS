# OpenLIMS v0.65: page-aware questions and natural corrections

The assistant can use a loaded sample/project page for supported questions about **this** record. It also accepts atomic corrections to a signed result query, including calendar-month windows. Both features work with OpenLIMS Rules; no model or new service is required.

## Ask about the record on screen

On a successfully loaded sample page, open the floating assistant. Its **Use this sample: …** switch makes the selected page visible and lets you turn page context off. Quick questions include:

```text
Summarize this sample
Why is this blocked?
Show results for this sample
```

Other supported sample reads are `Show evidence for this sample` and `Show history for this sample`. Guidance reports recorded pipeline requirements, missing fields, dependencies and review gates, with its existing display limits. If no pipeline exists, it says so; it does not invent a reason for being blocked.

Project pages offer:

```text
Summarize this project
Show samples in this project
Show results for this project
```

**Open assistant with this record** opens the full assistant with an explicit selected-record bar. It transfers a record reference to a new chat, not the widget's transcript. **Clear page selection** removes that reference. A normal visit to the assistant has no automatic page selection.

Page context comes from successfully loaded detail data that matches the current route. Unloaded, failed, unsupported or different-record routes do not publish an old page reference. The widget replaces the page reference as you navigate. Turning off page context or clearing the page selection leaves any existing conversation/query context intact; its own Clear control removes it. Page context is separate from conversation/query context: an existing investigation keeps its target when you ask a filter follow-up; a supported question explicitly referring to “this” uses the visible page selection. An explicit other sample/project request keeps its named target. General questions do not read the page record.

The UI enables this feature only when the API status advertises `page_context: true`. Both JSON chat and SSE chat accept an optional payload:

```json
{
  "message": "Show results for this sample",
  "page_context": {
    "kind": "sample",
    "record_id": "PUBLIC_UUID_OR_POSITIVE_RECORD_ID"
  }
}
```

Use the actual ID from the sample/project API. Only `kind` and `record_id` are accepted; client labels, user overrides and arbitrary paths are rejected. The server resolves the record through the caller's permission-scoped queryset on every request. The reference never grants access, and mismatched sample/project questions require clarification. Extra filters are not silently discarded from page-relative questions; start with the supported result read and then apply a correction.

Page context does not select a target for a write. A request such as `Approve this sample`, or a combined page read and mutation, asks for an exact explicit target and creates no action preview. Existing explicit action flows retain their confirmation requirements.

## Correct an investigation naturally

After a sample/project result query, try:

```text
Show failed results for project ALPHA yesterday excluding key old-control
Compare those with this month
Explain numeric differences
No, use last month and exclude key control
Actually, use sample S-102 and this month
```

Corrections support `No, …`, `Actually, …`, `Instead, …`, `Use …`, and `Switch to …`. Join supported changes with `and`; quote identifiers containing spaces or `and`. You can change the target, date window, QC status, exact keys, instrument or entered-by username using the existing typed filter forms. The operation remains read-only.

The backend first parses the whole correction and validates the final plan. It then applies all requested changes together. Unmentioned filters, comparison period and comparison-answer focus remain. A new date window replaces the earlier date constraints; newly excluded keys are added to prior exclusions. `Clear excluded keys filter` removes exclusions. In a result detail view, corrections apply to its retained parent result query. More than one candidate query requires clarification.

`No, use last month and exclude controls` requires clarification because “controls” does not identify an exact recorded result field. It runs no query and does not partially apply the new month. Repeat the complete correction with exact keys, for example `No, use last month and exclude key control`. Unsupported conditions, conflicting periods, multiple new targets and embedded mutations also run no query and retain the earlier signed query state. This is a bounded correction grammar, not unrestricted natural-language understanding.

`last month` / `previous month` means the complete previous calendar month. `this month` means the first day of the current month through the end of today. They use `OPENLIMS_TIME_ZONE` and filter **result creation time**. Start boundaries are inclusive and end boundaries exclusive. These periods also work in initial result requests and `Compare those with last month`. Month windows remain relative and are resolved again when a saved query is reopened. Year transitions, leap years and local date boundaries are respected.

## Saved chats and access changes

Page reads save a stable record reference and a fixed read-task name, not historical laboratory answers or page values. Reopening fetches current accessible data and current labels after a rename. Page result queries issue the same signed continuation state used by existing filter/focus/investigation follow-ups. Subsequent corrected result queries retain their typed plan normally. Revoked/inaccessible targets return an unavailable message; saved conversation ownership and signed-turn checks still apply.

## Upgrade and validation

No new migration, dependency or model is required. Rebuild the frontend and restart/reload the API normally. `VERSION`, the generated footer, and both READMEs report **v0.65.0**. The README release summaries explicitly cover v0.65, v0.64 and v0.63; the earlier v0.62 history remains available.

Regression coverage includes loaded-page identity and navigation, opt-out and explicit full-chat handoff, unchanged explicit targets/general questions, page write rejection, strict metadata validation, permission revocation, saved-chat refresh and renames, signed/cross-user state, atomic corrections and unsupported conditions, month boundaries, existing comparison filters/focus, and real authenticated HTTP/ASGI streaming. Frontend and browser checks cover both chat interfaces. These are deterministic application/integration checks, not a live LLM accuracy measurement.
