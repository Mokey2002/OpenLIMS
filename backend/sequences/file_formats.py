import io

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqFeature import ExactPosition, FeatureLocation, SeqFeature
from Bio.SeqRecord import SeqRecord


def parse_sequence_file(content, file_format):
    normalized = str(file_format or "").lower()
    bio_format = "genbank" if normalized in {"genbank", "gb", "gbk"} else "fasta"
    records = []
    for source in SeqIO.parse(io.StringIO(content), bio_format):
        molecule_type = str(source.annotations.get("molecule_type", "DNA")).upper()
        sequence_type = "RNA" if "RNA" in molecule_type else ("PROTEIN" if "PROTEIN" in molecule_type else "DNA")
        topology = str(source.annotations.get("topology", "linear")).upper()
        features = []
        for feature in source.features:
            if feature.type == "source":
                continue
            if not isinstance(feature.location.start, ExactPosition) or not isinstance(feature.location.end, ExactPosition):
                continue
            qualifiers = {
                key: value if len(value) != 1 else value[0]
                for key, value in feature.qualifiers.items()
            }
            name = qualifiers.get("label") or qualifiers.get("gene") or qualifiers.get("note") or feature.type
            if isinstance(name, list):
                name = name[0] if name else feature.type
            features.append({
                "feature_type": "PRIMER" if "primer" in feature.type.lower() else "ANNOTATION",
                "name": str(name),
                "start": int(feature.location.start),
                "end": int(feature.location.end),
                "direction": int(feature.location.strand or 1),
                "color": "#9333ea" if "primer" in feature.type.lower() else "#22c55e",
                "metadata": {"genbank_type": feature.type, "qualifiers": qualifiers},
            })
        records.append({
            "name": source.name if source.name != "<unknown name>" else source.id,
            "description": source.description if source.description != "<unknown description>" else "",
            "sequence_type": sequence_type,
            "topology": "CIRCULAR" if topology == "CIRCULAR" else "LINEAR",
            "sequence": str(source.seq).upper(),
            "features": features,
            "source_metadata": {
                "format": bio_format,
                "id": source.id,
                "annotations": source.annotations,
                "dbxrefs": source.dbxrefs,
            },
        })
    return records


def export_sequence_revision(revision, file_format):
    normalized = str(file_format or "").lower()
    bio_format = "genbank" if normalized in {"genbank", "gb", "gbk"} else "fasta"
    record = SeqRecord(
        Seq(revision.sequence),
        id=str(revision.sequence_record.public_id),
        name=revision.sequence_record.name[:16] or "sequence",
        description=revision.sequence_record.description,
    )
    if bio_format == "genbank":
        record.annotations["molecule_type"] = revision.sequence_type
        record.annotations["topology"] = revision.topology.lower()
        for feature in revision.features.all():
            metadata = feature.metadata or {}
            qualifiers = metadata.get("qualifiers", {})
            qualifiers = {
                key: value if isinstance(value, list) else [str(value)]
                for key, value in qualifiers.items()
            }
            qualifiers.setdefault("label", [feature.name])
            record.features.append(
                SeqFeature(
                    FeatureLocation(feature.start, feature.end, strand=feature.direction),
                    type=metadata.get("genbank_type") or (
                        "primer_bind" if feature.feature_type == "PRIMER" else "misc_feature"
                    ),
                    qualifiers=qualifiers,
                )
            )
    output = io.StringIO()
    SeqIO.write(record, output, bio_format)
    return output.getvalue()
