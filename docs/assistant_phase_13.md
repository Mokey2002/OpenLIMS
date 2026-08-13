# Assistant Phase 13 — Investigation Workbench

OpenLIMS v0.23.0 adds a deterministic, permission-filtered investigation workspace for reviewing why a sample or result may have failed QC.

## Evidence reviewed

- The subject sample's results, configured reference limits, QC decisions, and recorded failure reasons.
- Same-batch peers when a batch exists, otherwise same-project peers, within a configurable date window.
- Numeric differences from peer medians and transparent z-scores when enough peer measurements exist.
- Failed and overdue work items, assignees, due dates, sample age, and peer workflow timing.
- Similar failures for the same result keys in the peer cohort.
- Instrument import provenance from the explicit connector-created work-item relation, with legacy name, notes, and audit fallback.
- Other instrument jobs and reagent reservations associated with the same project and date window.
- Audit events for the sample, its work items, and its results.

## Evidence levels

| Evidence type | Meaning |
|---|---|
| Direct | A stored result, QC decision, workflow state, audit event, or connector provenance link for the subject. |
| Comparative | A deterministic comparison with accessible peer samples. |
| Contextual | A project/time association without a direct subject-level usage link. |

Instrument connector imports link their work items directly to the originating import job. Legacy records are backfilled from the established import-job naming convention, with audit/text fallback retained when a relation is unavailable. Other project import jobs remain contextual. Inventory reservations currently connect reagent lots to projects, not individual samples, so reagent evidence is always presented as context rather than causation.

## Example Assistant requests

```text
Investigate why sample S-1042 failed QC
Investigate result 481
Graph failures by operator
Show instrument import context
Show reagent lot context
Export this investigation as PDF
```

## Regular UI

Open `/investigations` to select a sample or result, evidence window, optional analyte filter, and graph grouping. The workbench displays ranked findings, source results, workflow evidence, similar failures, instrument connector evidence, reagent lot context, and the audit timeline.

## Safety and reproducibility

- Every query begins with the requesting user's accessible sample scope.
- Read-only investigation does not require confirmation.
- Calculations are performed by OpenLIMS code; an optional LLM may summarize but does not calculate evidence.
- Operator names are displayed for traceability and are not treated as evidence of responsibility.
- Findings are decision support and do not automatically change QC or workflow records.
- Export requires explicit confirmation, recalculates the investigation, and rechecks access.
- Generated artifacts store their filters and SHA-256 checksum in the audit trail.
