import os
from django.core.exceptions import ValidationError


MAX_UPLOAD_SIZE_MB = 10
MAX_UPLOAD_SIZE_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024


def validate_uploaded_file(
    uploaded_file,
    allowed_extensions,
    max_size_bytes=MAX_UPLOAD_SIZE_BYTES,
):
    if not uploaded_file:
        raise ValidationError("No file was uploaded.")

    if uploaded_file.size == 0:
        raise ValidationError("Uploaded file is empty.")

    if uploaded_file.size > max_size_bytes:
        raise ValidationError(
            f"Uploaded file is too large. Max size is {max_size_bytes // (1024 * 1024)} MB."
        )

    filename = uploaded_file.name or ""
    extension = os.path.splitext(filename)[1].lower()

    if extension not in allowed_extensions:
        raise ValidationError(
            f"Unsupported file type '{extension}'. Allowed types: {', '.join(allowed_extensions)}."
        )

    return True


def validate_text_file(uploaded_file):
    try:
        uploaded_file.seek(0)
        uploaded_file.read().decode("utf-8")
        uploaded_file.seek(0)
    except UnicodeDecodeError:
        uploaded_file.seek(0)
        raise ValidationError("Unable to read uploaded file. Expected UTF-8 text.")

    uploaded_file.seek(0)
    return True


def validate_fasta_records(records, max_records=500):
    if not records:
        raise ValidationError("No FASTA records found.")

    if len(records) > max_records:
        raise ValidationError(f"Too many FASTA records. Max allowed is {max_records}.")

    seen_headers = set()
    invalid_records = []

    dna_chars = set("ACGTUN-")

    for index, record in enumerate(records, start=1):
        header = record.get("header", "").strip()
        sequence = record.get("sequence", "").strip().upper()

        if not header:
            invalid_records.append(f"Record {index}: missing FASTA header.")
            continue

        if header in seen_headers:
            invalid_records.append(f"Record {index}: duplicate FASTA header '{header}'.")
            continue

        seen_headers.add(header)

        if not sequence:
            invalid_records.append(f"Record {index}: empty sequence.")
            continue

        invalid_chars = sorted(set(sequence) - dna_chars)

        if invalid_chars:
            invalid_records.append(
                f"Record {index}: invalid sequence characters: {', '.join(invalid_chars)}."
            )

    if invalid_records:
        raise ValidationError(invalid_records)

    return True