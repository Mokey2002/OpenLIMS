import csv
from datetime import timedelta
from io import BytesIO, StringIO
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from openpyxl import Workbook

from imports.instrument_qc import ENGINE_VERSION
from imports.models import ImportJob, InstrumentQCRun
from imports.tasks import process_import_job, run_instrument_qc
from projects.models import Project
from results.models import Result

pytestmark = pytest.mark.django_db


@pytest.fixture
def completed_csv(settings, tmp_path, instrument_profile, tech_user, viewer_user):
    settings.MEDIA_ROOT = tmp_path
    project = Project.objects.create(code="QC", name="Instrument export checks")
    project.members.add(tech_user, viewer_user)
    job = ImportJob.objects.create(
        project=project, instrument=instrument_profile, uploaded_by=tech_user,
        uploaded_file=SimpleUploadedFile(
            "plate.csv",
            b"sample_id,well,reading\nQ-1,A01,4.5\nQ-2,a1,nan\nQ-3,Z9,\n",
        ),
    )
    process_import_job.run(job.pk)
    return ImportJob.objects.get(pk=job.pk)


@pytest.mark.parametrize("plate_size", [96, 384])
def test_export_qc_runs_with_snakemake(
    plate_size, completed_csv, tech_client, viewer_client, django_capture_on_commit_callbacks,
):
    job = completed_csv
    path = f"/api/import-jobs/{job.pk}/qc-runs/"
    columns = tech_client.get(path).json()["workflow"]
    assert columns["columns"] == ["sample_id", "well", "reading"]
    request = {"reading_column": "reading", "well_column": "well", "plate_size": plate_size}
    assert viewer_client.post(path, request, format="json").status_code == 403
    before_results = list(Result.objects.values())
    with patch("imports.tasks.run_instrument_qc.apply_async") as dispatch:
        with django_capture_on_commit_callbacks(execute=True):
            response = tech_client.post(path, request, format="json")
        assert response.status_code == 202
        run_id = response.json()["id"]
        dispatch.assert_called_once_with(args=(run_id,), retry=False)
    assert tech_client.post(path, request, format="json").status_code == 409
    assert tech_client.get(f"{path}{run_id}/report/").status_code == 404

    run_instrument_qc.run(run_id)
    run_instrument_qc.run(run_id)
    entry = viewer_client.get(path).json()["runs"][0]
    assert entry["status"] == "COMPLETED"
    assert entry["engine_version"] == ENGINE_VERSION
    assert entry["summary"] == {
        "outcome": "NEEDS_REVIEW", "rows_checked": 3, "invalid_readings": 2,
        "missing_wells": plate_size - 1, "duplicate_wells": 1, "invalid_wells": 1,
    }
    assert entry["input_sha256"] == response.json()["input_sha256"]
    assert "input_rows" not in entry
    report = viewer_client.get(f"{path}{run_id}/report/")
    assert report.status_code == 200
    assert report["Content-Disposition"].endswith(f'"instrument-qc-{run_id}.csv"')
    assert report["Cache-Control"] == "private, no-store"
    rows = list(csv.DictReader(StringIO(report.content.decode())))
    assert any(row["type"] == "DUPLICATE_WELL" and row["well"] == "A1" for row in rows)
    assert any(row["type"] == "INVALID_READING" and row["data_row"] == "2" for row in rows)
    assert list(Result.objects.values()) == before_results


def test_reviewed_excel_sheet_is_frozen_for_retry(
    settings, tmp_path, instrument_profile, admin_user, admin_client,
):
    settings.MEDIA_ROOT = tmp_path
    workbook = Workbook()
    workbook.active.title = "Ignored"
    workbook.active.append(["sample_id", "reading"])
    workbook.active.append(["Q-not-selected", "invalid"])
    sheet = workbook.create_sheet("Selected")
    sheet.append(["sample_id", "reading"])
    sheet.append(["Q-selected", 42])
    upload = BytesIO()
    workbook.save(upload)
    job = ImportJob.objects.create(
        instrument=instrument_profile, uploaded_by=admin_user,
        uploaded_file=SimpleUploadedFile("readings.xlsx", upload.getvalue()),
        summary={"tabular": {"sheet": "Selected"}},
    )
    process_import_job.run(job.pk)
    job.refresh_from_db()
    path = f"/api/import-jobs/{job.pk}/qc-runs/"
    response = admin_client.post(path, {"reading_column": "reading"}, format="json")
    assert response.status_code == 202
    original = InstrumentQCRun.objects.get(pk=response.json()["id"])
    assert original.input_metadata["sheet"] == "Selected"
    assert original.input_rows == [{"reading": "42", "well": ""}]

    with patch("imports.instrument_qc.execute_workflow", side_effect=TimeoutError):
        run_instrument_qc.run(original.pk)
    original.refresh_from_db()
    assert original.status == InstrumentQCRun.FAILED

    job.uploaded_file.delete(save=False)
    response = admin_client.post(f"{path}{original.pk}/retry/", {}, format="json")
    assert response.status_code == 202
    retry = InstrumentQCRun.objects.get(pk=response.json()["id"])
    assert retry.retry_of == original
    assert retry.input_sha256 == original.input_sha256
    assert retry.workflow_sha256 == original.workflow_sha256
    run_instrument_qc.run(retry.pk)
    retry.refresh_from_db()
    assert retry.report_summary["outcome"] == "PASS"
    assert retry.report_summary["rows_checked"] == 1
    assert b"PASS" in admin_client.get(f"{path}{retry.pk}/report/").content


def test_permissions_validation_and_abandoned_analysis(
    completed_csv, tech_client, tech_user, viewer_client, viewer_user, admin_client,
):
    job = completed_csv
    path = f"/api/import-jobs/{job.pk}/qc-runs/"
    assert admin_client.post(path, {"reading_column": "absent"}, format="json").status_code == 400
    assert tech_client.post(
        path, {"reading_column": "reading", "well_column": "well"}, format="json",
    ).status_code == 400
    response = tech_client.post(path, {"reading_column": "reading"}, format="json")
    assert response.status_code == 202
    run = InstrumentQCRun.objects.get(pk=response.json()["id"])
    run.deadline_at = timezone.now() - timedelta(seconds=1)
    run.save(update_fields=["deadline_at"])
    assert tech_client.get(path).json()["runs"][0]["status"] == "FAILED"
    retry = tech_client.post(f"{path}{run.pk}/retry/", {}, format="json")
    assert retry.status_code == 202
    run.refresh_from_db()
    assert run.status == InstrumentQCRun.FAILED

    job.project.members.remove(tech_user, viewer_user)
    with patch("imports.instrument_qc.execute_workflow") as execute:
        run_instrument_qc.run(retry.json()["id"])
    execute.assert_not_called()
    entry = admin_client.get(path).json()["runs"][0]
    assert entry["status"] == "FAILED"
    assert "lost access" in entry["message"]
    assert viewer_client.get(path).status_code == 404
    assert viewer_client.get(f"{path}{run.pk}/report/").status_code == 404


def test_dispatch_failure_leaves_analysis_safe_to_retry(
    completed_csv, tech_client, django_capture_on_commit_callbacks,
):
    path = f"/api/import-jobs/{completed_csv.pk}/qc-runs/"
    with patch("imports.tasks.run_instrument_qc.apply_async", side_effect=OSError):
        with django_capture_on_commit_callbacks(execute=True):
            response = tech_client.post(path, {"reading_column": "reading"}, format="json")
    assert response.status_code == 202
    run = InstrumentQCRun.objects.get(pk=response.json()["id"])
    assert run.status == InstrumentQCRun.FAILED
    assert tech_client.post(f"{path}{run.pk}/retry/", {}, format="json").status_code == 202
