import re
import subprocess
import tempfile
from pathlib import Path

from events.models import Event


def _safe_fasta_name(value):
    value = (value or "sequence").strip()
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^A-Za-z0-9_.-]", "_", value)
    return value[:120] or "sequence"


def _wrap_sequence(value, width=80):
    cleaned = "".join((value or "").split()).upper()
    return "\n".join(cleaned[i : i + width] for i in range(0, len(cleaned), width))


def build_input_fasta(sequences):
    lines = []

    for sequence_record in sequences:
        if sequence_record.sample_id and sequence_record.sample:
            base_name = sequence_record.sample.sample_id
        else:
            base_name = sequence_record.name

        header = f"{_safe_fasta_name(base_name)}|seq_{sequence_record.id}"
        wrapped = _wrap_sequence(sequence_record.sequence)

        lines.append(f">{header}")
        lines.append(wrapped)

    return "\n".join(lines) + "\n"


def run_clustal_omega_alignment(job, actor=None):
    sequences = list(
        job.sequences.select_related("sample", "project").all().order_by("id")
    )

    input_fasta = build_input_fasta(sequences)

    job.status = "RUNNING"
    job.input_fasta = input_fasta
    job.error_message = ""
    job.summary = {
        "tool": "CLUSTAL_OMEGA",
        "sequence_count": len(sequences),
        "input_lengths": {
            str(sequence.id): len(sequence.sequence or "")
            for sequence in sequences
        },
    }
    job.save(
        update_fields=[
            "status",
            "input_fasta",
            "error_message",
            "summary",
            "updated_at",
        ]
    )

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            input_path = tmpdir_path / "input.fasta"
            output_path = tmpdir_path / "aligned.fasta"

            input_path.write_text(input_fasta)

            result = subprocess.run(
                [
                    "clustalo",
                    "-i",
                    str(input_path),
                    "-o",
                    str(output_path),
                    "--force",
                    "--outfmt=fasta",
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )

            if result.returncode != 0:
                raise RuntimeError(result.stderr or result.stdout or "Clustal Omega failed.")

            aligned_fasta = output_path.read_text()

        aligned_lengths = []
        current_lines = []

        for line in aligned_fasta.splitlines():
            if line.startswith(">"):
                if current_lines:
                    aligned_lengths.append(len("".join(current_lines)))
                current_lines = []
            else:
                current_lines.append(line.strip())

        if current_lines:
            aligned_lengths.append(len("".join(current_lines)))

        summary = {
            **(job.summary or {}),
            "aligned_sequence_count": len(aligned_lengths),
            "aligned_length": aligned_lengths[0] if aligned_lengths else 0,
        }

        job.status = "COMPLETED"
        job.aligned_fasta = aligned_fasta
        job.summary = summary
        job.error_message = ""
        job.save(
            update_fields=[
                "status",
                "aligned_fasta",
                "summary",
                "error_message",
                "updated_at",
            ]
        )

        Event.objects.create(
            entity_type="AlignmentJob",
            entity_id=str(job.id),
            action="ALIGNMENT_COMPLETED",
            actor=actor,
            payload={
                "alignment_job_id": job.id,
                "name": job.name,
                "tool": job.tool,
                "project_id": job.project_id,
                "sequence_ids": [sequence.id for sequence in sequences],
                **summary,
            },
        )

    except Exception as exc:
        job.status = "FAILED"
        job.error_message = str(exc)
        job.summary = {
            **(job.summary or {}),
            "error": str(exc),
        }
        job.save(
            update_fields=[
                "status",
                "error_message",
                "summary",
                "updated_at",
            ]
        )

        Event.objects.create(
            entity_type="AlignmentJob",
            entity_id=str(job.id),
            action="ALIGNMENT_FAILED",
            actor=actor,
            payload={
                "alignment_job_id": job.id,
                "name": job.name,
                "tool": job.tool,
                "project_id": job.project_id,
                "error": str(exc),
            },
        )

    return job
