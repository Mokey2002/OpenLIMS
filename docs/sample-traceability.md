# Sample record / Ficha de muestra

## English

Open **Samples**, then select a sample. The record keeps its pipeline, storage,
sequences, instrument runs, results, files, QC review and sample history together.
Use the section links near the top to jump to experiments, results, files or history.

- **Linked Experiments** shows experiments whose **current saved revision** links
  to this sample. In the notebook, add a sample in Links and save a revision.
  The sample record shows notebook, experiment status and completed workflow steps.
  Open the experiment for its detailed procedure, files and revision history.
- Only notebooks you can read are included. A disabled notebook module exposes
  no experiments. Removed links remain in experiment revision history but are
  not presented as current sample links. Unsaved links are not included.
- **Result Values** shows the source work item, work status, QC status and import
  source. Click the work item to jump to its results and QC controls on this page.
  Work completion and QC approval are separate states.
- **Sample Attachments** includes direct uploads and accessible shared attachments
  targeting this sample. Experiment attachments remain in their experiment.
- **Chain of Custody Timeline** is the sample's audit history, not the global audit
  log. Both numeric legacy IDs and stable public IDs are supported. Experiment
  revisions and their own audit history remain in the notebook.

The page follows pagination for sample history, experiments, work items, sample
files, sequences, instrument runs and pipeline runs. Large records can take longer
to load; failed requests show an error rather than a silently incomplete record.
No database migration is required by this release. Update backend and frontend
together: the frontend uses the new paginated, sample-access-checked GET endpoints
`/api/v1/samples/{id}/history/` and `/api/v1/samples/{id}/experiments/`.

## Español

Abre **Samples** y selecciona una muestra. Usa los enlaces superiores para ir a
experimentos, resultados, archivos e historial.

- Vincula la muestra en **Links** del experimento y guarda una revisión. Solo se
  muestran vínculos de la revisión actual y bitácoras a las que tienes acceso.
- Abre el experimento para consultar procedimiento, archivos e historial de
  revisiones. Los vínculos eliminados siguen en las revisiones anteriores.
- En **Result Values**, revisa el estado del trabajo y del control de calidad;
  pulsa el trabajo para saltar a sus resultados y controles. Aprobar el control
  de calidad no equivale a completar el trabajo.
- **Sample Attachments** reúne archivos directos y compartidos de la muestra.
  Los archivos del experimento se consultan dentro del experimento.
- El historial incluye los eventos de la muestra, incluso los antiguos; el
  historial propio del experimento permanece en la bitácora.

Actualiza backend e interfaz juntos. Esta versión no requiere migraciones nuevas.
