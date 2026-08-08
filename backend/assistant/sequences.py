import re
from collections import Counter, defaultdict

from django.apps import apps
from django.db.models import Q

from blast.models import BlastDatabase

from samples.access import get_sample_access_queryset
from samples.models import Sample


SEQUENCE_VALUE_FIELDS = [
    "sequence",
    "sequence_text",
    "raw_sequence",
    "bases",
    "residues",
    "fasta",
]

SEQUENCE_LABEL_FIELDS = [
    "name",
    "label",
    "sequence_id",
    "identifier",
    "accession",
    "gene",
    "target",
    "description",
]

SEQUENCE_TYPE_FIELDS = [
    "sequence_type",
    "molecule_type",
    "type",
    "kind",
]

BLAST_PROGRAMS = [
    "blastn",
    "blastp",
    "blastx",
    "tblastn",
    "tblastx",
]


def apply_sample_access(user):
    base_queryset = Sample.objects.all().select_related(
        "project",
        "container",
        "created_by",
    )

    try:
        return get_sample_access_queryset(base_queryset, user)
    except TypeError:
        return get_sample_access_queryset(user).select_related(
            "project",
            "container",
            "created_by",
        )


def model_label(model):
    return f"{model._meta.app_label}.{model.__name__}"


def concrete_field_names(model):
    return {
        field.name
        for field in model._meta.fields
        if hasattr(field, "name")
    }


def field_points_to_sample(field):
    remote = getattr(getattr(field, "remote_field", None), "model", None)

    if remote is None:
        return False

    return getattr(remote._meta, "label_lower", "") == Sample._meta.label_lower


def find_sample_fk_field(model):
    for field in model._meta.fields:
        if field_points_to_sample(field):
            return field.name

    return None


def find_fk_to_model(model, target_model):
    target_label = target_model._meta.label_lower

    for field in model._meta.fields:
        remote = getattr(getattr(field, "remote_field", None), "model", None)

        if remote is None:
            continue

        if getattr(remote._meta, "label_lower", "") == target_label:
            return field.name

    return None


def has_sequence_like_field(model):
    field_names = concrete_field_names(model)

    if any(field in field_names for field in SEQUENCE_VALUE_FIELDS):
        return True

    return any("sequence" in field.lower() for field in field_names)


def find_sequence_models():
    candidates = []

    for model in apps.get_models():
        model_name = model.__name__.lower()
        field_names = concrete_field_names(model)
        sample_fk = find_sample_fk_field(model)

        looks_like_sequence = (
            "sequence" in model_name
            or any(field in field_names for field in SEQUENCE_VALUE_FIELDS)
            or any("sequence" in field.lower() for field in field_names)
        )

        if looks_like_sequence and sample_fk and has_sequence_like_field(model):
            candidates.append((model, sample_fk))

    return candidates


def get_first_field_value(obj, candidate_fields):
    field_names = concrete_field_names(obj.__class__)

    for field in candidate_fields:
        if field in field_names:
            value = getattr(obj, field, None)

            if value not in [None, ""]:
                return value

    return None


def get_sequence_label(obj):
    value = get_first_field_value(obj, SEQUENCE_LABEL_FIELDS)

    if value:
        return str(value)

    return f"{obj.__class__.__name__} #{obj.pk}"


def get_sequence_type(obj):
    value = get_first_field_value(obj, SEQUENCE_TYPE_FIELDS)

    if value:
        return str(value)

    return "unknown"


def get_sequence_text(obj):
    value = get_first_field_value(obj, SEQUENCE_VALUE_FIELDS)

    if value is None:
        return ""

    return str(value)


def get_sequence_length(obj):
    sequence_text = get_sequence_text(obj)

    if not sequence_text:
        return None

    cleaned = re.sub(r"[^A-Za-z*.-]", "", sequence_text)

    return len(cleaned) if cleaned else None


def get_sequence_sample(obj):
    sample_fk = find_sample_fk_field(obj.__class__)

    if not sample_fk:
        return None

    return getattr(obj, sample_fk, None)


def sample_link(sample):
    return {
        "label": f"Open {sample.sample_id}",
        "url": f"/samples/{sample.id}",
    }


def extract_sample_tokens(message):
    text = str(message or "")

    tokens = re.findall(r"\b[A-Za-z]{1,8}-[A-Za-z0-9_-]+\b", text)
    tokens += re.findall(r"\bsample\s+([A-Za-z0-9_-]+)\b", text, re.IGNORECASE)

    cleaned = []
    for token in tokens:
        token = token.strip(" .,:;#")

        if token and token.lower() not in ["sequence", "sequences", "blast"]:
            cleaned.append(token)

    return list(dict.fromkeys(cleaned))


def find_accessible_sample_from_message(message, user):
    queryset = apply_sample_access(user)
    tokens = extract_sample_tokens(message)

    for token in tokens:
        sample = queryset.filter(sample_id__iexact=token).first()

        if sample:
            return sample

    for token in tokens:
        sample = queryset.filter(sample_id__icontains=token).first()

        if sample:
            return sample

    return None


def sequence_queryset_for_user(model, sample_fk, user, sample=None):
    accessible_sample_ids = apply_sample_access(user).values_list("id", flat=True)

    queryset = model.objects.filter(**{
        f"{sample_fk}_id__in": accessible_sample_ids,
    })

    if sample is not None:
        queryset = queryset.filter(**{
            f"{sample_fk}_id": sample.id,
        })

    return queryset


def sequence_line(obj):
    sample = get_sequence_sample(obj)
    label = get_sequence_label(obj)
    sequence_type = get_sequence_type(obj)
    length = get_sequence_length(obj)

    length_text = f"{length} bp/aa" if length is not None else "length unknown"
    sample_text = getattr(sample, "sample_id", "unknown sample")

    return f"- {label} — sample: {sample_text}, type: {sequence_type}, length: {length_text}"


def find_sample_sequences(message, user, limit=20):
    models = find_sequence_models()

    if not models:
        return {
            "answer": (
                "I could not find a sequence record model linked to samples yet. "
                "Add sequence records linked to Sample before using sequence search."
            ),
            "links": [],
            "suggestions": [
                "Summarize sequence records",
                "Chart samples by status",
            ],
            "skip_llm": True,
        }

    sample = find_accessible_sample_from_message(message, user)

    lines = []
    links = []
    total = 0

    for model, sample_fk in models:
        queryset = sequence_queryset_for_user(model, sample_fk, user, sample=sample)
        count = queryset.count()
        total += count

        if count == 0:
            continue

        lines.append(f"{model_label(model)}: {count} sequence record(s)")

        for obj in queryset.order_by("-id")[:limit]:
            lines.append(sequence_line(obj))

            obj_sample = get_sequence_sample(obj)
            if obj_sample:
                link = sample_link(obj_sample)
                if link not in links:
                    links.append(link)

    if total == 0:
        if sample:
            return {
                "answer": f"No sequence records were found for sample {sample.sample_id}.",
                "links": [sample_link(sample)],
                "suggestions": [
                    "Summarize sequence records",
                    "Prepare BLAST for sample",
                ],
                "skip_llm": True,
            }

        return {
            "answer": "No accessible sequence records were found.",
            "links": [],
            "suggestions": [
                "Find sample sequences",
                "Chart samples by status",
            ],
            "skip_llm": True,
        }

    scope = f" for sample {sample.sample_id}" if sample else ""
    answer = [f"Found {total} accessible sequence record(s){scope}."]
    answer.extend(lines)

    return {
        "answer": "\n".join(answer),
        "links": links[:10],
        "suggestions": [
            "Prepare BLAST for sample",
            "Summarize sequence records",
            "Chart samples by status",
        ],
    }


def summarize_sequence_records(message, user):
    models = find_sequence_models()

    if not models:
        return {
            "answer": (
                "No sequence record model linked to samples was found yet. "
                "Sequence summaries will work once sequence records are stored in OpenLIMS."
            ),
            "links": [],
            "suggestions": [
                "Find sample sequences",
                "Chart samples by status",
            ],
            "skip_llm": True,
        }

    sample = find_accessible_sample_from_message(message, user)

    total = 0
    model_counts = Counter()
    type_counts = Counter()
    sample_counts = Counter()
    lengths = []
    links = []

    for model, sample_fk in models:
        queryset = sequence_queryset_for_user(model, sample_fk, user, sample=sample)

        for obj in queryset[:5000]:
            total += 1
            model_counts[model_label(model)] += 1
            type_counts[get_sequence_type(obj)] += 1

            length = get_sequence_length(obj)
            if length is not None:
                lengths.append(length)

            obj_sample = get_sequence_sample(obj)
            if obj_sample:
                sample_counts[obj_sample.sample_id] += 1
                link = sample_link(obj_sample)
                if link not in links:
                    links.append(link)

    if total == 0:
        scope = f" for sample {sample.sample_id}" if sample else ""
        return {
            "answer": f"No accessible sequence records were found{scope}.",
            "links": [sample_link(sample)] if sample else [],
            "suggestions": [
                "Find sample sequences",
                "Prepare BLAST for sample",
            ],
            "skip_llm": True,
        }

    lines = [f"Sequence summary: {total} accessible sequence record(s)."]

    if model_counts:
        lines.append("")
        lines.append("By model:")
        for name, count in model_counts.most_common():
            lines.append(f"- {name}: {count}")

    if type_counts:
        lines.append("")
        lines.append("By type:")
        for sequence_type, count in type_counts.most_common():
            lines.append(f"- {sequence_type}: {count}")

    if lengths:
        avg_length = sum(lengths) / len(lengths)
        lines.append("")
        lines.append(
            f"Lengths: min {min(lengths)}, max {max(lengths)}, average {avg_length:.1f}"
        )

    if sample_counts and not sample:
        lines.append("")
        lines.append("Top samples by sequence count:")
        for sample_id, count in sample_counts.most_common(10):
            lines.append(f"- {sample_id}: {count}")

    return {
        "answer": "\n".join(lines),
        "links": links[:10],
        "suggestions": [
            "Find sample sequences",
            "Prepare BLAST for sample",
            "Chart samples by status",
        ],
    }


def parse_blast_program(message, sequence_obj=None):
    lower = str(message or "").lower()

    for program in BLAST_PROGRAMS:
        if program in lower:
            return program

    sequence_type = ""
    if sequence_obj is not None:
        sequence_type = get_sequence_type(sequence_obj).lower()

    if any(term in sequence_type for term in ["protein", "amino", "aa", "peptide"]):
        return "blastp"

    return "blastn"


def parse_blast_database(message):
    text = str(message or "")

    patterns = [
        r"\bdatabase\s+([A-Za-z0-9_.:-]+)",
        r"\bdb\s+([A-Za-z0-9_.:-]+)",
        r"\bagainst\s+([A-Za-z0-9_.:-]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            return match.group(1).strip(" .,:;")

    return ""


def select_sequences_for_blast(message, user):
    models = find_sequence_models()

    if not models:
        return [], None

    sample = find_accessible_sample_from_message(message, user)

    if sample is None:
        return [], None

    found = []

    for model, sample_fk in models:
        queryset = sequence_queryset_for_user(model, sample_fk, user, sample=sample)

        for obj in queryset.order_by("-id")[:20]:
            found.append(obj)

    return found, sample


def prepare_blast_job(message, user):
    sequences, sample = select_sequences_for_blast(message, user)

    if sample is None:
        return {
            "answer": (
                "Tell me which sample to use for BLAST. "
                "Example: Prepare BLAST for sample S-UW-101."
            ),
            "links": [],
            "suggestions": [
                "Find sample sequences",
                "Summarize sequence records",
            ],
            "skip_llm": True,
        }

    if not sequences:
        return {
            "answer": f"No sequence records were found for sample {sample.sample_id}.",
            "links": [sample_link(sample)],
            "suggestions": [
                "Find sample sequences",
                "Summarize sequence records",
            ],
            "skip_llm": True,
        }

    if len(sequences) > 1:
        lines = [
            f"I found {len(sequences)} sequence record(s) for sample {sample.sample_id}.",
            "Choose which sequence should be used for BLAST:",
        ]

        for index, obj in enumerate(sequences[:10], start=1):
            lines.append(f"{index}. {sequence_line(obj).lstrip('- ')}")

        return {
            "answer": "\n".join(lines),
            "links": [sample_link(sample)],
            "suggestions": [
                f"Prepare BLAST for sample {sample.sample_id} using sequence 1",
                f"Run blastn for sample {sample.sample_id}",
                "Find sample sequences",
            ],
            "skip_llm": True,
        }

    sequence_obj = sequences[0]
    program = parse_blast_program(message, sequence_obj=sequence_obj)
    database_name = parse_blast_database(message)
    label = get_sequence_label(sequence_obj)
    sequence_type = get_sequence_type(sequence_obj)
    length = get_sequence_length(sequence_obj)

    length_text = f"{length} bp/aa" if length is not None else "unknown length"

    lines = [
        "Prepared a BLAST job plan.",
        "",
        f"Sample: {sample.sample_id}",
        f"Sequence: {label}",
        f"Sequence type: {sequence_type}",
        f"Sequence length: {length_text}",
        f"Program: {program}",
        f"Database: {database_name or 'not selected yet'}",
        "",
        "Status: not queued.",
    ]

    if program not in ["blastn", "blastp"]:
        lines.extend([
            "",
            f"{program} is not supported by the current BLAST job model. Choose blastn or blastp.",
        ])
        return {
            "answer": "\n".join(lines),
            "links": [sample_link(sample), {"label": "Open BLAST", "url": "/blast"}],
            "suggestions": [
                f"Prepare blastn for sample {sample.sample_id}",
                f"Prepare blastp for sample {sample.sample_id}",
            ],
            "skip_llm": True,
        }

    if not database_name:
        lines.extend([
            "",
            "No action can be confirmed yet. Choose a ready local BLAST database using `against DATABASE_NAME`.",
        ])
        return {
            "answer": "\n".join(lines),
            "links": [sample_link(sample), {"label": "Open BLAST", "url": "/blast"}],
            "suggestions": [
                f"Prepare {program} for sample {sample.sample_id} against local_database_name",
                "Find sample sequences",
            ],
            "skip_llm": True,
        }

    database = (
        BlastDatabase.objects
        .filter(name__iexact=database_name, status=BlastDatabase.STATUS_READY)
        .first()
    )

    if not database:
        lines.extend([
            "",
            f"I could not find a READY local BLAST database named {database_name}. No action was proposed.",
        ])
        return {
            "answer": "\n".join(lines),
            "links": [sample_link(sample), {"label": "Open BLAST databases", "url": "/blast"}],
            "suggestions": [
                "Find sample sequences",
                "Summarize BLAST results",
            ],
            "skip_llm": True,
        }

    summary = (
        f"Run {program} for {sample.sample_id} using {label} "
        f"against {database.name}"
    )
    lines.extend([
        "",
        "Review the action details below. BLAST will run only after you confirm.",
    ])

    return {
        "answer": "\n".join(lines),
        "links": [sample_link(sample), {"label": "Open BLAST", "url": "/blast"}],
        "suggestions": [
            "Summarize BLAST results",
            "Find sample sequences",
        ],
        "skip_llm": True,
        "pending_action": {
            "type": "RUN_BLAST",
            "summary": summary,
            "payload": {
                "name": f"Assistant BLAST — {sample.sample_id}",
                "project": sample.project_id,
                "query_sequence": sequence_obj.id,
                "database": database.id,
                "program": program,
                "max_target_seqs": 25,
                "evalue": "10",
            },
        },
    }


def find_blast_models():
    job_models = []
    hit_models = []

    for model in apps.get_models():
        model_name = model.__name__.lower()

        if "blast" not in model_name:
            continue

        if "job" in model_name or "run" in model_name:
            job_models.append(model)

        if "hit" in model_name or "result" in model_name:
            hit_models.append(model)

    return job_models, hit_models


def extract_job_id(message):
    text = str(message or "")

    patterns = [
        r"blast\s+job\s*#?\s*(\d+)",
        r"job\s*#?\s*(\d+)",
        r"#\s*(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)

        if match:
            return int(match.group(1))

    return None


def get_related_sample_from_object(obj):
    for field in obj.__class__._meta.fields:
        remote = getattr(getattr(field, "remote_field", None), "model", None)

        if remote is None:
            continue

        remote_label = getattr(remote._meta, "label_lower", "")

        if remote_label == Sample._meta.label_lower:
            return getattr(obj, field.name, None)

        if "sequence" in remote.__name__.lower():
            sequence_obj = getattr(obj, field.name, None)

            if sequence_obj is not None:
                sample = get_sequence_sample(sequence_obj)

                if sample is not None:
                    return sample

    return None


def user_can_access_sample(sample, user):
    if sample is None:
        return False

    return apply_sample_access(user).filter(id=sample.id).exists()


def user_can_access_blast_job(job, user):
    sample = get_related_sample_from_object(job)

    if sample is not None:
        return user_can_access_sample(sample, user)

    return bool(getattr(user, "is_staff", False) or getattr(user, "is_superuser", False))


def get_field_from_candidates(obj, candidates):
    field_names = concrete_field_names(obj.__class__)

    for candidate in candidates:
        if candidate in field_names:
            value = getattr(obj, candidate, None)

            if value not in [None, ""]:
                return value

    return None


def summarize_blast_results(message, user):
    job_models, hit_models = find_blast_models()

    if not job_models:
        return {
            "answer": (
                "No stored BLAST job/result models were found yet. "
                "v0.19.5 can prepare BLAST plans, but actual BLAST execution and result storage "
                "should be added as a confirmed background action in v0.20.0."
            ),
            "links": [],
            "suggestions": [
                "Prepare BLAST for sample",
                "Find sample sequences",
            ],
            "skip_llm": True,
        }

    job_id = extract_job_id(message)
    job = None
    job_model = None

    for candidate_model in job_models:
        if job_id:
            candidate = candidate_model.objects.filter(id=job_id).first()
        else:
            candidate = candidate_model.objects.order_by("-id").first()

        if candidate is not None:
            job = candidate
            job_model = candidate_model
            break

    if job is None:
        if job_id:
            answer = f"I could not find BLAST job #{job_id}."
        else:
            answer = "No BLAST jobs were found."

        return {
            "answer": answer,
            "links": [],
            "suggestions": [
                "Prepare BLAST for sample",
                "Find sample sequences",
            ],
            "skip_llm": True,
        }

    if not user_can_access_blast_job(job, user):
        return {
            "answer": (
                f"I found BLAST job #{job.id}, but I could not confirm that it is linked "
                "to a sample you can access. I will not summarize it."
            ),
            "links": [],
            "suggestions": [
                "Find sample sequences",
                "Prepare BLAST for sample",
            ],
            "skip_llm": True,
        }

    status = get_field_from_candidates(job, ["status", "state"])
    program = get_field_from_candidates(job, ["program", "blast_program"])
    database = get_field_from_candidates(job, ["database", "db", "target_database"])
    summary = get_field_from_candidates(job, ["summary", "metadata", "result_summary"])

    lines = [
        f"BLAST job #{job.id} summary:",
        f"- Model: {model_label(job_model)}",
    ]

    if status:
        lines.append(f"- Status: {status}")

    if program:
        lines.append(f"- Program: {program}")

    if database:
        lines.append(f"- Database: {database}")

    matching_hit_model = None
    matching_job_fk = None

    for hit_model in hit_models:
        job_fk = find_fk_to_model(hit_model, job_model)

        if job_fk:
            matching_hit_model = hit_model
            matching_job_fk = job_fk
            break

    if matching_hit_model is None:
        if summary:
            lines.append("")
            lines.append(f"Stored summary: {summary}")
        else:
            lines.append("")
            lines.append("No linked BLAST hit/result model was found for this job yet.")

        return {
            "answer": "\n".join(lines),
            "links": [],
            "suggestions": [
                "Prepare BLAST for sample",
                "Find sample sequences",
            ],
            "skip_llm": True,
        }

    hits_queryset = matching_hit_model.objects.filter(**{
        matching_job_fk: job,
    })

    hit_count = hits_queryset.count()
    lines.append(f"- Hits: {hit_count}")

    if hit_count == 0:
        lines.append("")
        lines.append("No BLAST hits were stored for this job.")

        return {
            "answer": "\n".join(lines),
            "links": [],
            "suggestions": [
                "Prepare BLAST for sample",
                "Find sample sequences",
            ],
            "skip_llm": True,
        }

    lines.append("")
    lines.append("Top hits:")

    for hit in hits_queryset.order_by("id")[:10]:
        title = get_field_from_candidates(hit, [
            "subject_id",
            "hit_id",
            "accession",
            "title",
            "description",
            "name",
        ]) or f"Hit #{hit.id}"

        evalue = get_field_from_candidates(hit, [
            "evalue",
            "e_value",
            "expect",
        ])

        score = get_field_from_candidates(hit, [
            "bitscore",
            "bit_score",
            "score",
        ])

        identity = get_field_from_candidates(hit, [
            "percent_identity",
            "identity",
            "identity_percent",
            "pident",
        ])

        details = []

        if evalue not in [None, ""]:
            details.append(f"e-value {evalue}")

        if score not in [None, ""]:
            details.append(f"score {score}")

        if identity not in [None, ""]:
            details.append(f"identity {identity}")

        suffix = f" — {', '.join(details)}" if details else ""

        lines.append(f"- {title}{suffix}")

    return {
        "answer": "\n".join(lines),
        "links": [],
        "suggestions": [
            "Prepare BLAST for sample",
            "Find sample sequences",
            "Summarize sequence records",
        ],
        "skip_llm": True,
    }


def route_assistant_sequence(message, user):
    text = str(message or "").strip()
    lower = text.lower()

    sequence_terms = [
        "sequence",
        "sequences",
        "fasta",
        "nucleotide",
        "protein",
        "dna",
        "rna",
        "blast",
    ]

    if not any(term in lower for term in sequence_terms):
        return None

    if "blast" in lower:
        if any(term in lower for term in ["result", "results", "summary", "summarize", "hits", "hit"]):
            return summarize_blast_results(text, user)

        return prepare_blast_job(text, user)

    if any(term in lower for term in ["summarize", "summary", "overview", "count"]):
        return summarize_sequence_records(text, user)

    if any(term in lower for term in ["find", "show", "list", "sample"]):
        return find_sample_sequences(text, user)

    return summarize_sequence_records(text, user)
