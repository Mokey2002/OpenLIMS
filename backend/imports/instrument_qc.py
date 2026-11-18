"""Stage a completed instrument export and run the bundled QC workflow."""
import csv
import hashlib
import json
import logging
import os
import signal
import subprocess
import time
from collections import Counter
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.conf import settings
from django.utils import timezone

from core.permissions import is_admin, is_tech
from core.upload_validators import MAX_UPLOAD_SIZE_BYTES
from projects.access import get_project_access_queryset

from .models import ImportJob, InstrumentQCRun
from .tabular import read_tabular

WORKFLOW_VERSION = "1.0.0"
ENGINE_VERSION = "9.14.6"
WORKFLOWS = Path(__file__).parent / "workflows" / "instrument_export_qc"
ACTIVE_STATUSES = (InstrumentQCRun.QUEUED, InstrumentQCRun.RUNNING)
QUEUE_TIMEOUT = timedelta(minutes=15)
RUN_SECONDS = 90
RUN_TIMEOUT = timedelta(seconds=RUN_SECONDS + 30)
TIMEOUT_MESSAGE = "The analysis timed out. Check that the instrument QC worker is running, then retry."
logger = logging.getLogger(__name__)


def available_input(job):
    metadata = job.summary.get("csv_metadata", {})
    fields = metadata.get("fieldnames", [])
    if (
        job.status != "COMPLETED" or job.source_type != "UPLOAD"
        or not job.uploaded_file or job.summary.get("assistant_upload") or not fields
    ):
        return None

    counts = Counter(fields)
    columns = [field for field in fields if field.strip() and len(field) <= 256 and counts[field] == 1]
    if not columns:
        return None

    numeric_columns = list(job.instrument.column_mappings.filter(
        value_type="NUMBER", source_column__in=columns,
    ).values_list("source_column", flat=True)[:2])
    return {
        "filename": Path(job.uploaded_file.name).name,
        "sheet": metadata.get("sheet"),
        "columns": columns,
        "default_reading_column": numeric_columns[0] if len(numeric_columns) == 1 else "",
        "default_well_column": next(
            (column for column in columns if column.strip().lower() in {"well", "well_id", "well position"}), "",
        ),
    }


def snapshot_export(job, parameters):
    metadata = job.summary["csv_metadata"]
    source_format = SimpleNamespace(
        delimiter=metadata.get("delimiter", job.instrument.delimiter),
        sample_id_column=parameters["reading_column"],
        header_row_index=metadata["header_row_index"],
        auto_detect_header=False,
    )
    try:
        if job.uploaded_file.size > MAX_UPLOAD_SIZE_BYTES:
            raise ValueError("The saved export exceeds 10 MB.")
        with job.uploaded_file.open("rb") as upload:
            rows, parsed = read_tabular(upload, source_format, metadata.get("sheet"))
    except (OSError, ValueError, csv.Error) as exc:
        raise ValueError("Could not read the saved export. Check the file and retry.") from exc
    if (
        rows is None or parsed["fieldnames"] != metadata["fieldnames"]
        or len(rows) != job.summary.get("rows_processed")
    ):
        raise ValueError("The saved export no longer matches the completed import.")
    if not rows:
        raise ValueError("The export has no data rows to check.")

    return {
        "import_id": job.pk,
        "filename": Path(job.uploaded_file.name).name,
        "sheet": parsed.get("sheet"),
        "parameters": parameters,
        "rows": [
            {
                "reading": (row.get(parameters["reading_column"]) or "").strip(),
                "well": (row.get(parameters["well_column"]) or "").strip() if parameters["well_column"] else "",
            }
            for row in rows
        ],
    }


def encode_input(snapshot):
    return json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")


def workflow_digest(version):
    files = sorted((WORKFLOWS / version).iterdir())
    digest = hashlib.sha256()
    for path in files:
        if path.is_file():
            digest.update(path.name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def user_can_run_qc(user, job_id):
    return bool(
        user and user.is_active and (is_admin(user) or is_tech(user))
        and get_project_access_queryset(
            ImportJob.objects.filter(pk=job_id), user, owner_lookup="uploaded_by",
        ).exists()
    )


def expired(run, now):
    return run.status in ACTIVE_STATUSES and run.deadline_at <= now


def serialize_run(run, now):
    timed_out = expired(run, now)
    return {
        "id": run.pk,
        "status": InstrumentQCRun.FAILED if timed_out else run.status,
        "message": TIMEOUT_MESSAGE if timed_out else run.progress_message,
        "workflow_version": run.workflow_version,
        "workflow_sha256": run.workflow_sha256,
        "input_sha256": run.input_sha256,
        "filename": run.input_metadata["filename"],
        "sheet": run.input_metadata["sheet"],
        "parameters": run.input_metadata["parameters"],
        "engine_version": run.engine_version or None,
        "summary": run.report_summary or None,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "retry_of": run.retry_of_id,
    }


def execute_workflow(run, on_reporting):
    """Execute fixed, local rules in a run-specific directory with a minimal environment."""
    input_bytes = encode_input({**run.input_metadata, "rows": run.input_rows})
    if hashlib.sha256(input_bytes).hexdigest() != run.input_sha256:
        raise ValueError("The recorded analysis inputs have changed.")
    if workflow_digest(run.workflow_version) != run.workflow_sha256:
        raise ValueError("The recorded workflow definition is unavailable.")

    with TemporaryDirectory(prefix="openlims-qc-") as directory:
        work = Path(directory)
        (work / "input.json").write_bytes(input_bytes)
        command = [
            settings.SNAKEMAKE_EXECUTABLE,
            "--snakefile", str(WORKFLOWS / run.workflow_version / "Snakefile"),
            "--executor", "local", "--cores", "1", "--workflow-profile", "none",
        ]
        clean_env = {
            "HOME": directory,
            "TMPDIR": directory,
            "XDG_CACHE_HOME": directory,
            "LANG": "C.UTF-8",
            "PATH": os.defpath,
            "PYTHONNOUSERSITE": "1",
        }
        deadline = time.monotonic() + RUN_SECONDS
        reporting = False
        with (work / "snakemake.log").open("wb") as log:
            with subprocess.Popen(
                command, cwd=work, env=clean_env, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            ) as process:
                try:
                    while True:
                        try:
                            code = process.wait(timeout=0.5)
                            break
                        except subprocess.TimeoutExpired:
                            if time.monotonic() >= deadline:
                                raise TimeoutError("Instrument export QC exceeded 90 seconds.") from None
                            if not reporting and all((work / name).is_file() for name in ("readings.json", "wells.json")):
                                on_reporting()
                                reporting = True
                finally:
                    if process.poll() is None:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
        if code != 0:
            with (work / "snakemake.log").open("rb") as log:
                log.seek(max(0, log.seek(0, os.SEEK_END) - 4096))
                tail = log.read().decode("utf-8", errors="replace")
            logger.warning("Snakemake QC run %s exited with status %s.\n%s", run.pk, code, tail)
            raise RuntimeError("Check that the instrument QC worker has the bundled Snakemake version.")
        report = json.loads((work / "report.json").read_text(encoding="utf-8"))
        if report["engine_version"] != ENGINE_VERSION:
            raise RuntimeError("The instrument QC worker has a different Snakemake version.")
        return report
