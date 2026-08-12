# Assistant Phase 12 — Comparisons and Visual Analytics

OpenLIMS v0.22.0 adds deterministic, permission-filtered comparisons and charts to the Assistant and to a regular Comparisons page.

## Supported analyses

- Compare two to ten samples, projects, or batches.
- Graph numeric result values shared by selected samples.
- Compare sample status, QC pass/failure rates, open and overdue work, turnaround time, and required-metadata completeness.
- Graph daily numeric-result means for one or more projects or samples.
- Flag numeric results outside configured reference limits or with an absolute z-score of at least 2.5 when a group has at least four values.
- Identify samples that have remained in a non-terminal status beyond a configurable threshold, together with overdue and unassigned work.
- Continue the current analysis with date-window and metric follow-ups.
- Export an analysis as an audited CSV or PDF containing the stored filters, table, and chart.

## Example Assistant requests

```text
Compare samples S-100, S-101, and S-102
Compare Project Alpha, Project Beta, and Project Gamma
Compare batches B-100, B-101, and B-102
Graph glucose results for Project Alpha over the last 90 days
Find unusual results in Project Alpha
Where are samples getting stuck?
```

Follow-up examples:

```text
Only show the last 30 days
Graph the QC failure rates
Graph overdue and unassigned work
Why is Beta higher?
Export this comparison as PDF
```

## Safety and calculation rules

- All queries begin with the requesting user's accessible sample, project, or batch scope.
- Read-only analysis does not require confirmation.
- OpenLIMS calculates all metrics; an LLM may interpret phrasing but does not calculate or invent values.
- Blank QC rates mean that no explicit pass/fail decisions exist in the selected window.
- Linked-project samples may appear in more than one project comparison.
- Outlier flags are review aids and do not automatically change QC status.
- Export confirmation recalculates the analysis and rechecks access before generating the artifact.
- Generated artifacts retain their exact filters and SHA-256 checksum in the audit trail.

## Regular UI

Open `/comparisons` to build the same analyses without natural-language commands or an AI provider. Users can select the analysis, record type, entities, date window, and graph focus before running it.
