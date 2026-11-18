import io
import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import Group
from rest_framework.test import APIClient

from imports.models import InstrumentProfile, InstrumentColumnMapping, ImportJob
from samples.models import Sample
from results.models import WorkItem
from imports.tasks import process_import_job

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user():
    user = User.objects.create_user(username="admin1", password="pass123")
    group, _ = Group.objects.get_or_create(name="admin")
    user.groups.add(group)
    return user


@pytest.fixture
def client(admin_user):
    client = APIClient()
    client.force_authenticate(user=admin_user)
    return client


@pytest.fixture
def instrument():
    profile = InstrumentProfile.objects.create(
        name="NovaFlex",
        code="NOVAFLEX",
        delimiter=",",
        has_header=True,
        sample_id_column="sample_id",
    )

    InstrumentColumnMapping.objects.create(
        instrument=profile,
        source_column="concentration",
        target_key="concentration",
        value_type="NUMBER",
    )

    return profile


def test_csv_import_workflow(client, instrument):
    csv_content = b"sample_id,concentration\nS-CSV-001,14.5\n"
    upload = SimpleUploadedFile("test.csv", csv_content, content_type="text/csv")

    response = client.post(
        "/api/import-jobs/",
        {
            "instrument": instrument.id,
            "uploaded_file": upload,
        },
        format="multipart",
    )

    assert response.status_code in (200, 201)

    job = ImportJob.objects.first()
    process_import_job(job.id)
    job.refresh_from_db()
    assert job.status == "COMPLETED"
    assert Sample.objects.filter(sample_id="S-CSV-001").exists()
    work_item = WorkItem.objects.get(sample__sample_id="S-CSV-001")
    assert work_item.source_import_job_id == job.id

    detail = client.get(f"/api/import-jobs/{job.id}/")
    assert detail.status_code == 200
    assert detail.json()["linked_sample_count"] == 1
    assert detail.json()["linked_work_item_count"] == 1
    assert detail.json()["linked_result_count"] == 1


def test_workbook_staging_and_external_retries(client, instrument, settings):
    from openpyxl import Workbook

    from imports.models import ImportRowReceipt

    workbook = Workbook()
    workbook.active.title = "Notes"
    sheet = workbook.create_sheet("Results")
    sheet.append(["sample_id", "external_id", "concentration"])
    sheet.append(["S-EXCEL", "a", 14.5])
    sheet.append(["S-EXCEL", "a", 14.5])
    sheet.append(["S-EXCEL", "a", 23])
    sheet.append(["S-EXCEL", "b", "invalid"])
    content = io.BytesIO()
    workbook.save(content)

    def post(path, **extra):
        return client.post(
            f"/api/import-jobs/{path}",
            {
                "instrument": instrument.pk,
                "uploaded_file": SimpleUploadedFile("results.xlsx", content.getvalue()),
                "source_system": "exporter",
                **extra,
            },
            format="multipart",
        )

    response = post("preview/")
    assert response.json() == {"sheet_required": True, "sheets": ["Notes", "Results"]}
    assert post("").status_code == 400
    preview = post("preview/", sheet="Results")
    assert preview.status_code == 200
    assert [row["outcome"] for row in preview.json()["preview_rows"]] == [
        "READY", "IDENTICAL", "CONFLICT", "REJECTED",
    ]

    upload = post("", sheet="Results")
    assert upload.status_code == 201
    job_id = upload.json()["id"]
    report = process_import_job(job_id)["row_report"]
    assert [row["outcome"] for row in report] == ["IMPORTED", "IDENTICAL", "CONFLICT", "REJECTED"]
    assert client.post(f"/api/import-jobs/{job_id}/retry/", {}, format="json").status_code == 400

    ingest = client.post(
        "/api/import-jobs/instrument-ingest/",
        {
            "instrument_code": instrument.code,
            "run_id": "external-run",
            "source_system": "exporter",
            "rows": [{"sample_id": "S-EXCEL", "external_id": "a", "concentration": 14.5}],
        },
        format="json",
        HTTP_X_INSTRUMENT_API_KEY=settings.INSTRUMENT_API_KEY,
    )
    assert ingest.status_code == 201
    assert ingest.json()["row_report"][0]["outcome"] == "IDENTICAL"

    correction = {
        "corrections": [{"row": 4, "values": {
            "sample_id": "S-EXCEL", "external_id": "b", "concentration": "22",
        }}],
    }
    corrected = client.post(f"/api/import-jobs/{job_id}/retry/", correction, format="json")
    assert corrected.status_code == 202
    assert client.post(f"/api/import-jobs/{job_id}/retry/", correction, format="json").status_code == 400
    child_id = corrected.json()["id"]
    assert process_import_job(child_id)["row_report"][0]["row"] == 4
    assert ImportJob.objects.get(pk=job_id).summary["row_report"] == report
    assert client.post(f"/api/import-jobs/{job_id}/retry/", correction, format="json").status_code == 400
    assert ImportRowReceipt.objects.count() == 2
    assert WorkItem.objects.count() == 2


def test_receipts_roll_back_with_writes_when_worker_fails(client, instrument, monkeypatch):
    from imports.models import ImportRowReceipt
    from results.models import Result

    response = client.post(
        "/api/import-jobs/",
        {
            "instrument": instrument.pk,
            "source_system": "exporter",
            "uploaded_file": SimpleUploadedFile(
                "results.csv", b"sample_id,external_id,concentration\nS-ROLLBACK,one,14.5\n",
            ),
        },
        format="multipart",
    )
    assert response.status_code == 201
    job_id = response.json()["id"]

    def fail(**kwargs):
        raise RuntimeError("Simulated result write failure")

    with monkeypatch.context() as patch:
        patch.setattr(Result.objects, "update_or_create", fail)
        with pytest.raises(RuntimeError, match="Simulated result write failure"):
            process_import_job(job_id)

    assert ImportJob.objects.get(pk=job_id).status == "FAILED"
    assert not Sample.objects.filter(sample_id="S-ROLLBACK").exists()
    assert not ImportRowReceipt.objects.exists()
    retry = client.post(f"/api/import-jobs/{job_id}/retry/", {}, format="json")
    assert retry.status_code == 202
    assert process_import_job(job_id)["row_report"][0]["outcome"] == "IMPORTED"
    assert WorkItem.objects.count() == ImportRowReceipt.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_overlapping_jobs_claim_external_rows_once(instrument):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import connections

    from imports.models import ImportRowReceipt

    header = b"sample_id,external_id,concentration\n"
    first = b"S-CONCURRENT,a,14.5\n"
    second = b"S-CONCURRENT,b,23\n"

    def create_job(content):
        return ImportJob.objects.create(
            instrument=instrument,
            uploaded_file=SimpleUploadedFile("overlap.csv", header + content),
            summary={"tabular": {"source_system": "exporter"}},
        )

    jobs = [create_job(first + second), create_job(second + first)]
    barrier = Barrier(2)

    def run(job_id):
        try:
            barrier.wait(timeout=10)
            return process_import_job(job_id)["row_report"]
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        reports = list(executor.map(run, [job.pk for job in jobs]))

    assert sorted(row["outcome"] for report in reports for row in report) == [
        "IDENTICAL", "IDENTICAL", "IMPORTED", "IMPORTED",
    ]
    assert ImportRowReceipt.objects.count() == WorkItem.objects.count() == 2
