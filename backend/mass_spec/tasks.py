from celery import shared_task
from django.utils import timezone

from events.models import Event

from .models import MassSpecRun


def _safe_min(current, value):
    if value is None:
        return current
    if current is None:
        return value
    return min(current, value)


def _safe_max(current, value):
    if value is None:
        return current
    if current is None:
        return value
    return max(current, value)


def _safe_avg(values):
    values = [value for value in values if value is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _safe_call(obj, method_name, default=None):
    try:
        return getattr(obj, method_name)()
    except Exception:
        return default


def _file_kind(path):
    lower_path = path.lower()

    if lower_path.endswith(".featurexml"):
        return "featurexml"
    if lower_path.endswith(".consensusxml"):
        return "consensusxml"
    if lower_path.endswith(".mzid") or lower_path.endswith(".mzidentml"):
        return "mzidentml"
    if lower_path.endswith(".mzml"):
        return "mzml"
    if lower_path.endswith(".mzxml"):
        return "mzxml"
    if lower_path.endswith(".mzdata"):
        return "mzdata"

    raise ValueError(
        "Unsupported mass spec file type. Use mzML, mzXML, mzData, featureXML, consensusXML, mzID, or mzIdentML."
    )


def _load_experiment(path):
    import pyopenms as oms

    experiment = oms.MSExperiment()
    kind = _file_kind(path)

    if kind == "mzml":
        loader = oms.MzMLFile()
    elif kind == "mzxml":
        loader = oms.MzXMLFile()
    elif kind == "mzdata":
        loader = oms.MzDataFile()
    else:
        raise ValueError("This file type is not a raw spectrum experiment.")

    loader.load(path, experiment)
    return experiment


def _parse_featurexml(path):
    import pyopenms as oms

    feature_map = oms.FeatureMap()
    oms.FeatureXMLFile().load(path, feature_map)

    features = []

    for feature in feature_map:
        features.append(
            {
                "mz": float(_safe_call(feature, "getMZ", 0.0) or 0.0),
                "rt": float(_safe_call(feature, "getRT", 0.0) or 0.0),
                "intensity": float(_safe_call(feature, "getIntensity", 0.0) or 0.0),
                "charge": _safe_call(feature, "getCharge", None),
            }
        )

    top_features = sorted(
        features,
        key=lambda item: item["intensity"],
        reverse=True,
    )[:50]

    return {
        "featurexml_count": len(features),
        "consensusxml_count": 0,
        "detected_features": [
            {
                "mz": item["mz"],
                "rt_min": item["rt"],
                "rt_max": item["rt"],
                "apex_rt": item["rt"],
                "apex_intensity": item["intensity"],
                "total_intensity": item["intensity"],
                "peak_count": 1,
                "ms_level": 1,
                "charge": item["charge"],
            }
            for item in top_features
        ],
        "openms_summary": {
            "file_type": "featureXML",
            "feature_count": len(features),
            "top_features": top_features,
        },
    }


def _parse_consensusxml(path):
    import pyopenms as oms

    consensus_map = oms.ConsensusMap()
    oms.ConsensusXMLFile().load(path, consensus_map)

    consensus_features = []

    for feature in consensus_map:
        consensus_features.append(
            {
                "mz": float(_safe_call(feature, "getMZ", 0.0) or 0.0),
                "rt": float(_safe_call(feature, "getRT", 0.0) or 0.0),
                "intensity": float(_safe_call(feature, "getIntensity", 0.0) or 0.0),
                "charge": _safe_call(feature, "getCharge", None),
            }
        )

    top_consensus = sorted(
        consensus_features,
        key=lambda item: item["intensity"],
        reverse=True,
    )[:50]

    return {
        "featurexml_count": 0,
        "consensusxml_count": len(consensus_features),
        "detected_features": [
            {
                "mz": item["mz"],
                "rt_min": item["rt"],
                "rt_max": item["rt"],
                "apex_rt": item["rt"],
                "apex_intensity": item["intensity"],
                "total_intensity": item["intensity"],
                "peak_count": 1,
                "ms_level": 1,
                "charge": item["charge"],
            }
            for item in top_consensus
        ],
        "openms_summary": {
            "file_type": "consensusXML",
            "consensus_count": len(consensus_features),
            "top_consensus_features": top_consensus,
        },
    }


def _strip_namespace(tag):
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _xml_attr(element, name, default=None):
    return element.attrib.get(name, default)


def _parse_mzidentml(path):
    import xml.etree.ElementTree as ET

    tree = ET.parse(path)
    root = tree.getroot()

    proteins_by_id = {}
    peptides_by_id = {}
    peptide_evidence = {}
    peptide_hits = []

    for element in root.iter():
        tag = _strip_namespace(element.tag)

        if tag == "DBSequence":
            protein_id = _xml_attr(element, "id")
            accession = _xml_attr(element, "accession", protein_id)
            if protein_id:
                proteins_by_id[protein_id] = {
                    "id": protein_id,
                    "accession": accession,
                    "description": _xml_attr(element, "name", ""),
                    "peptide_count": 0,
                    "score": 0.0,
                }

        elif tag == "Peptide":
            peptide_id = _xml_attr(element, "id")
            sequence = ""

            for child in element:
                if _strip_namespace(child.tag) == "PeptideSequence":
                    sequence = child.text or ""
                    break

            if peptide_id:
                peptides_by_id[peptide_id] = {
                    "id": peptide_id,
                    "sequence": sequence,
                    "score": 0.0,
                    "protein_accessions": [],
                    "charge": None,
                    "experimental_mz": None,
                    "calculated_mz": None,
                }

        elif tag == "PeptideEvidence":
            evidence_id = _xml_attr(element, "id")
            peptide_ref = _xml_attr(element, "peptide_ref")
            protein_ref = _xml_attr(element, "dBSequence_ref") or _xml_attr(element, "DBSequence_ref")

            if evidence_id:
                peptide_evidence[evidence_id] = {
                    "peptide_ref": peptide_ref,
                    "protein_ref": protein_ref,
                }

    for element in root.iter():
        tag = _strip_namespace(element.tag)

        if tag != "SpectrumIdentificationItem":
            continue

        peptide_ref = _xml_attr(element, "peptide_ref")
        if not peptide_ref:
            continue

        score = None
        score_name = None

        for child in element:
            child_tag = _strip_namespace(child.tag)

            if child_tag == "cvParam":
                value = _xml_attr(child, "value")
                name = _xml_attr(child, "name")

                if value is not None:
                    try:
                        numeric_value = float(value)
                        if score is None:
                            score = numeric_value
                            score_name = name
                    except ValueError:
                        pass

        evidence_refs = []
        for child in element:
            if _strip_namespace(child.tag) == "PeptideEvidenceRef":
                ref = _xml_attr(child, "peptideEvidence_ref")
                if ref:
                    evidence_refs.append(ref)

        protein_accessions = []

        for evidence_ref in evidence_refs:
            evidence = peptide_evidence.get(evidence_ref, {})
            protein_ref = evidence.get("protein_ref")
            protein = proteins_by_id.get(protein_ref)

            if protein:
                protein_accessions.append(protein["accession"])
                protein["peptide_count"] += 1
                if score is not None:
                    protein["score"] += score

        peptide = peptides_by_id.get(
            peptide_ref,
            {
                "id": peptide_ref,
                "sequence": peptide_ref,
                "score": 0.0,
                "protein_accessions": [],
                "charge": None,
                "experimental_mz": None,
                "calculated_mz": None,
            },
        )

        if score is not None:
            peptide["score"] = max(float(peptide.get("score") or 0.0), score)

        peptide["score_name"] = score_name
        peptide["protein_accessions"] = sorted(set(protein_accessions))
        peptide["charge"] = _xml_attr(element, "chargeState")
        peptide["experimental_mz"] = _xml_attr(element, "experimentalMassToCharge")
        peptide["calculated_mz"] = _xml_attr(element, "calculatedMassToCharge")
        peptide["rank"] = _xml_attr(element, "rank")
        peptide["pass_threshold"] = _xml_attr(element, "passThreshold")

        peptides_by_id[peptide_ref] = peptide
        peptide_hits.append(peptide)

    top_proteins = sorted(
        proteins_by_id.values(),
        key=lambda item: (item.get("peptide_count") or 0, item.get("score") or 0.0),
        reverse=True,
    )[:50]

    top_peptides = sorted(
        peptide_hits or peptides_by_id.values(),
        key=lambda item: item.get("score") or 0.0,
        reverse=True,
    )[:50]

    protein_count = len(
        [protein for protein in proteins_by_id.values() if protein.get("peptide_count", 0) > 0]
    ) or len(proteins_by_id)

    peptide_count = len(peptides_by_id)

    return {
        "file_type": "mzIdentML",
        "protein_count": protein_count,
        "peptide_count": peptide_count,
        "top_proteins": top_proteins,
        "top_peptides": top_peptides,
        "note": "Protein and peptide identifications parsed from mzIdentML.",
    }


def _finish_identification_file(run, id_summary):
    run.status = MassSpecRun.STATUS_COMPLETED
    run.spectra_count = 0
    run.ms1_count = 0
    run.ms2_count = 0
    run.rt_min = None
    run.rt_max = None
    run.mz_min = None
    run.mz_max = None
    run.chromatogram_data = []
    run.peak_count = 0
    run.base_peak_mz = None
    run.base_peak_intensity = None
    run.top_peaks = []
    run.feature_count = 0
    run.detected_features = []
    run.featurexml_count = 0
    run.consensusxml_count = 0
    run.openms_summary = {
        "file_type": "mzIdentML",
        "protein_count": id_summary["protein_count"],
        "peptide_count": id_summary["peptide_count"],
    }
    run.protein_count = id_summary["protein_count"]
    run.peptide_count = id_summary["peptide_count"]
    run.top_proteins = id_summary["top_proteins"]
    run.top_peptides = id_summary["top_peptides"]
    run.identification_summary = id_summary
    run.total_ion_current = None
    run.mean_total_intensity = None
    run.max_total_intensity = None
    run.mean_peak_intensity = None
    run.rt_span = None
    run.mz_span = None
    run.ms1_ratio = None
    run.ms2_ratio = None
    run.processed_at = timezone.now()
    run.error_message = ""

    run.save(
        update_fields=[
            "status",
            "spectra_count",
            "ms1_count",
            "ms2_count",
            "rt_min",
            "rt_max",
            "mz_min",
            "mz_max",
            "chromatogram_data",
            "peak_count",
            "base_peak_mz",
            "base_peak_intensity",
            "top_peaks",
            "feature_count",
            "detected_features",
            "featurexml_count",
            "consensusxml_count",
            "openms_summary",
            "protein_count",
            "peptide_count",
            "top_proteins",
            "top_peptides",
            "identification_summary",
            "total_ion_current",
            "mean_total_intensity",
            "max_total_intensity",
            "mean_peak_intensity",
            "rt_span",
            "mz_span",
            "ms1_ratio",
            "ms2_ratio",
            "processed_at",
            "error_message",
        ]
    )

    Event.objects.create(
        entity_type="mass_spec_run",
        entity_id=str(run.id),
        action="MZIDENTML_PARSED",
        actor=run.uploaded_by,
        payload={
            "name": run.name,
            "original_filename": run.original_filename,
            "file_type": "mzIdentML",
            "protein_count": run.protein_count,
            "peptide_count": run.peptide_count,
        },
    )


def _pick_peaks(experiment):
    import pyopenms as oms

    picked_experiment = oms.MSExperiment()

    try:
        picker = oms.PeakPickerHiRes()
        picker.pickExperiment(experiment, picked_experiment)
        return picked_experiment, True
    except Exception:
        return experiment, False


def _extract_peak_summary(experiment):
    peak_count = 0
    base_peak_mz = None
    base_peak_intensity = None
    top_peaks = []
    peak_intensities = []

    for spectrum in experiment:
        rt = float(spectrum.getRT())
        ms_level = spectrum.getMSLevel()
        mz_values, intensity_values = spectrum.get_peaks()

        if not len(mz_values):
            continue

        for mz, intensity in zip(mz_values, intensity_values):
            mz = float(mz)
            intensity = float(intensity)
            peak_count += 1
            peak_intensities.append(intensity)

            if base_peak_intensity is None or intensity > base_peak_intensity:
                base_peak_mz = mz
                base_peak_intensity = intensity

            top_peaks.append(
                {
                    "rt": rt,
                    "mz": mz,
                    "intensity": intensity,
                    "ms_level": ms_level,
                }
            )

            if len(top_peaks) > 250:
                top_peaks = sorted(
                    top_peaks,
                    key=lambda peak: peak["intensity"],
                    reverse=True,
                )[:100]

    top_peaks = sorted(
        top_peaks,
        key=lambda peak: peak["intensity"],
        reverse=True,
    )[:25]

    return {
        "peak_count": peak_count,
        "base_peak_mz": base_peak_mz,
        "base_peak_intensity": base_peak_intensity,
        "top_peaks": top_peaks,
        "mean_peak_intensity": _safe_avg(peak_intensities),
    }


def _detect_features(experiment):
    raw_peaks = []

    for spectrum in experiment:
        rt = float(spectrum.getRT())
        ms_level = spectrum.getMSLevel()
        mz_values, intensity_values = spectrum.get_peaks()

        if not len(mz_values):
            continue

        for mz, intensity in zip(mz_values, intensity_values):
            raw_peaks.append(
                {
                    "rt": rt,
                    "mz": float(mz),
                    "intensity": float(intensity),
                    "ms_level": ms_level,
                }
            )

    if not raw_peaks:
        return {"feature_count": 0, "detected_features": []}

    max_intensity = max(peak["intensity"] for peak in raw_peaks)
    intensity_threshold = max_intensity * 0.05
    candidate_peaks = [
        peak for peak in raw_peaks if peak["intensity"] >= intensity_threshold
    ] or raw_peaks

    ms1_candidates = [peak for peak in candidate_peaks if peak["ms_level"] == 1]
    if ms1_candidates:
        candidate_peaks = ms1_candidates

    candidate_peaks = sorted(candidate_peaks, key=lambda peak: peak["mz"])
    groups = []
    mz_tolerance = 1.0

    for peak in candidate_peaks:
        matched_group = None

        for group in groups:
            if abs(peak["mz"] - group["mz_mean"]) <= mz_tolerance:
                matched_group = group
                break

        if matched_group is None:
            groups.append({"peaks": [peak], "mz_mean": peak["mz"]})
        else:
            matched_group["peaks"].append(peak)
            matched_group["mz_mean"] = _safe_avg(
                [item["mz"] for item in matched_group["peaks"]]
            )

    detected_features = []

    for group in groups:
        peaks = group["peaks"]
        mz_values = [peak["mz"] for peak in peaks]
        rt_values = [peak["rt"] for peak in peaks]
        intensities = [peak["intensity"] for peak in peaks]
        apex_peak = max(peaks, key=lambda peak: peak["intensity"])

        detected_features.append(
            {
                "mz": _safe_avg(mz_values),
                "rt_min": min(rt_values),
                "rt_max": max(rt_values),
                "apex_rt": apex_peak["rt"],
                "apex_intensity": apex_peak["intensity"],
                "total_intensity": sum(intensities),
                "peak_count": len(peaks),
                "ms_level": apex_peak["ms_level"],
            }
        )

    detected_features = sorted(
        detected_features,
        key=lambda feature: feature["total_intensity"],
        reverse=True,
    )[:50]

    return {
        "feature_count": len(detected_features),
        "detected_features": detected_features,
    }


def _extract_quality_metrics(
    *,
    spectra_count,
    ms1_count,
    ms2_count,
    rt_min,
    rt_max,
    mz_min,
    mz_max,
    chromatogram_data,
    peak_summary,
):
    total_intensities = [
        float(point.get("total_intensity", 0.0))
        for point in chromatogram_data
        if point.get("total_intensity") is not None
    ]

    total_ion_current = sum(total_intensities) if total_intensities else None
    mean_total_intensity = _safe_avg(total_intensities)
    max_total_intensity = max(total_intensities) if total_intensities else None

    rt_span = rt_max - rt_min if rt_min is not None and rt_max is not None else None
    mz_span = mz_max - mz_min if mz_min is not None and mz_max is not None else None

    ms1_ratio = ms1_count / spectra_count if spectra_count else None
    ms2_ratio = ms2_count / spectra_count if spectra_count else None

    return {
        "total_ion_current": total_ion_current,
        "mean_total_intensity": mean_total_intensity,
        "max_total_intensity": max_total_intensity,
        "mean_peak_intensity": peak_summary.get("mean_peak_intensity"),
        "rt_span": rt_span,
        "mz_span": mz_span,
        "ms1_ratio": ms1_ratio,
        "ms2_ratio": ms2_ratio,
    }


def _empty_identification_summary(file_type):
    return {
        "file_type": file_type,
        "protein_count": 0,
        "peptide_count": 0,
        "top_proteins": [],
        "top_peptides": [],
        "note": "No protein or peptide identifications parsed for this file type yet.",
    }


def _finish_openms_file(run, parsed, action_name):
    detected_features = parsed["detected_features"]

    run.status = MassSpecRun.STATUS_COMPLETED
    run.spectra_count = 0
    run.ms1_count = 0
    run.ms2_count = 0
    run.rt_min = None
    run.rt_max = None
    run.mz_min = None
    run.mz_max = None
    run.chromatogram_data = []
    run.peak_count = 0
    run.base_peak_mz = None
    run.base_peak_intensity = None
    run.top_peaks = []
    run.feature_count = len(detected_features)
    run.detected_features = detected_features
    run.featurexml_count = parsed["featurexml_count"]
    run.consensusxml_count = parsed["consensusxml_count"]
    run.openms_summary = parsed["openms_summary"]
    id_summary = _empty_identification_summary(parsed["openms_summary"].get("file_type"))
    run.protein_count = id_summary["protein_count"]
    run.peptide_count = id_summary["peptide_count"]
    run.top_proteins = id_summary["top_proteins"]
    run.top_peptides = id_summary["top_peptides"]
    run.identification_summary = id_summary
    run.total_ion_current = None
    run.mean_total_intensity = None
    run.max_total_intensity = None
    run.mean_peak_intensity = None
    run.rt_span = None
    run.mz_span = None
    run.ms1_ratio = None
    run.ms2_ratio = None
    run.processed_at = timezone.now()
    run.error_message = ""

    run.save(
        update_fields=[
            "status",
            "spectra_count",
            "ms1_count",
            "ms2_count",
            "rt_min",
            "rt_max",
            "mz_min",
            "mz_max",
            "chromatogram_data",
            "peak_count",
            "base_peak_mz",
            "base_peak_intensity",
            "top_peaks",
            "feature_count",
            "detected_features",
            "featurexml_count",
            "consensusxml_count",
            "openms_summary",
            "protein_count",
            "peptide_count",
            "top_proteins",
            "top_peptides",
            "identification_summary",
            "total_ion_current",
            "mean_total_intensity",
            "max_total_intensity",
            "mean_peak_intensity",
            "rt_span",
            "mz_span",
            "ms1_ratio",
            "ms2_ratio",
            "processed_at",
            "error_message",
        ]
    )

    Event.objects.create(
        entity_type="mass_spec_run",
        entity_id=str(run.id),
        action=action_name,
        actor=run.uploaded_by,
        payload={
            "name": run.name,
            "original_filename": run.original_filename,
            "featurexml_count": parsed["featurexml_count"],
            "consensusxml_count": parsed["consensusxml_count"],
            "feature_count": len(detected_features),
            "file_type": parsed["openms_summary"].get("file_type"),
            "protein_count": run.protein_count,
            "peptide_count": run.peptide_count,
        },
    )


@shared_task
def process_mass_spec_run_task(run_id):
    run = MassSpecRun.objects.get(id=run_id)

    run.status = MassSpecRun.STATUS_RUNNING
    run.error_message = ""
    run.save(update_fields=["status", "error_message"])

    try:
        kind = _file_kind(run.uploaded_file.path)

        if kind == "featurexml":
            parsed = _parse_featurexml(run.uploaded_file.path)
            _finish_openms_file(run, parsed, "FEATUREXML_PARSED")
            return

        if kind == "consensusxml":
            parsed = _parse_consensusxml(run.uploaded_file.path)
            _finish_openms_file(run, parsed, "CONSENSUSXML_PARSED")
            return

        if kind == "mzidentml":
            id_summary = _parse_mzidentml(run.uploaded_file.path)
            _finish_identification_file(run, id_summary)
            return

        experiment = _load_experiment(run.uploaded_file.path)

        spectra_count = 0
        ms1_count = 0
        ms2_count = 0
        rt_min = None
        rt_max = None
        mz_min = None
        mz_max = None
        chromatogram_data = []

        for spectrum in experiment:
            spectra_count += 1
            ms_level = spectrum.getMSLevel()

            if ms_level == 1:
                ms1_count += 1
            elif ms_level == 2:
                ms2_count += 1

            rt = float(spectrum.getRT())
            rt_min = _safe_min(rt_min, rt)
            rt_max = _safe_max(rt_max, rt)

            mz_values, intensity_values = spectrum.get_peaks()
            total_intensity = float(intensity_values.sum()) if len(intensity_values) else 0.0

            chromatogram_data.append(
                {
                    "rt": rt,
                    "total_intensity": total_intensity,
                    "ms_level": ms_level,
                }
            )

            if len(mz_values):
                mz_min = _safe_min(mz_min, float(mz_values.min()))
                mz_max = _safe_max(mz_max, float(mz_values.max()))

        picked_experiment, peak_picking_applied = _pick_peaks(experiment)
        peak_summary = _extract_peak_summary(picked_experiment)
        feature_summary = _detect_features(picked_experiment)

        quality_metrics = _extract_quality_metrics(
            spectra_count=spectra_count,
            ms1_count=ms1_count,
            ms2_count=ms2_count,
            rt_min=rt_min,
            rt_max=rt_max,
            mz_min=mz_min,
            mz_max=mz_max,
            chromatogram_data=chromatogram_data,
            peak_summary=peak_summary,
        )

        run.status = MassSpecRun.STATUS_COMPLETED
        run.spectra_count = spectra_count
        run.ms1_count = ms1_count
        run.ms2_count = ms2_count
        run.rt_min = rt_min
        run.rt_max = rt_max
        run.mz_min = mz_min
        run.mz_max = mz_max
        run.chromatogram_data = chromatogram_data
        run.peak_count = peak_summary["peak_count"]
        run.base_peak_mz = peak_summary["base_peak_mz"]
        run.base_peak_intensity = peak_summary["base_peak_intensity"]
        run.top_peaks = peak_summary["top_peaks"]
        run.feature_count = feature_summary["feature_count"]
        run.detected_features = feature_summary["detected_features"]
        run.featurexml_count = 0
        run.consensusxml_count = 0
        run.openms_summary = {
            "file_type": kind,
            "peak_picking_applied": peak_picking_applied,
        }
        id_summary = _empty_identification_summary(kind)
        run.protein_count = id_summary["protein_count"]
        run.peptide_count = id_summary["peptide_count"]
        run.top_proteins = id_summary["top_proteins"]
        run.top_peptides = id_summary["top_peptides"]
        run.identification_summary = id_summary
        run.total_ion_current = quality_metrics["total_ion_current"]
        run.mean_total_intensity = quality_metrics["mean_total_intensity"]
        run.max_total_intensity = quality_metrics["max_total_intensity"]
        run.mean_peak_intensity = quality_metrics["mean_peak_intensity"]
        run.rt_span = quality_metrics["rt_span"]
        run.mz_span = quality_metrics["mz_span"]
        run.ms1_ratio = quality_metrics["ms1_ratio"]
        run.ms2_ratio = quality_metrics["ms2_ratio"]
        run.processed_at = timezone.now()
        run.error_message = ""

        run.save(
            update_fields=[
                "status",
                "spectra_count",
                "ms1_count",
                "ms2_count",
                "rt_min",
                "rt_max",
                "mz_min",
                "mz_max",
                "chromatogram_data",
                "peak_count",
                "base_peak_mz",
                "base_peak_intensity",
                "top_peaks",
                "feature_count",
                "detected_features",
                "featurexml_count",
                "consensusxml_count",
                "openms_summary",
                "protein_count",
                "peptide_count",
                "top_proteins",
                "top_peptides",
                "identification_summary",
                "total_ion_current",
                "mean_total_intensity",
                "max_total_intensity",
                "mean_peak_intensity",
                "rt_span",
                "mz_span",
                "ms1_ratio",
                "ms2_ratio",
                "processed_at",
                "error_message",
            ]
        )

        Event.objects.create(
            entity_type="mass_spec_run",
            entity_id=str(run.id),
            action="MASS_SPEC_PROCESSED",
            actor=run.uploaded_by,
            payload={
                "name": run.name,
                "original_filename": run.original_filename,
                "spectra_count": spectra_count,
                "ms1_count": ms1_count,
                "ms2_count": ms2_count,
                "chromatogram_points": len(chromatogram_data),
                "peak_count": peak_summary["peak_count"],
                "base_peak_mz": peak_summary["base_peak_mz"],
                "base_peak_intensity": peak_summary["base_peak_intensity"],
                "feature_count": feature_summary["feature_count"],
                "peak_picking_applied": peak_picking_applied,
                "total_ion_current": quality_metrics["total_ion_current"],
                "mean_total_intensity": quality_metrics["mean_total_intensity"],
                "max_total_intensity": quality_metrics["max_total_intensity"],
                "mean_peak_intensity": quality_metrics["mean_peak_intensity"],
                "rt_span": quality_metrics["rt_span"],
                "mz_span": quality_metrics["mz_span"],
                "ms1_ratio": quality_metrics["ms1_ratio"],
                "ms2_ratio": quality_metrics["ms2_ratio"],
                "protein_count": run.protein_count,
                "peptide_count": run.peptide_count,
            },
        )

    except Exception as e:
        run.status = MassSpecRun.STATUS_FAILED
        run.error_message = str(e)
        run.processed_at = timezone.now()
        run.save(update_fields=["status", "error_message", "processed_at"])

        Event.objects.create(
            entity_type="mass_spec_run",
            entity_id=str(run.id),
            action="MASS_SPEC_FAILED",
            actor=run.uploaded_by,
            payload={
                "name": run.name,
                "original_filename": run.original_filename,
                "error": str(e),
            },
        )

        raise
