const { test, expect } = require('@playwright/test');

const actionId = 'b14cfe45-62c8-4d40-8135-87e93daa2012';
const experimentId = 'ecc506b2-b888-45b5-8dd6-d33be3df2012';
const beforeId = '12180b02-37ab-42bc-b080-34fb46cc2012';
const afterId = '9c0d35f1-828c-489b-b76c-bcc8580c2012';
const user = { id: 1, username: 'director', roles: ['admin'], is_active: true, is_superuser: true };
const comparison = {
  before: { public_id: beforeId, number: 1, checksum: 'a'.repeat(64) }, after: { public_id: afterId, number: 2, checksum: 'b'.repeat(64) },
  summary: { blocks_added: 0, blocks_removed: 0, blocks_modified: 1, links_added: 0, links_removed: 0, links_modified: 0 },
  block_changes: [{ position: 0, change: 'modified', before: { block_type: 'RICH_TEXT', data: { text: 'Store protein at 4 °C.' } },
    after: { block_type: 'RICH_TEXT', data: { text: 'Store protein at -20 °C.' } } }], link_changes: [],
};
const storageEvent = { id: 1, entity_type: 'Container', entity_id: '13', entity_label: 'Protein box', action: 'CONTAINER_UPDATED', action_label: 'Container updated',
  actor_username: 'director', timestamp: new Date().toISOString(), payload: { before: { location: 1 }, after: { location: 2 } },
  field_changes: [{ field: 'location', label: 'Location', before: 'Freezer A', after: 'Freezer B', before_present: true, after_present: true }] };
const revisionEvent = { id: 2, entity_type: 'experiment', entity_id: experimentId, entity_label: 'Protein storage study',
  action: 'EXPERIMENT_REVISION_CREATED', action_label: 'Experiment saved', actor_username: 'director', timestamp: new Date().toISOString(),
  payload: { before: { revision: 1 }, after: { revision: 2 } }, can_compare_revision: true, field_changes: [] };

function health(overrides = {}) {
  return { accessible: true, stalled: true, current_step: 'Importing rows', last_completed_step: '25 of 100 rows processed',
    last_progress_at: new Date(Date.now() - 1900000).toISOString(), progress_current: 25, progress_total: 100,
    recovery_hint: 'Refresh the status before starting another attempt; the original job may still be running.',
    recovery: [{ label: 'Review task in assistant', url: `/assistant?job_action=${actionId}` }, { label: 'Review job', url: '/blast?job=99' }], ...overrides };
}

async function setup(page, options = {}) {
  const state = { language: 'en', events: [storageEvent, revisionEvent], comparison, status: 'QUEUED', health: health(), healthRequests: 0,
    mutations: [], nativeRequests: [], optionalFailure: false, ...options };
  await page.context().addCookies([{ name: 'csrftoken', value: 'comparison-csrf', url: 'http://127.0.0.1:5173' }]);
  const old = { id: 1, public_id: beforeId, number: 1, checksum: 'a'.repeat(64), blocks: comparison.block_changes[0].before ? [comparison.block_changes[0].before] : [], links: [], change_summary: 'Initial protocol' };
  const next = { ...old, id: 2, public_id: afterId, number: 2, checksum: 'b'.repeat(64), blocks: [comparison.block_changes[0].after], change_summary: 'Updated storage temperature' };
  const experiment = { id: 11, public_id: experimentId, notebook: 1, notebook_name: 'Protein notebook', title: 'Protein storage study', status: 'IN_PROGRESS',
    assignees: [], comments: [], reviews: [], workflow_steps: [], permissions: { read: true, write: true }, revisions: [next, old], current_revision_detail: next };
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.replace('/api/v1/', '/api/');
    let body = [], status = 200;
    if (request.method() !== 'GET') state.mutations.push({ method: request.method(), path });
    if (path === '/api/session/') body = { user, feature_flags: {} };
    else if (path === '/api/me/') body = user;
    else if (path === '/api/ui-settings/') body = { ui_language: state.language, assistant_helper_enabled: false };
    else if (path === '/api/feature-flags/') body = {};
    else if (path === '/api/events/') body = { count: state.events.length, results: state.events };
    else if (path === '/api/events/summary/') body = { total_events: state.events.length, entity_types: ['Container', 'experiment'], actions: ['CONTAINER_UPDATED', 'EXPERIMENT_REVISION_CREATED'] };
    else if (path === '/api/events/2/comparison/') {
      if (state.comparisonFailure) { status = 404; body = { detail: 'Private comparison unavailable' }; }
      else body = { field_changes: [], revision_comparison: state.comparison };
    } else if (path === `/api/assistant/jobs/${actionId}/`) {
      state.healthRequests++;
      if (state.healthFailure) { status = 404; body = { detail: 'Not available' }; }
      else body = { id: actionId, type: 'QUEUE_IMPORT', summary: 'Import protein sequencer results', status: state.status, health: state.health, result: {}, preview: {} };
    } else if (path === '/api/notifications/') body = { count: 1, results: [{ id: 1, title: 'Assistant task needs attention', message: 'Import is waiting for progress.',
      is_read: false, created_at: new Date().toISOString(), link: `/assistant?job_action=${actionId}`,
      assistant_alert: { action_id: actionId, kind: 'STALLED', status: state.status, resolved_at: state.resolved ? new Date().toISOString() : null, snapshot: state.health } }] };
    else if (state.optionalFailure && ['/api/inventory-items/', '/api/samples/', '/api/results/', '/api/notification-subscriptions/'].includes(path)) { status = 403; body = {}; }
    else if (path === '/api/notebooks/') body = [{ id: 1, name: 'Protein notebook', scope: 'USER', permissions: { read: true, write: true } }];
    else if (path === '/api/experiments/') body = [experiment];
    else if (path === '/api/experiments/11/') body = experiment;
    else if (path === '/api/experiments/11/compare/') body = state.comparison;
    else if (path === '/api/blast-jobs/') body = { count: 1, results: [{ id: 42, name: 'Different newer job', status: 'PENDING', program: 'blastn', hits_count: 0 }] };
    else if (path === '/api/blast-jobs/99/') {
      state.nativeRequests.push(99);
      body = { id: 99, name: 'Older protein BLAST', status: 'FAILED', program: 'blastn', hits_count: 0, hits: [],
        query_sequence_name: 'Protein query', database_name: 'Reference database', error_message: 'Correct the query input before preparing another attempt.' };
    }
    await route.fulfill({ status, json: body });
  });
  return state;
}

test('audit field comparison shows stored location names and distinct before/after values', async ({ page }) => {
  await setup(page);
  await page.goto('/events');
  const row = page.getByRole('row').filter({ hasText: 'Protein box' });
  await row.getByText('Compare changes (1)', { exact: true }).click();
  await expect(row.locator('del')).toHaveText('A');
  await expect(row.locator('ins')).toHaveText('B');
  await expect(row.locator('.change-comparison')).toContainText('Freezer A');
  await expect(row.locator('.change-comparison')).toContainText('Freezer B');
});

test('audit revisions open highlighted notebook text without modifying data', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/events');
  await page.getByRole('button', { name: 'Compare revision text', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.locator('del')).toHaveText('4');
  await expect(dialog.locator('ins')).toHaveText('-20');
  await expect(dialog.locator('.change-comparison')).toContainText('Store protein at');
  await expect(dialog.getByText('Deleted text is struck through. Added text is underlined.', { exact: true })).toBeVisible();
  expect(state.mutations).toHaveLength(0);
});

test('notebook History uses the same highlighted comparison instead of raw JSON', async ({ page }) => {
  await setup(page);
  await page.goto('/notebook');
  await expect(page.getByRole('heading', { name: 'Protein storage study', exact: true })).toBeVisible();
  await page.getByRole('tab', { name: /^History / }).click();
  await page.getByRole('button', { name: 'Compare', exact: true }).click();
  await expect(page.locator('.notebook-comparison del')).toHaveText('4');
  await expect(page.locator('.notebook-comparison ins')).toHaveText('-20');
});

test('comparison markup stays text and cannot inject HTML or scripts', async ({ page }) => {
  const malicious = structuredClone(comparison);
  malicious.block_changes[0].after.data.text = '<img class="attack" src=x onerror="window.attacked=true">';
  await setup(page, { comparison: malicious });
  await page.goto('/events');
  await page.getByRole('button', { name: 'Compare revision text', exact: true }).click();
  await expect(page.getByRole('dialog').locator('.change-comparison')).toContainText('<img class="attack"');
  await expect(page.locator('img.attack')).toHaveCount(0);
  expect(await page.evaluate(() => window.attacked)).toBeUndefined();
});

test('unavailable or revoked revision access shows a useful error without old content', async ({ page }) => {
  await setup(page, { comparisonFailure: true });
  await page.goto('/events');
  await page.getByRole('button', { name: 'Compare revision text', exact: true }).click();
  await expect(page.getByRole('dialog').getByRole('alert')).toContainText('The comparison is unavailable.');
  await expect(page.getByRole('dialog').locator('del')).toHaveCount(0);
});

test('stalled task opens directly in the assistant with its checkpoint and safe recovery options', async ({ page }) => {
  const state = await setup(page);
  await page.goto(`/assistant?job_action=${actionId}`);
  const progress = page.getByRole('alert', { name: 'Assistant task progress' });
  await expect(progress.getByText('25 of 100 rows processed', { exact: true })).toBeVisible();
  await expect(progress).toContainText('the original job may still be running');
  await expect(progress.getByRole('link', { name: 'Review job', exact: true })).toHaveAttribute('href', '/blast?job=99');
  expect(state.mutations).toHaveLength(0);
});

test('failed task shows the actual last checkpoint, error and recovery guidance', async ({ page }) => {
  await setup(page, { status: 'FAILED', health: health({ stalled: false, current_step: 'Failed', failure_reason: 'CSV mapping changed after confirmation.',
    recovery_hint: 'Review the import receipt and source mapping. Repair rejected rows without resubmitting rows already imported.' }) });
  await page.goto(`/assistant?job_action=${actionId}`);
  const progress = page.getByRole('alert', { name: 'Assistant task progress' });
  await expect(progress).toContainText('CSV mapping changed after confirmation.');
  await expect(progress).toContainText('25 of 100 rows processed');
  await expect(progress).toContainText('without resubmitting rows already imported');
  await expect(progress.getByRole('button', { name: /Confirm|Retry job/ })).toHaveCount(0);
});

test('refreshing task status recovers completion without automatically rerunning the job', async ({ page }) => {
  const state = await setup(page);
  await page.goto(`/assistant?job_action=${actionId}`);
  const progress = page.getByRole('alert', { name: 'Assistant task progress' });
  await expect(progress).toContainText('25 of 100 rows processed');
  state.status = 'COMPLETED'; state.health = health({ stalled: false, current_step: 'Completed', last_completed_step: 'Results saved' });
  await progress.getByRole('button', { name: 'Refresh task status', exact: true }).click();
  await expect(progress).toContainText('Results saved');
  await expect(progress.getByText('Assistant task completed', { exact: true })).toBeVisible();
  expect(state.mutations).toHaveLength(0);
});

test('job notifications remain visible when optional subscription modules cannot load, without per-notification polling', async ({ page }) => {
  const state = await setup(page, { optionalFailure: true });
  await page.clock.install();
  await page.goto('/notifications');
  await expect(page.getByText('Import is waiting for progress.', { exact: true })).toBeVisible();
  await expect(page.getByText('25 of 100 rows processed', { exact: true })).toBeVisible();
  expect(state.healthRequests).toBe(0);
  state.health.last_completed_step = '35 of 100 rows processed';
  await page.getByRole('button', { name: 'Refresh task status', exact: true }).click();
  await expect.poll(() => state.healthRequests).toBe(1);
  await expect(page.getByText('35 of 100 rows processed', { exact: true })).toBeVisible();
  await page.clock.fastForward(30_000);
  expect(state.healthRequests).toBe(1);
});

test('resolved notifications are marked as history and do not start polling again', async ({ page }) => {
  const state = await setup(page, { resolved: true, status: 'COMPLETED' });
  await page.goto('/notifications');
  await expect(page.getByText('Alert resolved', { exact: true })).toBeVisible();
  expect(state.healthRequests).toBe(0);
  await expect(page.getByRole('button', { name: 'Refresh task status', exact: true })).toHaveCount(0);
});

test('task status refresh handles revoked access without starting a new action', async ({ page }) => {
  const state = await setup(page, { healthFailure: true });
  await page.goto(`/assistant?job_action=${actionId}`);
  await expect(page.getByRole('status').filter({ hasText: 'Could not refresh this task.' })).toBeVisible();
  expect(state.mutations).toHaveLength(0);
});

test('job recovery links open the exact older job even outside the current list page', async ({ page }) => {
  const state = await setup(page);
  await page.goto(`/assistant?job_action=${actionId}`);
  await page.getByRole('link', { name: 'Review job', exact: true }).click();
  await expect(page.getByText('Older protein BLAST · FAILED', { exact: true })).toBeVisible();
  expect(state.nativeRequests).toContain(99);
  expect(state.mutations).toHaveLength(0);
});

test('comparison controls and job progress headings are translated into Spanish', async ({ page }) => {
  await setup(page, { language: 'es' });
  await page.goto('/events');
  await page.getByRole('button', { name: 'Comparar texto de revisiones', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('columnheader', { name: 'Antes', exact: true })).toBeVisible();
  await expect(dialog.getByRole('columnheader', { name: 'Después', exact: true })).toBeVisible();
  await page.goto(`/assistant?job_action=${actionId}`);
  await expect(page.getByRole('button', { name: 'Actualizar estado de la tarea', exact: true })).toBeVisible();
  await expect(page.getByText('Último paso completado:', { exact: true })).toBeVisible();
});
