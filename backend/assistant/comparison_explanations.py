"""Plain-language comparisons generated exclusively from backend calculations."""
from datetime import date

COMPARISON_FOCI = {"overview", "counts", "qc_rates", "numeric"}


def window_scope(selected, comparison):
    def bounds(filters):
        return (date.fromisoformat(filters["created_from"]) if filters.get("created_from") else date.min,
                date.fromisoformat(filters["created_before"]) if filters.get("created_before") else date.max)
    left, right = bounds(selected), bounds(comparison)
    left_days = (left[1] - left[0]).days if {"created_from", "created_before"} <= selected.keys() else None
    right_days = (right[1] - right[0]).days
    return {"overlap": max(left[0], right[0]) < min(left[1], right[1]),
            "selected_days": left_days, "comparison_days": right_days,
            "unequal_duration": left_days != right_days if left_days is not None else None}


def _rate_line(row):
    left, right = row["selected"], row["comparison"]
    proportions = (f"selected {left['failure_rate']:.2f}% ({left['failed']}/{left['assessed']} failed/assessed), "
                   f"comparison {right['failure_rate']:.2f}% ({right['failed']}/{right['assessed']} failed/assessed)")
    difference = abs(row["difference_pp"])
    amount = f"{difference:.2f}" if difference else "less than 0.01"
    direction = row["direction"]
    change = "unchanged (0.00 percentage points)" if direction == "unchanged" else f"{direction} of {amount} percentage points"
    return f"Largest QC failure-rate difference: {row['group']}: {proportions}; {change} (selected minus comparison)."


def explain_comparison(facts, focus="overview"):
    statistics = facts["statistics"]
    lines = []
    unknowns = ["These descriptive differences do not establish scientific causality, statistical significance, or release approval."]
    if focus in {"overview", "counts"}:
        lines.append(f"{facts['target']}: {facts['total']} matching results; {facts['failed']} failed checks and {facts['rejected']} rejected reviews. Showing {facts['shown']}.")
        if facts["differences"]:
            row = facts["differences"][0]
            lines.append(f"Largest count difference: {row['key']}, {row['selected']} versus {row['comparison']} ({row['difference']:+d}).")
        else:
            lines.append("No records match the result-list filters in either window.")
        unknowns.append("Count differences do not identify their cause. Windows can have different durations; the count difference is not a failure-rate comparison.")
    else:
        lines.append(f"{facts['target']}: {'QC failure-rate' if focus == 'qc_rates' else 'numeric measurement'} comparison.")
    if focus in {"overview", "qc_rates"}:
        paired = next((row for row in statistics["rates"] if row["difference_pp"] is not None), None)
        if paired:
            lines.append(_rate_line(paired))
        else:
            lines.append("A QC failure-rate difference is unavailable: no group has assessed checks in both windows. Missing rates are not zero.")
        unassessed = statistics["unassessed"]
        lines.append(f"Unassessed results: selected {unassessed['selected']}; comparison {unassessed['comparison']}. These are excluded from rate denominators.")
        lines.append("QC rates retain date, key, instrument and entered-by filters and remove the QC status filter from both denominators. Human review rejection is separate.")
        lines.append("A sample can contribute multiple result checks to these denominators.")
    if focus in {"overview", "numeric"}:
        paired = [row for row in statistics["numeric"] if row["mean_difference"] is not None]
        for row in paired[:2]:
            lines.append(f"Mean comparison — {row['group']}: selected {row['selected_mean']} {row['unit']} (n={row['selected_n']}), "
                         f"comparison {row['comparison_mean']} {row['unit']} (n={row['comparison_n']}); "
                         f"difference {row['mean_difference']} {row['unit']} (selected minus comparison).")
        if not paired:
            lines.append("A numeric mean difference is unavailable: no group has finite numeric values and recorded compatible units in both windows.")
        lines.append("Numeric summaries keep the selected QC filter. Missing units and incompatible groups are not compared.")
        lines.append("n counts recorded numeric values, including repeated measurements of the same sample.")
        lines.append("Mean differences are calculated before display rounding.")
        if statistics["numeric_comparable_groups"] > 2:
            lines.append(f"Showing 2 of {statistics['numeric_comparable_groups']} paired numeric groups in analysis/work type/key/unit order. Narrow the result key to focus the comparison; changes across different units are not ranked.")
    scope = facts["comparison_scope"]
    if scope["overlap"]:
        lines.append("Scope: the date windows overlap; they are not independent cohorts.")
    if scope["unequal_duration"]:
        lines.append(f"Scope: the windows cover different numbers of calendar days: selected {scope['selected_days']}, comparison {scope['comparison_days']}.")
    elif scope["selected_days"] is None:
        lines.append("Scope: the selected window has an open date boundary; its duration is not fixed.")
    if statistics["rate_groups"] > len(statistics["rates"]) or statistics["numeric_groups"] > len(statistics["numeric"]):
        lines.append("Scope: the tables show up to 40 groups each. The largest QC-rate difference is selected before that limit; numeric changes are not ranked across unlike groups.")
    lines.append(f"Selected window: {facts['window']}. Comparison window: {facts['comparison_window']}.")
    lines.append(facts["filter_summary"] + ".")
    return {"text": "\n".join(lines), "focus": focus, "unknowns": unknowns,
            "next_checks": ["Open Sources and scope to inspect the comparison tables and recorded results; check cohort size and window overlap before interpreting changes."]}
