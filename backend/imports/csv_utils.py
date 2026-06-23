import csv
import io


def _non_empty_lines(decoded):
    return [line for line in decoded.splitlines() if line.strip()]


def detect_header_row_index(decoded, instrument, max_scan_rows=50):
    """
    Find the row containing the configured sample_id_column.
    Returns zero-based row index or None.
    """
    lines = _non_empty_lines(decoded)
    sample_id_column = str(instrument.sample_id_column or "").strip()

    if not sample_id_column:
        return None

    for index, line in enumerate(lines[:max_scan_rows]):
        columns = [
            column.strip()
            for column in next(
                csv.reader([line], delimiter=instrument.delimiter),
                [],
            )
        ]

        if sample_id_column in columns:
            return index

    return None


def get_csv_dict_reader(decoded, instrument):
    """
    Supports instrument exports with metadata rows before the real CSV header.

    Example:
      Instrument: XYZ
      Run ID: 123
      Operator: Peter

      sample_id,result
      S-001,pass

    If auto_detect_header is true, the parser finds the row containing
    instrument.sample_id_column. Otherwise it uses instrument.header_row_index.
    """
    lines = _non_empty_lines(decoded)

    if not lines:
        raise ValueError("Uploaded CSV file has no readable rows.")

    header_row_index = instrument.header_row_index or 0

    if getattr(instrument, "auto_detect_header", False):
        detected = detect_header_row_index(decoded, instrument)

        if detected is not None:
            header_row_index = detected

    if header_row_index >= len(lines):
        raise ValueError(
            "Header row index is beyond the number of readable rows in the file."
        )

    csv_text = "\n".join(lines[header_row_index:])

    reader = csv.DictReader(
        io.StringIO(csv_text),
        delimiter=instrument.delimiter,
    )

    fieldnames = reader.fieldnames or []

    if instrument.sample_id_column not in fieldnames:
        raise ValueError(
            f"Could not find sample ID column '{instrument.sample_id_column}' "
            f"in detected CSV header. Found columns: {', '.join(fieldnames) or 'none'}."
        )

    return reader, {
        "header_row_index": header_row_index,
        "detected_header_row": header_row_index,
        "skipped_metadata_rows": header_row_index,
        "fieldnames": fieldnames,
    }
