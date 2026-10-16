// Route state is a proposal, never a trusted API payload or a saved template.
export function workflowDraftSteps(draft, procedures, emptyStep) {
  if (!draft || !Array.isArray(draft.steps) || !draft.steps.length || draft.steps.length > 30) return null;
  const steps = [];
  for (const proposed of draft.steps) {
    const procedure = procedures.find(row => row.id === proposed?.procedure && row.active && row.code === proposed.code && row.version === proposed.version);
    if (!procedure) return null;
    steps.push({ ...emptyStep(), procedure: String(procedure.id), name: procedure.name });
  }
  return steps;
}
