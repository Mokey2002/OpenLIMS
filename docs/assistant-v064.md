# OpenLIMS v0.64: clearer scientific comparison answers

Result-period comparisons now explain actual QC-rate and numeric measurement differences in the main answer. These explanations are authored from backend calculations and work with OpenLIMS Rules; they do not require an LLM or a new service.

## Ask for the comparison you mean

With an accessible project or sample:

```text
Show failed results for project ALPHA yesterday
Compare those with this week
Explain failure-rate differences
Explain numeric differences
Explain count differences
Show comparison overview
```

Both the assistant page and widget have a **Comparison answer focus** selector with the same choices. Changing focus preserves the target, dates, included/excluded keys, QC status, instrument and entered-by filters. Filter edits retain the chosen focus. Clearing the comparison removes it. A drill-down can return to the focused comparison, and saved conversations retain that choice while fetching fresh data and rechecking permissions.

`Explain measurement differences`, `Show QC failure rates`, and `Explain the count difference` are also supported. `Explain the largest difference` retains its documented result-count meaning. Focus requests require one existing sample/project result-period comparison. Multiple comparisons or requests mixing a focus with a new unsupported condition require clarification before any query runs. Change filters separately.

A typed comparison read-plan step can include `"focus": "overview"`, `"counts"`, `"qc_rates"`, or `"numeric"`. These are presentation choices on `project_results_compare` / `sample_results_compare`, not new database permissions or executable operations. Focus is validated and included in signed continuation state. Other operation types reject it.

## What the answer explains

**Counts:** matching result counts and the largest absolute count difference by key. Counts remain distinct from failure rates. A difference of ten recorded results cannot by itself establish a higher failure rate.

**QC rates:** the largest absolute failure-rate difference among compatible analysis/work-type/key groups, with the failed/assessed denominator in each window, unassessed counts, and change in percentage points. For example:

> Selected 50.00% (2/4 failed/assessed), comparison 20.00% (1/5 failed/assessed); increase of 30.00 percentage points (selected minus comparison).

The rate denominator keeps date, key, instrument and entered-by filters but removes the QC status filter from both windows. A failure-only list therefore does not turn every rate into 100%. Human review rejection is a separate decision. A zero assessed denominator has no rate and is never presented as zero failure or no change.

Groups are ranked using unrounded proportions **before** the 40-group table limit. Percentages and percentage-point differences use exact fractions with half-even rounding to two decimal places. The displayed percentage-point difference is calculated before percentage rounding: `1/3 − 1/6` is approximately `16.67` percentage points, even though subtracting the displayed percentages `33.33 − 16.67` would give `16.66`. A nonzero change that rounds to zero is described as less than `0.01` percentage points rather than unchanged.

**Numeric measurements:** up to two paired group summaries in analysis/work-type/key/unit order, each with selected/comparison means, recorded-value counts and the mean difference in a common compatible unit. Numeric summaries retain the selected QC filter. Mean differences are calculated before the means are rounded for display. Different analyses, keys, work types or incompatible units are not ranked against each other. Missing units, nonnumeric values and absent values in either window cannot establish a comparable mean difference. Known unit conversions follow the [v0.63 guide](assistant-v063.md).

The full numeric table adds **Mean difference (selected minus comparison)**. Groups with comparable means appear first; the answer discloses when only a subset of paired groups is summarized. Finite extreme differences remain decimal strings rather than overflowing JSON numbers.

## Scope and interpretation

The answer names both date windows and the active filters. It identifies overlapping windows, unequal calendar-day durations or an open selected boundary. Calendar-day counts are not elapsed-hour counts across daylight-saving changes. Overlapping windows are not independent cohorts.

Sources include a permission-checked project/sample link describing aggregate scope. Aggregates use all matching accessible records, including records outside the displayed result examples. Those examples are not claimed to enumerate a denominator or verify the entire aggregate. Each read still accesses current data independently; the response is not one transactionally consistent database snapshot.

The explanations report descriptive differences. They do not establish causality, statistical significance, assay equivalence or release approval. No provider generates replacement laboratory facts, and saved conversations do not store the computed statistics as historical laboratory answers.

## Upgrade and validation

No new migration or dependency is required. Rebuild the frontend and restart/reload the API normally. `VERSION`, the generated footer module, and both READMEs report **v0.64.0**.

Regression tests cover:

- Displayed denominators, units, mean differences, citations and source scope.
- Focus changes with preserved filters, saved-chat refresh, drill-down return, revoked access and cross-user signed-context rejection.
- Unrounded percentage calculations, largest changes beyond the display limit, mean display rounding and finite extreme numeric differences.
- Missing assessments/units, incompatible units, one-sided cohorts, zero and negative differences, adjacent and overlapping date windows.
- Rejection of malformed focus fields and unsupported extra conditions before database reads.
- Focus controls and statistic-table rendering in both browser chat surfaces.

These are deterministic answer and UI checks, not measurements of live LLM accuracy. Live-model and optional embedding evaluation remain separate deployment tasks.
