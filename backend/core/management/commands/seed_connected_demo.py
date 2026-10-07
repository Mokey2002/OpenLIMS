"""A non-destructive, single-sample walkthrough for the five demo identities."""
import hashlib
from io import BytesIO

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.management.commands.seed_demo import build_demo_chromatogram, build_demo_features, ensure_sequence_revision

CODE = "DEMO-360"
SAMPLE = "DEMO-360-001"
MARKER = "seed_connected_demo:v1"
DISCLAIMER = "SYNTHETIC DEMO / DEMOSTRACIÓN FICTICIA — not experimental evidence."
ROLES = {
    "director": "Review the project, templates and final report; manage access.",
    "peter": "Extraction is recorded. Finish PCR: enter amplification_status = PASS, then complete the work item.",
    "maria": "Review Michael's sequence QC work item and approve it with a reason. QC approval and work completion are separate.",
    "michael": "Sequence QC is recorded and awaits Maria. After PCR and QC approval, enter interpretation = PASS and complete interpretation.",
    "viewer": "Read the sample, experiment, files and report. Verify that editing and QC approval are unavailable.",
}


class Command(BaseCommand):
    help = "Create DEMO-360-001 and a five-user walkthrough; preserve existing data and credentials."

    @transaction.atomic
    def handle(self, *args, **options):
        from alignments.models import AlignmentJob
        from assistant.models import BarcodeLabel, SOPDocument
        from blast.models import BlastDatabase, BlastJob
        from core.models import SharedAttachment
        from custom_fields.models import SampleForm
        from events.models import Event
        from imports.models import ImportJob, InstrumentProfile
        from inventory.models import Container, InventoryItem, InventoryLot, InventoryReservation, Location
        from mass_spec.models import MassSpecRun
        from notebook.models import ExperimentTemplate, Notebook
        from notebook.services import instantiate_template
        from notifications.models import Notification
        from pipelines.models import AnalysisDefinition, PipelineTemplate, PipelineTemplateStep, ProcedureDefinition
        from pipelines.services import start_pipeline, sync_pipeline_step_from_work_item
        from projects.models import Project, ProjectPost
        from registry.models import RegistryRecord, RegistryRecordVersion, RegistrySchema
        from results.models import Result, WorkItem
        from samples.models import Sample, SampleCustodyEvent, SampleRelationship
        from sequences.models import Sequence
        from workflow_requests.models import AssayRequestType, WorkflowRequest, WorkflowRequestItem

        existing = Project.objects.filter(code=CODE).first()
        if existing:
            if existing.description.startswith(MARKER) and Sample.objects.filter(project=existing, sample_id=SAMPLE).exists():
                self.stdout.write(f"{SAMPLE} already exists. All edits, assignments and membership preserved.")
                return
            raise CommandError("DEMO-360 conflicts with existing data; nothing changed.")
        users = {u.username: u for u in get_user_model().objects.filter(username__in=ROLES, is_active=True)}
        missing = set(ROLES) - set(users)
        if missing:
            raise CommandError("Existing active demo users required: " + ", ".join(sorted(missing)) + ". Provision the demo identities first; this command never changes accounts.")
        required = {"director": "admin", "peter": "tech", "maria": "qc_reviewer", "michael": "tech", "viewer": "viewer"}
        for username, role in required.items():
            if not users[username].groups.filter(name=role).exists() and not (username == "director" and users[username].is_superuser):
                raise CommandError(f"{username} needs its existing {role} role; no roles were changed.")
        if users["viewer"].is_staff or users["viewer"].is_superuser or users["viewer"].groups.filter(name__in=["admin", "tech", "qc_reviewer"]).exists():
            raise CommandError("viewer must be read-only for this walkthrough; no roles were changed.")
        if Sample.objects.filter(sample_id__in=[SAMPLE, SAMPLE + "-A"]).exists():
            raise CommandError("Reserved sample IDs are already in use; nothing changed.")
        director, peter, maria, michael = (users[name] for name in ("director", "peter", "maria", "michael"))
        project = Project.objects.create(code=CODE, name="OpenLIMS 360 — one sample, five roles", description=MARKER + "\n" + DISCLAIMER)
        project.members.add(*users.values())
        form = SampleForm.objects.create(code=CODE, name_en="Connected demo sample", name_es="Muestra de demostración", published=True,
            fields=[{"key": "synthetic", "type": "boolean", "en": "Synthetic", "es": "Ficticia"},
                    {"key": "purpose", "type": "text", "en": "Purpose", "es": "Objetivo"}])
        location = Location.objects.create(code=CODE, name="DEMO-360 freezer", kind="freezer", project=project)
        box = Container.objects.create(container_id=CODE, kind="box", location=location)
        sample = Sample.objects.create(sample_id=SAMPLE, project=project, sample_type=form.code, container=box,
            created_by=peter, assigned_to=peter, status="IN_PROGRESS", form_values={"synthetic": True, "purpose": "Complete product walkthrough"})
        aliquot = Sample.objects.create(sample_id=SAMPLE + "-A", project=project, sample_type=form.code, container=box, created_by=peter)
        SampleRelationship.objects.create(source_sample=sample, derived_sample=aliquot, relationship_type="ALIQUOT", created_by=peter, reason="Synthetic aliquot to demonstrate lineage.")
        BarcodeLabel.objects.create(sample=sample, barcode=SAMPLE)
        SampleCustodyEvent.objects.create(sample=sample, action="MOVE", to_container=box, performed_by=peter, reason="Synthetic receipt and storage example.")
        item = InventoryItem.objects.create(code=CODE, name="DEMO-360 reagent", default_unit="uL")
        lot = InventoryLot.objects.create(item=item, lot_code=CODE, quantity=200, unit="uL", location=location, container=box)
        InventoryReservation.objects.create(lot=lot, project=project, quantity=20, unit="uL", created_by=peter)
        sop = SOPDocument.objects.create(document_code=CODE, title="DEMO-360 walkthrough SOP", version="1", section="Walkthrough", content=DISCLAIMER + "\n" + "\n".join(f"{k}: {v}" for k, v in ROLES.items()), project=project, uploaded_by=director)
        template = PipelineTemplate.objects.create(code=CODE, name="DEMO-360 extraction to interpretation", active=True, created_by=director)
        definitions = [("Extraction", "concentration", "NUMBER", [], False), ("PCR", "amplification_status", "STRING", [1], False),
                       ("Sequence QC", "quality_score", "NUMBER", [1], True), ("Interpretation", "interpretation", "STRING", [2, 3], False)]
        for pos, (name, key, value_type, dependencies, qc) in enumerate(definitions, 1):
            analysis = AnalysisDefinition.objects.create(code=f"{CODE}-{pos}", name=name, required_fields=[{"key": key, "value_type": value_type, "required": True}], created_by=director)
            procedure = ProcedureDefinition.objects.create(code=f"{CODE}-{pos}", name=name, version="1", analysis=analysis, created_by=director)
            PipelineTemplateStep.objects.create(template=template, position=pos, name=name, procedure=procedure, dependency_positions=dependencies, requires_qc=qc)
        run = start_pipeline(sample=sample, template=template, actor=director)
        extraction = run.steps.get(position=1).work_item
        instrument = InstrumentProfile.objects.create(code=CODE, name="DEMO-360 synthetic import", sample_id_column="sample_id")
        imported = ImportJob.objects.create(instrument=instrument, project=project, uploaded_by=peter, run_id=CODE, status="COMPLETED", summary={"synthetic": True, "note": "Prepared fixture; not a live instrument import."})
        extraction.source_import_job = imported
        extraction.assigned_to = peter
        Result.objects.create(work_item=extraction, key="concentration", value_type="NUMBER", value_number=43, unit="ng/uL", entered_by=peter)
        extraction.status = "COMPLETED"
        extraction.save()
        sync_pipeline_step_from_work_item(extraction, actor=peter)
        pcr = run.steps.get(position=2).work_item
        pcr.assigned_to = peter
        pcr.status = "IN_PROGRESS"
        pcr.save()
        qc = run.steps.get(position=3).work_item
        qc.assigned_to = michael
        Result.objects.create(work_item=qc, key="quality_score", value_type="NUMBER", value_number=98, entered_by=michael)
        qc.status = "COMPLETED"
        qc.save()
        sync_pipeline_step_from_work_item(qc, actor=michael)
        text = "ATGCGTACCGTAGGCTAACCGGTTACCGGATCGATCGTACGTAGCTAGCTAGGCTA"
        sequence = Sequence.objects.create(name="DEMO-360 synthetic sequence", sequence_type="DNA", sequence=text, project=project, sample=sample, created_by=michael, description=DISCLAIMER)
        ensure_sequence_revision(sequence, michael, "Synthetic fixture, not instrument output")
        reference = Sequence.objects.create(name="DEMO-360 synthetic reference", sequence_type="DNA", sequence=text[:-1] + "T", project=project, created_by=michael, description=DISCLAIMER)
        ensure_sequence_revision(reference, michael, "Synthetic comparison reference")
        fasta = f">demo\n{text}\n>reference\n{reference.sequence}\n"
        alignment = AlignmentJob.objects.create(name="DEMO-360 simulated alignment", project=project, created_by=michael, status="COMPLETED", input_fasta=fasta, aligned_fasta=fasta, summary={"synthetic": True, "note": "Prepared fixture, not an executed alignment."})
        alignment.sequences.set([sequence, reference])
        database = BlastDatabase.objects.create(name=CODE, description=DISCLAIMER, database_type="DNA", created_by=director, status="NEW")
        BlastJob.objects.create(name="DEMO-360 search setup (not executed)", project=project, query_sequence=sequence, database=database, created_by=michael, query_fasta=f">demo\n{text}\n")
        points, features = build_demo_chromatogram(), build_demo_features()
        MassSpecRun.objects.create(name="DEMO-360 simulated MS", project=project, sample=sample, uploaded_by=michael, status="COMPLETED",
            original_filename="Synthetic summary — no raw acquisition", chromatogram_data=points, detected_features=features,
            feature_count=len(features), spectra_count=len(points), openms_summary={"synthetic": True, "note": DISCLAIMER})
        schema = RegistrySchema.objects.create(code=CODE.lower(), name="DEMO-360 material", entity_type="plasmid", id_prefix="D360", created_by=director)
        record = RegistryRecord.objects.create(registry_id=CODE, schema=schema, name="DEMO-360 synthetic construct", project=project, owner=peter, description=DISCLAIMER)
        version = RegistryRecordVersion.objects.create(record=record, schema=schema, version=1, data={"synthetic": True}, sequence_revision=sequence.current_revision, created_by=peter)
        record.current_version = version
        record.save(update_fields=["current_version"])
        notebook = Notebook.objects.create(name="DEMO-360 team notebook", project=project, scope="PROJECT", owner=director, description=DISCLAIMER)
        notebook.editors.add(peter, maria, michael)
        notebook.readers.add(users["viewer"])
        notebook.reviewers.add(maria, director)
        notebook.lockers.add(director)
        steps = [{"name": "Document results", "assignee": peter.pk, "fields": [{"key": "observations", "label": "Observations", "type": "STRING", "required": True}]},
                 {"name": "Review interpretation", "assignee": maria.pk, "fields": [{"key": "accepted", "label": "Accepted", "type": "BOOLEAN", "required": True, "equals": True}]}]
        blocks = [{"block_type": "HEADING", "data": {"text": "Start here: DEMO-360-001"}},
                  {"block_type": "RICH_TEXT", "data": {"text": DISCLAIMER}},
                  {"block_type": "TABLE", "data": {"rows": [["User", "Next action"]] + [[k, v] for k, v in ROLES.items()]}}]
        exp_template = ExperimentTemplate.objects.create(notebook=notebook, name="DEMO-360 reusable review", blocks=blocks, workflow_steps=steps, created_by=director)
        linked = [sample, sequence, record, lot, run, sop]
        types = ["sample", "sequence", "registry_record", "inventory_lot", "pipeline_run", "sop_document"]
        experiment = instantiate_template(exp_template, director, title="DEMO-360 live team walkthrough", assignees=[peter, maria, michael],
            links=[{"entity_type": kind, "public_id": str(obj.public_id), "relation_type": "demo_input"} for kind, obj in zip(types, linked)])
        request_type = AssayRequestType.objects.create(code=CODE, name="DEMO-360 sequencing service")
        request = WorkflowRequest.objects.create(request_number=CODE, request_type=request_type, project=project, requester=peter,
            title="DEMO-360 service request (draft)", assigned_pipeline=template, form_data={"synthetic": True})
        WorkflowRequestItem.objects.create(request=request, sample=sample, notes="Review this draft; approving may create a separate pipeline run.")
        # Real files, explicitly synthetic. File creation is tracked for cleanup on failure.
        self.saved_files = []
        try:
            database.source_fasta.save("DEMO-360-reference.fasta", ContentFile(f">demo_reference synthetic\n{reference.sequence}\n".encode()), save=True)
            self.saved_files.append((database.source_fasta.storage, database.source_fasta.name))
            imported.uploaded_file.save("DEMO-360-import.csv", ContentFile(b"sample_id,concentration\nDEMO-360-001,43\n"), save=True)
            self.saved_files.append((imported.uploaded_file.storage, imported.uploaded_file.name))
            def attachment(name, content, media_type):
                obj = SharedAttachment.objects.create(target_content_type=ContentType.objects.get_for_model(sample), target_object_id=str(sample.pk),
                    project=project, display_name=name, media_type=media_type, size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(), uploaded_by=director, description=DISCLAIMER)
                obj.file.save(name, ContentFile(content), save=True)
                self.saved_files.append((obj.file.storage, obj.file.name))
            attachment("DEMO-360-results.csv", b"sample_id,concentration,quality_score,synthetic\nDEMO-360-001,43,98,true\n", "text/csv")
            attachment("DEMO-360-sequence.fasta", f">DEMO-360-001 synthetic\n{text}\n".encode(), "text/plain")
            guide = DISCLAIMER + "\n\n" + "\n\n".join(f"{k}: {v}" for k, v in ROLES.items())
            attachment("DEMO-360-walkthrough.txt", guide.encode(), "text/plain")
            from reportlab.pdfgen import canvas
            pdf = BytesIO()
            report = canvas.Canvas(pdf)
            for i, line in enumerate(["DEMO-360 sample summary — SYNTHETIC", "Sample: " + SAMPLE, "Concentration: 43 ng/uL", "Sequence quality: 98; QC approval pending", "Not a final approved report; training fixture only."]):
                report.drawString(40, 800 - i * 24, line)
            report.save()
            attachment("DEMO-360-summary.pdf", pdf.getvalue(), "application/pdf")
            for username, user in users.items():
                Notification.objects.create(user=user, title="DEMO-360: your walkthrough", message=ROLES[username], link=f"/samples/{sample.pk}")
            ProjectPost.objects.create(project=project, author=director, note=guide)
            Event.objects.create(entity_type="Sample", entity_id=str(sample.pk), action="CONNECTED_DEMO_CREATED", actor=director,
                payload={"synthetic": True, "marker": MARKER, "experiment_id": experiment.pk, "sample_id": sample.pk})
        except Exception:
            for storage, name in self.saved_files:
                storage.delete(name)
            raise
        self.stdout.write(self.style.SUCCESS(f"Created {SAMPLE}: /samples/{sample.pk} | project /projects/{project.pk}"))
        self.stdout.write("All five users have project access and an in-app walkthrough notification. No credentials, global flags or email changed.")
        self.stdout.write("BLAST is a setup example, not an executed search. Enable relevant feature flags through Settings if hidden.")
