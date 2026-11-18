import json
from collections import Counter
from importlib.metadata import version
from pathlib import Path


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


export = load(snakemake.input.export)
issues = load(snakemake.input.readings) + load(snakemake.input.wells)
counts = Counter(issue["type"] for issue in issues)
report = {
    "engine_version": version("snakemake"),
    "summary": {
        "outcome": "NEEDS_REVIEW" if issues else "PASS",
        "rows_checked": len(export["rows"]),
        "invalid_readings": counts["INVALID_READING"],
        "invalid_wells": counts["INVALID_WELL"],
        "duplicate_wells": counts["DUPLICATE_WELL"],
        "missing_wells": counts["MISSING_WELL"],
    },
    "issues": issues,
}
Path(snakemake.output[0]).write_text(json.dumps(report), encoding="utf-8")
