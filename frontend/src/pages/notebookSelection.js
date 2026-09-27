// Explicit links must never silently select another experiment.
export function selectNotebookRecord({ notebooks, experiments, experimentId, notebookId, strict = false }) {
  const matches = (row, value) => value != null && (String(row.id) === String(value) || String(row.public_id) === String(value));
  const requestedExperiment = experiments.find(row => matches(row, experimentId));
  if (strict && experimentId != null && !requestedExperiment) return { notebook: null, experiment: null, unavailable: true };
  const requestedNotebookId = notebookId ?? requestedExperiment?.notebook;
  const requestedNotebook = notebooks.find(row => matches(row, requestedNotebookId));
  if (strict && requestedNotebookId != null && !requestedNotebook) return { notebook: null, experiment: null, unavailable: true };
  const notebook = requestedNotebook || notebooks[0] || null;
  const rows = experiments.filter(row => String(row.notebook) === String(notebook?.id));
  return { notebook, experiment: rows.find(row => matches(row, experimentId)) || rows[0] || null, unavailable: false };
}
