import json
import re
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from events.models import Event

from .models import BlastDatabase, BlastHit, BlastJob


def _safe_fasta_name(value):
    value = (value or "sequence").strip()
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^A-Za-z0-9_.-]", "_", value)
    return value[:120] or "sequence"


def _wrap_sequence(value, width=80):
    cleaned = "".join((value or "").split()).upper()
    return "\n".join(cleaned[i : i + width] for i in range(0, len(cleaned), width))


def build_query_fasta(sequence_record):
    header = f"{_safe_fasta_name(sequence_record.name)}|seq_{sequence_record.id}"
    return f">{header}\n{_wrap_sequence(sequence_record.sequence)}\n"


def _db_type_for_blast(database):
    if database.database_type == BlastDatabase.DATABASE_TYPE_PROTEIN:
        return "prot"

    return "nucl"


def build_blast_database(database, actor=None):
    if not database.source_fasta:
        raise RuntimeError("BLAST database source FASTA is required.")

    database.status = BlastDatabase.STATUS_BUILDING
    database.error_message = ""
    database.save(update_fields=["status", "error_message", "updated_at"])

    try:
        db_root = Path(settings.MEDIA_ROOT) / "blast_databases" / f"db_{database.id}"
        db_root.mkdir(parents=True, exist_ok=True)

        db_prefix = db_root / "blastdb"
        db_type = _db_type_for_blast(database)

        result = subprocess.run(
            [
                "makeblastdb",
                "-in",
                database.source_fasta.path,
                "-dbtype",
                db_type,
                "-out",
                str(db_prefix),
                "-parse_seqids",
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(result.stderr or result.stdout or "makeblastdb failed.")

        database.db_path = str(db_prefix)
        database.status = BlastDatabase.STATUS_READY
        database.error_message = ""
        database.save(
            update_fields=[
                "db_path",
                "status",
                "error_message",
                "updated_at",
            ]
        )

        Event.objects.create(
            entity_type="BlastDatabase",
            entity_id=str(database.id),
            action="BLAST_DATABASE_BUILT",
            actor=actor,
            payload={
                "blast_database_id": database.id,
                "name": database.name,
                "database_type": database.database_type,
                "db_path": database.db_path,
            },
        )

    except Exception as exc:
        database.status = BlastDatabase.STATUS_FAILED
        database.error_message = str(exc)
        database.save(update_fields=["status", "error_message", "updated_at"])

        Event.objects.create(
            entity_type="BlastDatabase",
            entity_id=str(database.id),
            action="BLAST_DATABASE_BUILD_FAILED",
            actor=actor,
            payload={
                "blast_database_id": database.id,
                "name": database.name,
                "error": str(exc),
            },
        )

        raise

    return database


def _extract_hits_from_blast_json(data):
    """
    Supports BLAST+ outfmt 15 JSON.

    Depending on BLAST+ version, the output can be shaped like:

    1. [
         {
           "BlastOutput2": {
             "report": {
               "results": {
                 "search": {
                   "hits": [...]
                 }
               }
             }
           }
         }
       ]

    2. {
         "BlastOutput2": [
           {
             "report": {
               "results": {
                 "search": {
                   "hits": [...]
                 }
               }
             }
           }
         ]
       }

    3. {
         "BlastOutput2": {
           "report": {
             "results": {
               "search": {
                 "hits": [...]
               }
             }
           }
         }
       }
    """

    if not data:
        return []

    root = data

    if isinstance(data, list):
        if not data:
            return []

        first = data[0]

        if isinstance(first, dict):
            root = first.get("BlastOutput2", first)
        else:
            return []

    elif isinstance(data, dict):
        root = data.get("BlastOutput2", data)

    else:
        return []

    if isinstance(root, list):
        if not root:
            return []

        first = root[0]

        if isinstance(first, dict):
            root = first
        else:
            return []

    if not isinstance(root, dict):
        return []

    report = root.get("report", {})
    results = report.get("results", {})
    search = results.get("search", {})

    return search.get("hits", []) or []


def _extract_first_description(hit):
    descriptions = hit.get("description") or []

    if not descriptions:
        return {}

    first_description = descriptions[0]

    if isinstance(first_description, dict):
        return first_description

    return {}


def _extract_first_hsp(hit):
    hsps = hit.get("hsps") or []

    if not hsps:
        return {}

    first_hsp = hsps[0]

    if isinstance(first_hsp, dict):
        return first_hsp

    return {}


def run_blast_job(job, actor=None):
    sequence_record = job.query_sequence
    database = job.database

    if database.status != BlastDatabase.STATUS_READY:
        raise RuntimeError("BLAST database is not ready.")

    if not database.db_path:
        raise RuntimeError("BLAST database path is missing.")

    query_fasta = build_query_fasta(sequence_record)
    query_length = len("".join((sequence_record.sequence or "").split()))

    job.status = BlastJob.STATUS_RUNNING
    job.query_fasta = query_fasta
    job.error_message = ""
    job.result_json = {
        "started_at": timezone.now().isoformat(),
        "program": job.program,
        "database": database.name,
        "query_sequence_id": sequence_record.id,
        "query_sequence_name": sequence_record.name,
        "query_length": query_length,
    }
    job.save(
        update_fields=[
            "status",
            "query_fasta",
            "error_message",
            "result_json",
            "updated_at",
        ]
    )

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            query_path = tmpdir_path / "query.fasta"
            output_path = tmpdir_path / "blast.json"

            query_path.write_text(query_fasta)

            command = [
                job.program,
                "-query",
                str(query_path),
                "-db",
                database.db_path,
                "-out",
                str(output_path),
                "-outfmt",
                "15",
                "-max_target_seqs",
                str(job.max_target_seqs),
                "-evalue",
                str(job.evalue),
            ]

            # Short nucleotide queries often return zero hits with default blastn.
            # blastn-short is designed for short DNA/RNA queries.
            if job.program == BlastJob.PROGRAM_BLASTN and query_length < 50:
                command.extend(["-task", "blastn-short"])

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )

            if result.returncode != 0:
                raise RuntimeError(result.stderr or result.stdout or "BLAST failed.")

            raw_output = output_path.read_text()
            parsed = json.loads(raw_output) if raw_output.strip() else {}

        hits = _extract_hits_from_blast_json(parsed)

        BlastHit.objects.filter(job=job).delete()

        created_hits = []

        for index, hit in enumerate(hits, start=1):
            first_description = _extract_first_description(hit)
            first_hsp = _extract_first_hsp(hit)

            alignment_length = first_hsp.get("align_len") or 0
            identity = first_hsp.get("identity") or 0
            identity_percent = None

            if alignment_length:
                identity_percent = round((identity / alignment_length) * 100, 2)

            created_hits.append(
                BlastHit(
                    job=job,
                    rank=index,
                    hit_id=first_description.get("id", ""),
                    hit_def=first_description.get("title", ""),
                    accession=first_description.get("accession", ""),
                    hit_length=hit.get("len") or 0,
                    bit_score=first_hsp.get("bit_score"),
                    evalue=first_hsp.get("evalue"),
                    identity_percent=identity_percent,
                    alignment_length=alignment_length or 0,
                    query_from=first_hsp.get("query_from"),
                    query_to=first_hsp.get("query_to"),
                    hit_from=first_hsp.get("hit_from"),
                    hit_to=first_hsp.get("hit_to"),
                    query_aligned=first_hsp.get("qseq", ""),
                    hit_aligned=first_hsp.get("hseq", ""),
                    midline=first_hsp.get("midline", ""),
                )
            )

        BlastHit.objects.bulk_create(created_hits)

        job.status = BlastJob.STATUS_COMPLETED
        job.hits_count = len(created_hits)
        job.result_json = {
            "completed_at": timezone.now().isoformat(),
            "program": job.program,
            "database": database.name,
            "query_sequence_id": sequence_record.id,
            "query_sequence_name": sequence_record.name,
            "query_length": query_length,
            "hits_count": len(created_hits),
            "used_blastn_short": (
                job.program == BlastJob.PROGRAM_BLASTN and query_length < 50
            ),
        }
        job.error_message = ""
        job.save(
            update_fields=[
                "status",
                "hits_count",
                "result_json",
                "error_message",
                "updated_at",
            ]
        )

        Event.objects.create(
            entity_type="BlastJob",
            entity_id=str(job.id),
            action="BLAST_COMPLETED",
            actor=actor,
            payload={
                "blast_job_id": job.id,
                "name": job.name,
                "project_id": job.project_id,
                "query_sequence_id": sequence_record.id,
                "database_id": database.id,
                "database_name": database.name,
                "program": job.program,
                "hits_count": job.hits_count,
                "used_blastn_short": (
                    job.program == BlastJob.PROGRAM_BLASTN and query_length < 50
                ),
            },
        )

    except Exception as exc:
        job.status = BlastJob.STATUS_FAILED
        job.error_message = str(exc)
        job.result_json = {
            **(job.result_json or {}),
            "error": str(exc),
            "failed_at": timezone.now().isoformat(),
        }
        job.save(
            update_fields=[
                "status",
                "error_message",
                "result_json",
                "updated_at",
            ]
        )

        Event.objects.create(
            entity_type="BlastJob",
            entity_id=str(job.id),
            action="BLAST_FAILED",
            actor=actor,
            payload={
                "blast_job_id": job.id,
                "name": job.name,
                "project_id": job.project_id,
                "query_sequence_id": sequence_record.id,
                "database_id": database.id,
                "database_name": database.name,
                "program": job.program,
                "error": str(exc),
            },
        )

        raise

    return job
