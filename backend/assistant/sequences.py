import re
from collections import Counter, defaultdict

from django.apps import apps
from django.db.models import Q

from blast.models import BlastDatabase

from samples.access import get_sample_access_queryset
from samples.models import Sample

from .intent_matching import compact_command_text, contains_any_intent_phrase


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

    return (
        f"- Sequence #{obj.pk}: {label} — sample: {sample_text}, "
        f"type: {sequence_type}, length: {length_text}"
    )


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

    matches = re.findall(
        r"\b(?:database|db|against)\s+([A-Za-z0-9_.:-]+)",
        text,
        re.IGNORECASE,
    )

    if not matches:
        return ""

    return matches[-1].strip(" .,:;")


def extract_sequence_record_id(message):
    patterns = [
        r"\bsequence\s*#\s*(\d+)\b",
        r"\brecord\s*#\s*(\d+)\b",
        r"\bsequence\s+id\s*#?\s*(\d+)\b",
    ]

    for pattern in patterns:
        match = re.search(
            pattern,
            str(message or ""),
            re.IGNORECASE,
        )
        if match:
            return int(match.group(1))

    return None


def extract_raw_sequence(message):
    match = re.search(
        r"\b(?:(?:DNA|RNA|PROTEIN)\s+)?sequence\s*[:=]\s*([A-Za-z*.-]{10,})",
        str(message or ""),
        re.IGNORECASE,
    )

    if not match:
        return ""

    return re.sub(r"[^A-Za-z*]", "", match.group(1)).upper()


def infer_raw_sequence_type(message, sequence):
    explicit = re.search(
        r"\b(DNA|RNA|PROTEIN)\s+sequence\s*[:=]",
        str(message or ""),
        re.IGNORECASE,
    )

    if explicit:
        return explicit.group(1).upper()

    letters = set(str(sequence or "").upper())

    dna_letters = set("ACGTRYKMSWBDHVN")
    rna_letters = set("ACGURYKMSWBDHVN")

    if letters and letters <= dna_letters:
        return "DNA"

    if letters and letters <= rna_letters:
        return "RNA"

    return "PROTEIN"


def validate_raw_sequence(sequence, sequence_type):
    letters = set(str(sequence or "").upper())

    if not letters:
        return False

    allowed = {
        "DNA": set("ACGTRYKMSWBDHVN"),
        "RNA": set("ACGURYKMSWBDHVN"),
        "PROTEIN": set("ABCDEFGHIJKLMNOPQRSTUVWXYZ*"),
    }

    return letters <= allowed.get(sequence_type, set())


def asks_to_use_sample_as_database(message):
    return bool(
        re.search(
            r"\bagainst\s+(?:this\s+)?sample\b",
            str(message or ""),
            re.IGNORECASE,
        )
    )


def select_sequences_for_blast(message, user):
    models = find_sequence_models()

    if not models:
        return [], None

    sequence_id = extract_sequence_record_id(message)

    if sequence_id is not None:
        for model, sample_fk in models:
            sequence_obj = (
                sequence_queryset_for_user(model, sample_fk, user)
                .filter(id=sequence_id)
                .first()
            )

            if sequence_obj is not None:
                return [sequence_obj], get_sequence_sample(sequence_obj)

        return [], None

    sample = find_accessible_sample_from_message(message, user)

    if sample is None:
        return [], None

    found = []

    for model, sample_fk in models:
        queryset = sequence_queryset_for_user(
            model,
            sample_fk,
            user,
            sample=sample,
        )

        for obj in queryset.order_by("-id")[:20]:
            found.append(obj)

    message_lower = str(message or "").lower()
    name_matches = [
        obj
        for obj in found
        if get_sequence_label(obj).lower() in message_lower
    ]

    if name_matches:
        return name_matches, sample

    return found, sample


def prepare_blast_job(message, user, context=None):
    incoming_context = dict(context or {})
    current_message = str(message or "").strip()

    if incoming_context.get("intent") == "RUN_BLAST":
        previous_request = str(
            incoming_context.get("request_text") or ""
        ).strip()
    else:
        previous_request = ""

    effective_message = "\n".join(
        part
        for part in [previous_request, current_message]
        if part
    ).strip()

    next_context = {
        "intent": "RUN_BLAST",
        "request_text": effective_message[-8000:],
    }

    raw_sequence = extract_raw_sequence(effective_message)
    raw_sequence_type = ""

    if raw_sequence:
        raw_sequence_type = infer_raw_sequence_type(
            effective_message,
            raw_sequence,
        )

        if not validate_raw_sequence(raw_sequence, raw_sequence_type):
            return {
                "answer": (
                    f"The pasted sequence is not valid {raw_sequence_type} data. "
                    "Check the sequence and start the BLAST request again."
                ),
                "links": [{"label": "Open BLAST", "url": "/blast"}],
                "suggestions": [
                    "Find sample sequences",
                    "Prepare BLAST for sample",
                ],
                "skip_llm": True,
                "context": {},
            }

        sequences = []
        sample = None
    else:
        sequences, sample = select_sequences_for_blast(
            effective_message,
            user,
        )

    selected_sequence_id = extract_sequence_record_id(effective_message)

    if not raw_sequence and sample is None:
        if selected_sequence_id is not None:
            answer = (
                f"I could not access sequence #{selected_sequence_id}. "
                "Choose one of the sequence IDs shown by the sequence search."
            )
        else:
            answer = (
                "Tell me which saved sequence to use for BLAST. "
                "You can say `Use sequence #12`, or paste a query using "
                "`Run BLAST for this DNA sequence: ATGC...`."
            )

        return {
            "answer": answer,
            "links": [],
            "suggestions": [
                "Find sample sequences",
                "Summarize sequence records",
            ],
            "skip_llm": True,
            "context": next_context,
        }

    if not raw_sequence and not sequences:
        return {
            "answer": f"No sequence records were found for sample {sample.sample_id}.",
            "links": [sample_link(sample)],
            "suggestions": [
                "Find sample sequences",
                "Summarize sequence records",
            ],
            "skip_llm": True,
            "context": next_context,
        }

    if not raw_sequence and len(sequences) > 1:
        lines = [
            f"I found {len(sequences)} sequence record(s) for sample {sample.sample_id}.",
            "Choose the exact sequence ID to use for BLAST:",
        ]

        for obj in sequences[:10]:
            lines.append(sequence_line(obj))

        suggestions = [
            f"Use sequence #{obj.id}"
            for obj in sequences[:2]
        ]
        suggestions.append("Find sample sequences")

        return {
            "answer": "\n".join(lines),
            "links": [sample_link(sample)],
            "suggestions": suggestions,
            "skip_llm": True,
            "context": next_context,
        }

    if raw_sequence:
        sequence_obj = None
        label = "Pasted query sequence"
        sequence_type = raw_sequence_type
        length = len(raw_sequence)
        project_id = None
        links = [{"label": "Open BLAST", "url": "/blast"}]
    else:
        sequence_obj = sequences[0]
        label = get_sequence_label(sequence_obj)
        sequence_type = get_sequence_type(sequence_obj)
        length = get_sequence_length(sequence_obj)
        project_id = sample.project_id
        links = [
            sample_link(sample),
            {"label": "Open BLAST", "url": "/blast"},
        ]

    program = parse_blast_program(
        effective_message,
        sequence_obj=sequence_obj,
    )

    if (
        raw_sequence
        and not any(name in effective_message.lower() for name in BLAST_PROGRAMS)
        and sequence_type == "PROTEIN"
    ):
        program = "blastp"

    database_name = parse_blast_database(effective_message)
    length_text = f"{length} bp/aa" if length is not None else "unknown length"

    lines = [
        "Prepared a BLAST job plan.",
        "",
    ]

    if sample is not None:
        lines.append(f"Sample: {sample.sample_id}")

    lines.extend([
        f"Sequence: {label}",
        f"Sequence type: {sequence_type}",
        f"Sequence length: {length_text}",
        f"Program: {program}",
        f"Database: {database_name or 'not selected yet'}",
        "",
        "Status: not queued.",
    ])

    if program not in ["blastn", "blastp"]:
        lines.extend([
            "",
            f"{program} is not supported by the current BLAST job model. "
            "Choose blastn or blastp.",
        ])

        suggestions = ["Use blastn", "Use blastp"]

        return {
            "answer": "\n".join(lines),
            "links": links,
            "suggestions": suggestions,
            "skip_llm": True,
            "context": next_context,
        }

    expected_database_type = (
        "PROTEIN"
        if program == "blastp"
        else "DNA"
    )

    ready_database_names = list(
        BlastDatabase.objects.filter(
            status=BlastDatabase.STATUS_READY,
            database_type=expected_database_type,
        )
        .order_by("name")
        .values_list("name", flat=True)[:10]
    )

    database_suggestions = [
        f"Use database {name}"
        for name in ready_database_names[:3]
    ]

    if asks_to_use_sample_as_database(current_message):
        lines.extend([
            "",
            "A sample sequence is not a BLAST database. To compare two saved "
            "sequences, use an alignment. For BLAST, choose a READY local "
            f"{expected_database_type} database.",
        ])

        if ready_database_names:
            lines.append(
                "Ready databases: " + ", ".join(ready_database_names)
            )

        return {
            "answer": "\n".join(lines),
            "links": links,
            "suggestions": database_suggestions + [
                "Find sample sequences",
            ],
            "skip_llm": True,
            "context": next_context,
        }

    if not database_name:
        lines.extend([
            "",
            "No action can be confirmed yet. Choose a READY local BLAST "
            "database by name.",
        ])

        if ready_database_names:
            lines.append(
                "Ready databases: " + ", ".join(ready_database_names)
            )
        else:
            lines.append(
                f"No READY {expected_database_type} BLAST databases were found."
            )

        return {
            "answer": "\n".join(lines),
            "links": links,
            "suggestions": database_suggestions + [
                "Find sample sequences",
            ],
            "skip_llm": True,
            "context": next_context,
        }

    database = (
        BlastDatabase.objects
        .filter(
            name__iexact=database_name,
            status=BlastDatabase.STATUS_READY,
        )
        .first()
    )

    if database is None:
        target_sample = (
            apply_sample_access(user)
            .filter(sample_id__iexact=database_name)
            .first()
        )

        if target_sample is not None:
            explanation = (
                f"{database_name} is a sample, not a BLAST database. "
                "Use alignment to compare saved sequences, or choose a READY "
                f"{expected_database_type} BLAST database."
            )
        else:
            explanation = (
                f"I could not find a READY local BLAST database named "
                f"{database_name}. No action was proposed."
            )

        lines.extend(["", explanation])

        if ready_database_names:
            lines.append(
                "Ready databases: " + ", ".join(ready_database_names)
            )

        return {
            "answer": "\n".join(lines),
            "links": links,
            "suggestions": database_suggestions + [
                "Find sample sequences",
            ],
            "skip_llm": True,
            "context": next_context,
        }

    if database.database_type != expected_database_type:
        lines.extend([
            "",
            f"{program} requires a {expected_database_type} database, but "
            f"{database.name} is {database.database_type}. No action was proposed.",
        ])

        if ready_database_names:
            lines.append(
                "Compatible databases: " + ", ".join(ready_database_names)
            )

        return {
            "answer": "\n".join(lines),
            "links": links,
            "suggestions": database_suggestions,
            "skip_llm": True,
            "context": next_context,
        }

    if raw_sequence:
        summary = (
            f"Run {program} for a pasted {sequence_type} query "
            f"against {database.name}"
        )
        payload = {
            "name": "Assistant BLAST — pasted query",
            "database": database.id,
            "program": program,
            "max_target_seqs": 25,
            "evalue": "10",
            "raw_query": {
                "name": "Assistant pasted BLAST query",
                "sequence": raw_sequence,
                "sequence_type": sequence_type,
            },
        }
    else:
        summary = (
            f"Run {program} for {sample.sample_id} using {label} "
            f"against {database.name}"
        )
        payload = {
            "name": f"Assistant BLAST — {sample.sample_id}",
            "project": project_id,
            "query_sequence": sequence_obj.id,
            "database": database.id,
            "program": program,
            "max_target_seqs": 25,
            "evalue": "10",
        }

    payload = {
        key: value
        for key, value in payload.items()
        if value is not None
    }

    lines.extend([
        "",
        "Review the action details below. BLAST will run only after you confirm.",
    ])

    return {
        "answer": "\n".join(lines),
        "links": links,
        "suggestions": [
            "Summarize BLAST results",
            "Find sample sequences",
        ],
        "skip_llm": True,
        "context": {},
        "pending_action": {
            "type": "RUN_BLAST",
            "summary": summary,
            "payload": payload,
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


def route_assistant_sequence(message, user, context=None):
    text = str(message or "").strip()
    lower = text.lower()
    context = dict(context or {})

    pending_blast = context.get("intent") == "RUN_BLAST"

    if pending_blast and compact_command_text(text) in [
        "cancel",
        "cancel blast",
        "never mind",
        "nevermind",
        "start over",
    ]:
        return {
            "answer": "The pending BLAST request was cleared.",
            "links": [],
            "suggestions": [
                "Find sample sequences",
                "Prepare BLAST for sample",
            ],
            "skip_llm": True,
            "context": {},
        }

    starts_new_blast = contains_any_intent_phrase(
        text,
        [
            "run blast",
            "prepare blast",
            "start blast",
        ],
    )

    if pending_blast and starts_new_blast:
        context = {}
        pending_blast = False

    if pending_blast:
        still_about_sequences = any(
            term in lower
            for term in [
                "blast",
                "sequence",
                "sequences",
                "fasta",
                "nucleotide",
                "protein",
                "dna",
                "rna",
            ]
        )
        structured_follow_up = bool(
            re.search(
                r"\b(?:use|choose|select)\s+(?:sequence|database|blastn|blastp)\b",
                lower,
            )
            or re.search(r"\bsequence\s*#?\s*\d+\b", lower)
            or re.search(r"\b(?:blastn|blastp|blastx|tblastn|tblastx)\b", lower)
            or re.fullmatch(r"[A-Za-z]+[-_][A-Za-z0-9_-]+[.!?]?", text)
            or extract_raw_sequence(text)
        )
        if not still_about_sequences and not structured_follow_up:
            return None

        is_sequence_lookup = (
            any(term in lower for term in ["find", "show", "list"])
            and any(term in lower for term in ["sample", "sequence"])
        )

        if is_sequence_lookup:
            result = find_sample_sequences(text, user)
            result["context"] = context
            return result

        return prepare_blast_job(
            text,
            user,
            context=context,
        )

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
        if any(
            term in lower
            for term in [
                "result",
                "results",
                "summary",
                "summarize",
                "hits",
                "hit",
            ]
        ):
            return summarize_blast_results(text, user)

        return prepare_blast_job(
            text,
            user,
            context=context,
        )

    if any(term in lower for term in ["summarize", "summary", "overview", "count"]):
        return summarize_sequence_records(text, user)

    if any(term in lower for term in ["find", "show", "list", "sample"]):
        return find_sample_sequences(text, user)

    return summarize_sequence_records(text, user)
