# Complete lab workflow regression tests

Run from `backend` with project dependencies installed:

```sh
pytest -v core/tests/test_complete_lab_workflow.py
```

The existing CI `pytest -v` job discovers these tests and runs them against its
PostgreSQL database. Local runs may use SQLite. They exercise real DRF views,
serializers, permissions, pipeline signals, database writes and PDF generation.
Authentication is supplied by APIClient; these are API integration tests, not
browser login tests. Uploaded files use an isolated temporary media directory.

## Journeys

- An administrator configures extraction and sequencing steps through the API.
  A technician registers a sample and starts the pipeline. Missing measurements
  prevent completion; recording a result permits completion but does not skip QC.
  An independent reviewer approves each gate. The technician links a DNA sequence,
  uploads a results file, records a storage move, creates and edits a linked notebook
  experiment, and completes it. A reader retrieves the stored records and exports
  a PDF. Assertions verify sample links, storage, reviewer identity and audit events.
- Rejected extraction QC blocks the pipeline and prevents downstream work creation,
  while preserving the measured value and attributed rejection reason.
- A viewer can read but cannot change records. An outsider and a technician whose
  membership is revoked cannot retrieve the sample, pipeline, work or results, or
  overwrite the stored result. Unauthorized notebook export and linked sequence/file
  retrieval are also checked in the successful journey.

The sequencing portion records a sequence and its QC score; it does not operate a
sequencer or run external analysis software. The exported report is the notebook
experiment PDF. Existing browser, notebook concurrency and module-specific tests
remain complementary coverage. No production data or live server is used.

## Español

Estas pruebas recorren las API reales desde el registro de una muestra hasta QC,
secuencias y archivos vinculados, almacenamiento, bitácora y exportación PDF.
También verifican rechazo de QC, permisos de lectura y pérdida de acceso al revocar
la membresía. Se ejecutan con el comando anterior y automáticamente en CI.
No controlan equipos de secuenciación ni prueban el inicio de sesión del navegador.
