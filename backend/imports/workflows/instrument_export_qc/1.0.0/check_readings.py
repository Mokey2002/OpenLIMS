import json
import math
from pathlib import Path


export = json.loads(Path(snakemake.input[0]).read_text(encoding="utf-8"))
issues = []
for row_number, row in enumerate(export["rows"], start=1):
    reading = row["reading"]
    try:
        valid = math.isfinite(float(reading))
    except ValueError:
        valid = False
    if not valid:
        issues.append({
            "type": "INVALID_READING",
            "data_row": row_number,
            "well": "",
            "detail": "Enter a finite numeric reading." if reading else "The reading is blank.",
        })

Path(snakemake.output[0]).write_text(json.dumps(issues), encoding="utf-8")
