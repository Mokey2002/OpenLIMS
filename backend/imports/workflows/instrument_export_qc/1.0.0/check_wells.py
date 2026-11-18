import json
import re
from pathlib import Path


def check_wells(export):
    plate_size = export["parameters"]["plate_size"]
    if plate_size is None:
        return []

    letters, columns = ("ABCDEFGH", 12) if plate_size == 96 else ("ABCDEFGHIJKLMNOP", 24)
    expected = [f"{letter}{column}" for letter in letters for column in range(1, columns + 1)]
    expected_set = set(expected)
    seen = set()
    issues = []
    for row_number, row in enumerate(export["rows"], start=1):
        match = re.fullmatch(r"([A-P])([0-9]{1,2})", row["well"].upper())
        well = f"{match[1]}{int(match[2])}" if match else ""
        if well not in expected_set:
            issues.append({
                "type": "INVALID_WELL",
                "data_row": row_number,
                "well": "",
                "detail": f"Enter a valid well for a {plate_size}-well plate.",
            })
        elif well in seen:
            issues.append({
                "type": "DUPLICATE_WELL",
                "data_row": row_number,
                "well": well,
                "detail": "This well already appears earlier in the export.",
            })
        else:
            seen.add(well)

    for well in expected:
        if well not in seen:
            issues.append({
                "type": "MISSING_WELL",
                "data_row": None,
                "well": well,
                "detail": "The export has no row for this well.",
            })
    return issues


export = json.loads(Path(snakemake.input[0]).read_text(encoding="utf-8"))
Path(snakemake.output[0]).write_text(json.dumps(check_wells(export)), encoding="utf-8")
