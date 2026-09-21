"""One connected, entirely fictional project for a short live walkthrough."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from alignments.models import AlignmentJob
from core.management.commands.seed_demo import (
    build_demo_chromatogram, build_demo_features, ensure_sequence_revision,
)
from notebook.models import Experiment, Notebook
from notebook.services import create_revision
from projects.models import Project, ProjectPost
from results.models import Result, WorkItem
from samples.models import Sample, SampleBatch
from sequences.models import Sequence, SequenceFeature
from mass_spec.models import MassSpecRun
from custom_fields.models import SampleForm

CODE = "DEMO-AURORA"
NAME = "Aurora | Evaluación de pigmentos (DEMO)"
DISCLAIMER = "Datos totalmente ficticios / Entirely synthetic data. No representan resultados experimentales reales."
# Fixed fixture values, reused in the deck and walkthrough guide.
ROWS = [
    ("AUR-001", "Referencia", 1, 100, 98),
    ("AUR-002", "Referencia", 2, 104, 101),
    ("AUR-003", "Candidato A", 1, 148, 99),
    ("AUR-004", "Candidato A", 2, 152, 103),
    ("AUR-005", "Candidato B", 1, 176, 97),
    ("AUR-006", "Candidato B", 2, 181, 63),
]


class Command(BaseCommand):
    help = "Add a fictional Aurora project with samples, notebook and simulated results. Never sends email."

    def add_arguments(self, parser):
        parser.add_argument("--owner", required=True, help="Existing active username. No accounts or passwords are changed.")

    @transaction.atomic
    def handle(self, *args, **options):
        owner = get_user_model().objects.filter(username=options["owner"], is_active=True).first()
        if owner is None:
            raise CommandError("Owner must be an existing active user.")
        existing = Project.objects.filter(code=CODE).first()
        if existing:
            # A rerun must not reset records edited during a demonstration.
            if existing.name != NAME:
                raise CommandError("Project code DEMO-AURORA is already used by another project.")
            self.stdout.write("Aurora already exists; existing records and membership were preserved.")
            return
        if Project.objects.filter(name=NAME).exists() or Sample.objects.filter(sample_id__in=[r[0] for r in ROWS]).exists():
            raise CommandError("Aurora names or sample IDs are already in use. No data was changed.")
        if SampleForm.objects.filter(code="DEMO_PIGMENT").exists():
            raise CommandError("Sample form DEMO_PIGMENT already exists. No data was changed.")
        SampleForm.objects.create(code="DEMO_PIGMENT", name_en="Aurora synthetic sample", name_es="Muestra ficticia Aurora", published=True, fields=[
            {"key": "candidate", "type": "text", "en": "Candidate", "es": "Candidato"},
            {"key": "replicate", "type": "number", "en": "Replicate", "es": "Réplica"},
            {"key": "synthetic", "type": "boolean", "en": "Synthetic data", "es": "Datos ficticios"},
        ])
        project = Project.objects.create(code=CODE, name=NAME, description=DISCLAIMER + " Comparación de señales y revisión de QC. / Signal comparison and QC review.")
        project.members.add(owner)
        batch = SampleBatch.objects.create(code="B-AURORA-01", project=project)
        samples = []
        for sample_id, candidate, replicate, signal, recovery in ROWS:
            sample = Sample.objects.create(
                sample_id=sample_id, project=project, batch=batch, assigned_to=owner,
                sample_type="DEMO_PIGMENT", status="QC" if recovery < 80 else "REPORTED",
                form_values={"candidate": candidate, "replicate": replicate, "synthetic": True},
            )
            samples.append(sample)
            work = WorkItem.objects.create(
                sample=sample, name="Aurora: señal y QC (simulado)", work_type="DEMO_PIGMENT",
                status=WorkItem.STATUS_COMPLETED, created_by=owner, assigned_to=owner,
                qc_status=WorkItem.QC_RERUN_REQUIRED if recovery < 80 else WorkItem.QC_APPROVED,
                reviewed_by=owner, reviewed_at=timezone.now(), notes=DISCLAIMER,
                review_note="Repetición necesaria: recuperación 63%." if recovery < 80 else "Aceptado para este ejemplo ficticio.",
            )
            Result.objects.create(work_item=work, key="relative_signal", value_type="NUMBER", value_number=signal, unit="a.u.")
            Result.objects.create(
                work_item=work, key="spike_recovery_percent", value_type="NUMBER", value_number=recovery,
                unit="%", reference_min=80, reference_max=120, qc_passed=80 <= recovery <= 120,
                qc_rule="Demo only: 80–120% recovery", qc_failure_reason="63% is below 80%" if recovery < 80 else "",
            )
        WorkItem.objects.create(
            sample=samples[-1], name="Repetir QC de AUR-006 / Repeat QC", work_type="DEMO_QC_REPEAT",
            status=WorkItem.STATUS_PENDING, created_by=owner, assigned_to=owner,
            notes="Tarea de ejemplo. No se ejecuta ningún análisis automáticamente. / No analysis runs automatically.",
        )
        base = "ATGCGTACCGTAGGCTAACCGGTTACCGGATCGATCGTACGTAGCTAGCTAGGCTA"
        seqs = []
        for index, label in enumerate(("REF", "A", "B")):
            text = base if index == 0 else base[:20] + ("A" if index == 1 else "C") + base[21:]
            seq = Sequence.objects.create(
                name=f"AUR-{label} | fragmento sintético", sequence_type="DNA", sequence=text,
                project=project, sample=samples[index * 2], created_by=owner,
                description=DISCLAIMER + " Fragmento ilustrativo sin función biológica asignada.",
                source_metadata={"demo": True, "synthetic": True, "source": "seed_showcase"},
            )
            SequenceFeature.objects.create(sequence_record=seq, feature_type="ANNOTATION", name="Región de ejemplo / Example region", start=10, end=30, metadata={"synthetic": True})
            ensure_sequence_revision(seq, owner, "Synthetic showcase fixture")
            seqs.append(seq)
        fasta = "".join(f">AUR-{label}\n{seq.sequence}\n" for label, seq in zip(("REF", "A", "B"), seqs))
        alignment = AlignmentJob.objects.create(
            name="Aurora | alineamiento simulado", project=project, created_by=owner,
            status="COMPLETED", input_fasta=fasta, aligned_fasta=fasta,
            summary={"demo": True, "synthetic": True, "sequence_count": 3, "alignment_length": len(base), "note": "Prepared fixture, not a Clustal execution. One illustrative variable position."},
        )
        alignment.sequences.set(seqs)
        for sample, scale in zip((samples[0], samples[2], samples[4]), (1.0, 1.5, 1.75)):
            points = build_demo_chromatogram(scale=scale)
            features = build_demo_features(scale=scale)
            MassSpecRun.objects.create(
                name=f"Aurora {sample.sample_id} | MS simulado", project=project, sample=sample,
                uploaded_by=owner, status=MassSpecRun.STATUS_COMPLETED, processed_at=timezone.now(),
                uploaded_file="", original_filename="Synthetic summary (no raw file)",
                chromatogram_data=points, detected_features=features, feature_count=len(features),
                spectra_count=len(points), ms1_count=sum(p["ms_level"] == 1 for p in points),
                ms2_count=sum(p["ms_level"] == 2 for p in points),
                rt_min=points[0]["rt"], rt_max=points[-1]["rt"], mz_min=150, mz_max=300,
                total_ion_current=sum(p["total_intensity"] for p in points),
                peak_count=sum(f["peak_count"] for f in features),
                top_peaks=[{"mz": f["mz"], "intensity": f["apex_intensity"]} for f in features],
                base_peak_mz=features[0]["mz"], base_peak_intensity=features[0]["apex_intensity"],
                openms_summary={"demo": True, "synthetic": True, "note": "Simulated curves, no raw mzML and no compound identification. Not quantitative pigment evidence."},
            )
        notebook = Notebook.objects.create(name="Aurora | Bitácora de evaluación", project=project, scope=Notebook.SCOPE_PROJECT, owner=owner, description=DISCLAIMER)
        experiment = Experiment.objects.create(notebook=notebook, title="Aurora E01 | Comparación inicial (simulada)", created_by=owner)
        experiment.assignees.add(owner)
        blocks = [
            {"block_type": "HEADING", "data": {"text": "Comparación de referencia y dos candidatos"}},
            {"block_type": "RICH_TEXT", "data": {"text": DISCLAIMER + " Objetivo: mostrar trazabilidad, resultados y una decisión condicionada por QC."}},
            {"block_type": "TABLE", "data": {"rows": [["Muestra", "Grupo", "Réplica", "Señal (u.a.)", "Recuperación (%)"]] + [[r[0], r[1], str(r[2]), str(r[3]), str(r[4])] for r in ROWS]}},
            {"block_type": "RICH_TEXT", "data": {"text": "Referencia: media 102 u.a. Candidato A: media 150 u.a. (+47.1%). AUR-006 falla QC (63%; intervalo ilustrativo 80–120%). Candidato B requiere repetición antes de compararlo. Dos réplicas ficticias no demuestran significancia ni rendimiento industrial."}},
            {"block_type": "CHECKLIST", "data": {"items": [{"text": "Resultados iniciales documentados", "checked": True}, {"text": "Repetir QC de AUR-006 (pendiente)", "checked": False}]}},
        ]
        create_revision(experiment=experiment, actor=owner, blocks=blocks, links=[{"entity_type": "sample", "public_id": str(s.public_id), "relation_type": "input_sample"} for s in samples], reason="Fictional showcase results")
        experiment.refresh_from_db()
        experiment.status = Experiment.STATUS_COMPLETED
        experiment.completed_at = timezone.now()
        experiment.save(update_fields=["status", "completed_at", "updated_at"])
        ProjectPost.objects.create(project=project, author=owner, note=DISCLAIMER + " Recorrido: muestras AUR-001–006, bitácora E01, resultados, QC, secuencias y MS. Candidato A: +47.1% de señal ficticia. Candidato B: pendiente de repetir QC.")
        self.stdout.write(self.style.SUCCESS(f"Created {CODE}: 6 samples, completed experiment, 3 sequences, 1 alignment, 3 simulated MS runs. Owner: {owner.username}."))
        self.stdout.write("Use an isolated demo database. No email, passwords, permissions or global feature flags were changed.")
