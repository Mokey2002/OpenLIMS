import hashlib
import json

from .models import ImportRowReceipt


def row_identity(job, row):
    external_id = str(row.get("external_id") or "").strip()
    if not external_id or len(external_id) > 128:
        raise ValueError("Provide an external_id between 1 and 128 characters.")
    values = {
        key: str(value).strip() if value is not None else ""
        for key, value in row.items()
        if key is not None and key != "external_id"
    }
    encoded = json.dumps([job.project_id, values], sort_keys=True).encode()
    return external_id, hashlib.sha256(encoded).hexdigest()


def classify_receipt(receipt, fingerprint):
    if receipt.fingerprint == fingerprint:
        return "IDENTICAL", "Identical external row already imported."
    return "CONFLICT", "External ID already has different data. Review the source row."


def claim_row(job, row, row_number):
    external_id, fingerprint = row_identity(job, row)
    receipt, created = ImportRowReceipt.objects.get_or_create(
        instrument_id=job.instrument_id,
        source_system=job.summary["tabular"]["source_system"],
        external_id=external_id,
        defaults={"fingerprint": fingerprint, "job": job, "row_number": row_number},
    )
    if created:
        return "IMPORTED", "", receipt
    status, reason = classify_receipt(receipt, fingerprint)
    return status, reason, receipt
