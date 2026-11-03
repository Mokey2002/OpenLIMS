"""Descriptive comparisons of recorded results; no causal or release inference."""
from decimal import Decimal, localcontext
from fractions import Fraction

from django.db.models import Avg, Count, DecimalField, Max, Min, Q
from django.db.models.functions import Cast

from results.models import Result
from .result_queries import apply_filters

GROUP_FIELDS = ("work_item__analysis_code", "work_item__work_type", "key")
GROUP_LIMIT = 40
# Deliberately case-sensitive. Unknown units retain their exact spelling.
UNITS = {
    "ng": ("ng", "1"), "ug": ("ng", "1000"), "µg": ("ng", "1000"), "μg": ("ng", "1000"),
    "mg": ("ng", "1000000"), "g": ("ng", "1000000000"),
    "nL": ("µL", ".001"), "uL": ("µL", "1"), "µL": ("µL", "1"), "μL": ("µL", "1"),
    "mL": ("µL", "1000"), "L": ("µL", "1000000"),
    "ng/uL": ("ng/µL", "1"), "ng/µL": ("ng/µL", "1"), "ng/μL": ("ng/µL", "1"),
    "ug/mL": ("ng/µL", "1"), "µg/mL": ("ng/µL", "1"), "μg/mL": ("ng/µL", "1"),
    "mg/L": ("ng/µL", "1"), "ng/mL": ("ng/µL", ".001"),
}


def _identity(row):
    return tuple(row[field] for field in GROUP_FIELDS)


def _label(identity):
    analysis, work_type, key = identity
    return f"{analysis or '(no analysis code)'} / {work_type} / {key}"


def _rates(queryset):
    return {_identity(row): row for row in queryset.values(*GROUP_FIELDS).annotate(
        total=Count("pk"), assessed=Count("pk", filter=Q(qc_passed__isnull=False)),
        failed=Count("pk", filter=Q(qc_passed=False)), unassessed=Count("pk", filter=Q(qc_passed__isnull=True)),
    )}


def _rate(row):
    assessed = row.get("assessed", 0)
    return {"total": row.get("total", 0), "assessed": assessed, "failed": row.get("failed", 0),
            "unassessed": row.get("unassessed", 0),
            "failure_rate": float(round(Fraction(100 * row.get("failed", 0), assessed), 2)) if assessed else None}


def _rate_difference(left, right):
    if not left["assessed"] or not right["assessed"]:
        return None
    return 100 * (Fraction(left["failed"], left["assessed"]) - Fraction(right["failed"], right["assessed"]))


def _numeric(queryset):
    # Exclude NULL, NaN and both infinities before decimal aggregation. PostgreSQL
    # orders NaN above infinity. Decimal AVG avoids float accumulator overflow.
    numeric = queryset.filter(value_type=Result.VALUE_TYPE_NUMBER,
                              value_number__gt=float("-inf"), value_number__lt=float("inf"))
    value = Cast("value_number", DecimalField(max_digits=1000, decimal_places=500))
    groups = numeric.values(*GROUP_FIELDS, "unit").annotate(n=Count("pk"), mean=Avg(value), minimum=Min(value), maximum=Max(value))
    merged = {}
    with localcontext() as decimal_context:
        decimal_context.prec = 32
        for row in groups:
            raw_unit = row["unit"].strip()
            canonical, factor = UNITS.get(raw_unit, (raw_unit, "1"))
            factor = Decimal(factor)
            identity = (*_identity(row), canonical)
            stats = merged.setdefault(identity, {"n": 0, "sum": Decimal(0), "min": None, "max": None, "recorded_units": set()})
            low, high, mean = (Decimal(str(row[name])) * factor for name in ["minimum", "maximum", "mean"])
            stats["n"] += row["n"]
            stats["sum"] += mean * row["n"]
            stats["min"] = low if stats["min"] is None else min(low, stats["min"])
            stats["max"] = high if stats["max"] is None else max(high, stats["max"])
            stats["recorded_units"].add(raw_unit)
        for stats in merged.values():
            stats["_mean"] = stats.pop("sum") / stats["n"]
            for field, value in [("mean", stats["_mean"]), ("min", stats["min"]), ("max", stats["max"])]:
                stats[field] = format(value, ".8g")
            stats["recorded_units"] = sorted(stats["recorded_units"])
        for identity, stats in merged.items():
            if not identity[-1]:
                # Missing units do not establish compatibility, even within one
                # analysis/key. Keep the finite-value count but withhold summaries.
                stats.update(mean=None, min=None, max=None, _mean=None)
    return merged, numeric.count()


def compare_statistics(base, selected_filters, comparison_filters):
    rate_filters = [{k: v for k, v in filters.items() if k not in {"qc", "compare_period"}}
                    for filters in [selected_filters, comparison_filters]]
    selected_rates, comparison_rates = [_rates(apply_filters(base, filters)[0]) for filters in rate_filters]
    rate_rows = []
    for identity in sorted(selected_rates.keys() | comparison_rates.keys()):
        left, right = _rate(selected_rates.get(identity, {})), _rate(comparison_rates.get(identity, {}))
        difference = _rate_difference(left, right)
        rate_rows.append({"group": _label(identity), "selected": left, "comparison": right,
                          "difference_pp": float(round(difference, 2)) if difference is not None else None,
                          "direction": "unavailable" if difference is None else "increase" if difference > 0 else "decrease" if difference < 0 else "unchanged",
                          "selected_checks": f"{left['failed']}/{left['assessed']}", "comparison_checks": f"{right['failed']}/{right['assessed']}",
                          "selected_rate": left["failure_rate"], "comparison_rate": right["failure_rate"],
                          "unassessed": f"{left['unassessed']} / {right['unassessed']}"})
    # Rank all groups before applying the display limit. Exact fractions avoid
    # choosing the wrong largest difference after percentage rounding.
    rate_rows.sort(key=lambda row: (row["difference_pp"] is None,
                                   -abs(_rate_difference(row["selected"], row["comparison"]) or 0), row["group"]))
    numeric_scopes = [apply_filters(base, filters)[0] for filters in [selected_filters, comparison_filters]]
    (selected_numeric, selected_valid), (comparison_numeric, comparison_valid) = [_numeric(queryset) for queryset in numeric_scopes]
    numeric_rows = []
    for identity in sorted(selected_numeric.keys() | comparison_numeric.keys()):
        left, right = selected_numeric.get(identity, {}), comparison_numeric.get(identity, {})
        with localcontext() as decimal_context:
            decimal_context.prec = 32
            difference = (left["_mean"] - right["_mean"]) if left.get("_mean") is not None and right.get("_mean") is not None else None
        direction = "unavailable" if difference is None else "increase" if difference > 0 else "decrease" if difference < 0 else "unchanged"
        left.pop("_mean", None)
        right.pop("_mean", None)
        numeric_rows.append({"group": _label(identity[:3]), "unit": identity[3] or "(unit not recorded)",
                             "mean_difference": format(difference if difference else Decimal(0), ".8g") if difference is not None else None,
                             "direction": direction,
                             "selected_n": left.get("n", 0), "comparison_n": right.get("n", 0),
                             **{f"{side}_{key}": stats.get(key) for side, stats in [("selected", left), ("comparison", right)]
                                for key in ["mean", "min", "max"]},
                             "selected": left, "comparison": right})
    numeric_rows.sort(key=lambda row: (row["mean_difference"] is None, row["group"], row["unit"]))
    notes = ["Each group shares an analysis code, work type and result key. These are descriptive recorded-data summaries, not evidence of causality or statistical significance.",
             "Windows may overlap and have different durations. Rates describe QC checks; human review rejection is a separate decision.",
             f"Showing up to {GROUP_LIMIT} groups in each table; all matching records contribute to each displayed group."]
    rate_table = {"title": "QC failure rates among assessed checks", "columns": [
        {"key": "group", "label": "Analysis / work type / key"}, {"key": "selected_checks", "label": "Selected failed / assessed"},
        {"key": "selected_rate", "label": "Selected failure rate", "format": "percent"},
        {"key": "comparison_checks", "label": "Comparison failed / assessed"},
        {"key": "comparison_rate", "label": "Comparison failure rate", "format": "percent"},
        {"key": "difference_pp", "label": "Difference (percentage points)", "format": "number"},
        {"key": "unassessed", "label": "Unassessed (selected / comparison)"}], "rows": rate_rows[:GROUP_LIMIT],
        "notes": ["The QC status filter is removed only for this rate denominator. Date, instrument, operator and key filters remain. A zero assessed denominator has no rate.",
                  "Ranked by absolute failure-rate difference across all groups before the display limit; differences use unrounded proportions. Rounding can hide changes below 0.01 percentage points.", *notes]}
    numeric_table = {"title": "Numeric results in compatible units", "columns": [
        {"key": "group", "label": "Analysis / work type / key"}, {"key": "unit", "label": "Summary unit"},
        *[{"key": f"{side}_{key}", "label": f"{label} {key}"} for side, label in [("selected", "Selected"), ("comparison", "Comparison")]
          for key in ["n", "mean", "min", "max"]], {"key": "mean_difference", "label": "Mean difference (selected minus comparison)"}], "rows": numeric_rows[:GROUP_LIMIT],
        "notes": ["Numeric summaries keep the selected QC filter. Only finite NUMBER values contribute. Known mass, volume and mass-concentration units are converted; other exact units stay separate. Missing units show counts only because compatibility cannot be established.",
                  "n counts recorded numeric values, including repeated measurements of the same sample.",
                  "Groups with paired means appear first, then analysis/work type/key/unit order. Changes across different groups or units are not ranked against each other.",
                  f"Excluded nonnumeric, missing or nonfinite values: selected {numeric_scopes[0].count() - selected_valid}; comparison {numeric_scopes[1].count() - comparison_valid}.", *notes]}
    return {"rates": rate_rows[:GROUP_LIMIT], "numeric": numeric_rows[:GROUP_LIMIT], "rate_groups": len(rate_rows),
            "numeric_groups": len(numeric_rows), "numeric_comparable_groups": sum(row["mean_difference"] is not None for row in numeric_rows),
            "unassessed": {"selected": sum(row["unassessed"] for row in selected_rates.values()),
                           "comparison": sum(row["unassessed"] for row in comparison_rates.values())}}, [rate_table, numeric_table]
