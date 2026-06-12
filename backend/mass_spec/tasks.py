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


def _load_experiment(path):
    import pyopenms as oms

    experiment = oms.MSExperiment()
    lower_path = path.lower()

    if lower_path.endswith(".mzml"):
        loader = oms.MzMLFile()
    elif lower_path.endswith(".mzxml"):
        loader = oms.MzXMLFile()
    elif lower_path.endswith(".mzdata"):
        loader = oms.MzDataFile()
    else:
        raise ValueError("Unsupported mass spec file type. Use mzML, mzXML, or mzData.")

    loader.load(path, experiment)
    return experiment


def _pick_peaks(experiment):
    import pyopenms as oms

    picked_experiment = oms.MSExperiment()

    try:
        picker = oms.PeakPickerHiRes()
        picker.pickExperiment(experiment, picked_experiment)
        return picked_experiment, True
    except Exception:
        # Some demo or centroided files may not be suitable for PeakPickerHiRes.
        # Fall back to original spectra so OpenLIMS still provides a useful peak summary.
        return experiment, False


def _extract_peak_summary(experiment):
    peak_count = 0
    base_peak_mz = None
    base_peak_intensity = None
    top_peaks = []

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

            # Keep memory bounded for larger files.
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
    }


@shared_task
def process_mass_spec_run_task(run_id):
    run = MassSpecRun.objects.get(id=run_id)

    run.status = MassSpecRun.STATUS_RUNNING
    run.error_message = ""
    run.save(update_fields=["status", "error_message"])

    try:
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

            total_intensity = 0.0

            if len(intensity_values):
                total_intensity = float(intensity_values.sum())

            chromatogram_data.append(
                {
                    "rt": rt,
                    "total_intensity": total_intensity,
                    "ms_level": ms_level,
                }
            )

            if len(mz_values):
                local_mz_min = float(mz_values.min())
                local_mz_max = float(mz_values.max())

                mz_min = _safe_min(mz_min, local_mz_min)
                mz_max = _safe_max(mz_max, local_mz_max)

        picked_experiment, peak_picking_applied = _pick_peaks(experiment)
        peak_summary = _extract_peak_summary(picked_experiment)

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
                "peak_picking_applied": peak_picking_applied,
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
