// Navigation guidance only: server permissions, validation and transitions remain authoritative.
export function sampleNextStep(sample, allowed = [], runs = []) {
  if (sample.status === 'ARCHIVED') return 'archived';
  if (sample.status === 'CANCELLED') return 'cancelled';
  const active = runs.filter(run => ['ACTIVE', 'BLOCKED'].includes(run.status));
  const steps = active.flatMap(run => run.steps || []);
  if (steps.some(step => step.status === 'FAILED')) return 'failed';
  if (steps.some(step => step.status === 'AWAITING_QC')) return 'review';
  if (steps.some(step => step.status === 'IN_PROGRESS')) return 'continue';
  if (steps.some(step => step.status === 'READY')) return 'ready';
  if (active.length) return 'blocked';
  if (sample.status === 'QC') return 'review';
  if (sample.status === 'REPORTED') return 'reported';
  if (sample.status === 'RECEIVED') return 'received';
  if (sample.status === 'IN_PROGRESS') return 'working';
  return allowed.length ? 'custom' : 'noTransition';
}
