const { test, expect } = require('@playwright/test');
const experimentId = 'b80955b7-2b44-4e83-bf10-e6c7f5bb0760';
const firstRevision = 'b80955b7-2b44-4e83-bf10-e6c7f5bb0001';
const draftKey = `openlims:notebook-draft:v1:1:${experimentId}`;

async function setup(page, options = {}) {
  const state = { user: { id: 1, username: 'technician', roles: ['tech'], is_active: true }, text: 'Saved protein protocol.',
    revision: firstRevision, number: 1, failSave: false, locked: false, denied: false, saves: [], active: 0, maxActive: 0, sampleRequests: [], language: 'en', ...options };
  page.on('dialog', dialog => dialog.accept());
  await page.context().addCookies([{ name: 'csrftoken', value: 'draft-csrf', url: 'http://127.0.0.1:5173' }]);
  const experiment = () => {
    const revision = { id: state.number, public_id: state.revision, number: state.number, blocks: [{ block_type: 'RICH_TEXT', data: { text: state.text } }], links: [], checksum: 'a'.repeat(64), change_summary: 'Protocol update' };
    return { id: 11, public_id: experimentId, notebook: 1, title: 'Protein recovery experiment', status: state.locked ? 'LOCKED' : 'IN_PROGRESS',
      created_by: state.user.id, assignees: [], comments: [], reviews: [], workflow_steps: [], permissions: { read: true, write: !state.locked }, revisions: [revision], current_revision_detail: revision };
  };
  const sample = id => ({ id, sample_id: `BIO-${String(id).padStart(3, '0')}`, sample_type: 'PROTEIN', status: 'RECEIVED', project: 1, project_code: 'ALPHA',
    linked_projects: [], linked_project_summaries: [], can_modify: false, allowed_transitions: [], created_at: '2026-11-11T10:00:00Z' });
  await page.route('**/api/**', async route => {
    const request = route.request(), url = new URL(request.url()), path = url.pathname.replace('/api/v1/', '/api/');
    let body = [], status = 200;
    if (path === '/api/session/') body = { user: state.user, feature_flags: { notebook: true } };
    else if (path === '/api/me/') body = state.user;
    else if (path === '/api/ui-settings/') body = { ui_language: state.language, assistant_helper_enabled: false };
    else if (path === '/api/feature-flags/') body = { notebook: true };
    else if (path === '/api/notebooks/') body = [{ id: 1, name: 'Protein notebook', permissions: { read: true, write: true } }];
    else if (path === '/api/experiments/') body = [experiment()];
    else if (path === '/api/experiments/11/') { if (state.denied) { status = 403; body = { detail: 'Access revoked' }; } else body = experiment(); }
    else if (path === '/api/experiments/11/autosave/') {
      const payload = request.postDataJSON(); state.saves.push(payload); state.active++; state.maxActive = Math.max(state.maxActive, state.active);
      if (state.waitForSave) await state.waitForSave;
      if (state.failSave) { status = 503; body = { detail: 'Disconnected' }; }
      else if (payload.expected_revision_public_id !== state.revision) { status = 400; body = { revision: ['A newer revision exists.'] }; }
      else {
        state.number++; state.revision = `b80955b7-2b44-4e83-bf10-e6c7f5bb${String(state.number).padStart(4, '0')}`;
        state.text = payload.blocks[0]?.data?.text || '';
        body = { revision: experiment().current_revision_detail, created: true, experiment_status: 'IN_PROGRESS' };
      }
      state.active--;
    } else if (path === '/api/projects/') body = [{ id: 1, code: 'ALPHA', name: 'Protein project' }];
    else if (path === '/api/sample-forms/' && state.failForms) { status = 403; body = { detail: 'Optional forms unavailable' }; }
    else if (path === '/api/samples/') {
      state.sampleRequests.push(Object.fromEntries(url.searchParams));
      let rows = Array.from({ length: 35 }, (_, index) => sample(index + 1));
      const query = url.searchParams.get('search');
      if (query) rows = rows.filter(row => row.sample_id.toLowerCase().includes(query.toLowerCase()));
      const ordering = url.searchParams.get('ordering');
      if (ordering === '-sample_id') rows.reverse();
      const size = Number(url.searchParams.get('page_size') || 10), pageNumber = Number(url.searchParams.get('page') || 1), count = rows.length;
      if (pageNumber > Math.max(1, Math.ceil(count / size))) { status = 404; body = { detail: 'Invalid page' }; }
      else body = { count, results: rows.slice((pageNumber - 1) * size, pageNumber * size), previous: pageNumber > 1 ? 'previous' : null, next: pageNumber * size < count ? 'next' : null };
    } else if (/^\/api\/samples\/\d+\/$/.test(path)) body = sample(Number(path.split('/')[3]));
    else if (/^\/api\/samples\/\d+\/(history|experiments)\/$/.test(path)) body = { count: 0, results: [] };
    else if (path === '/api/inventory-items/') body = [{ id: 1, code: 'PROTEIN', name: 'Protein reagent', available_quantity: 100, default_unit: 'mL', reorder_level: 10 }];
    else if (path === '/api/inventory-lots/') body = Array.from({ length: 35 }, (_, index) => ({ id: index + 1, lot_code: `LOT-${String(index + 1).padStart(3, '0')}`, item_code: 'PROTEIN', available_quantity: index + 1, unit: 'mL', status: 'ACTIVE' }));
    else if (path === '/api/work-items/') body = Array.from({ length: 35 }, (_, index) => ({ id: index + 1, name: `Work ${index + 1}`, sample_code: `BIO-${index + 1}`, work_type: index % 2 ? 'SEQUENCING' : 'PCR', status: 'PENDING', can_update: index % 2 === 0 }));
    await route.fulfill({ status, json: body });
  });
  return state;
}
const editor = page => page.locator('.notebook-block textarea').first();
async function seedDraft(page, text = 'Recovered protein observations.', baseRevision = firstRevision, userId = 1) {
  await page.evaluate(({ key, text, baseRevision }) => sessionStorage.setItem(key, JSON.stringify({ version: 1, savedAt: Date.now(), baseRevision, blocks: [{ block_type: 'RICH_TEXT', data: { text } }], links: [] })), { key: `openlims:notebook-draft:v1:${userId}:${experimentId}`, text, baseRevision });
}

test('failed notebook saves survive refresh, restore only after review, and clear after confirmed save', async ({ page }) => {
  const state = await setup(page, { failSave: true });
  await page.goto('/notebook');
  await editor(page).fill('Protein concentration is 12 μg/mL.');
  await expect(page.getByRole('button', { name: 'Retry saving edits', exact: true })).toBeVisible();
  expect(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).blocks[0].data.text, draftKey)).toBe('Protein concentration is 12 μg/mL.');
  await page.reload();
  await expect(page.getByText('A recovery copy is available for this experiment.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Review recovered draft', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.locator('.change-comparison').first()).toContainText('Saved protein protocol.');
  await expect(dialog.locator('.change-comparison').first()).toContainText('12 μg/mL');
  const beforeRestore = state.saves.length;
  await dialog.getByRole('button', { name: 'Restore draft for editing', exact: true }).click();
  await expect(editor(page)).toHaveValue('Protein concentration is 12 μg/mL.');
  expect(state.saves.length).toBe(beforeRestore);
  state.failSave = false;
  await page.getByRole('button', { name: 'Save now', exact: true }).click();
  await expect(page.getByText('Saved as r2', { exact: true })).toBeVisible();
  expect(await page.evaluate(key => sessionStorage.getItem(key), draftKey)).toBeNull();
  await page.reload();
  await expect(editor(page)).toHaveValue('Protein concentration is 12 μg/mL.');
  await expect(page.getByRole('button', { name: 'Review recovered draft', exact: true })).toHaveCount(0);
});

test('stale recovery requires acknowledgement and never silently overwrites a collaborator', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/notebook'); await expect(editor(page)).toBeVisible();
  await seedDraft(page);
  state.text = 'A colleague updated the protocol.'; state.revision = 'b80955b7-2b44-4e83-bf10-e6c7f5bb0099'; state.number = 99;
  await page.reload();
  await expect(page.getByText('The saved experiment changed after this copy was made. Review both versions before restoring.', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Review recovered draft', exact: true }).click();
  const dialog = page.getByRole('dialog'), restore = dialog.getByRole('button', { name: 'Restore draft for editing', exact: true });
  await expect(restore).toBeDisabled();
  await expect(dialog).toContainText('A colleague updated the protocol.');
  expect(state.saves).toHaveLength(0);
  await dialog.getByRole('checkbox').check(); await restore.click();
  await page.getByRole('button', { name: 'Save now', exact: true }).click();
  await expect.poll(() => state.saves.length).toBe(1);
  expect(state.saves[0].expected_revision_public_id).toBe('b80955b7-2b44-4e83-bf10-e6c7f5bb0099');
});

test('navigation warns before leaving unsaved edits and offers recovery on return', async ({ page }) => {
  await setup(page, { failSave: true });
  await page.goto('/notebook'); await editor(page).fill('Pending observations.');
  await page.getByText('My profile', { exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('Leave with unsaved changes?', { exact: true })).toBeVisible();
  await dialog.getByRole('button', { name: 'Stay on this page', exact: true }).click();
  await expect(editor(page)).toHaveValue('Pending observations.');
  await page.getByText('My profile', { exact: true }).click();
  await page.getByRole('button', { name: 'Leave page', exact: true }).click();
  await expect(page).toHaveURL(/\/me$/);
  await expect(page.getByRole('heading', { name: 'My profile', exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole('button', { name: 'Review recovered draft', exact: true })).toBeVisible();
});

test('recovery copies remain account-specific and are not shown after source access is revoked', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/notebook'); await expect(editor(page)).toBeVisible(); await seedDraft(page, 'Private draft content.');
  state.user = { id: 2, username: 'another-user', roles: ['tech'], is_active: true };
  await page.reload();
  await expect(editor(page)).toHaveValue('Saved protein protocol.');
  await expect(page.getByRole('button', { name: 'Review recovered draft', exact: true })).toHaveCount(0);
  state.user.id = 1; state.denied = true;
  await page.reload();
  await expect(page.getByText('No experiment selected', { exact: true })).toBeVisible();
  await expect(page.getByText('Private draft content.', { exact: true })).toHaveCount(0);
});

test('a locked experiment offers draft review and download without allowing restore or save', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/notebook'); await expect(editor(page)).toBeVisible(); await seedDraft(page); state.locked = true;
  await page.reload(); await page.getByRole('button', { name: 'Review recovered draft', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('button', { name: 'Restore draft for editing', exact: true })).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: 'Download recovery copy', exact: true })).toBeVisible();
  expect(state.saves).toHaveLength(0);
});

test('slow autosaves serialize newer edits and retain the latest recovery copy until saved', async ({ page }) => {
  const state = await setup(page);
  let release; state.waitForSave = new Promise(resolve => { release = resolve; });
  await page.goto('/notebook'); await editor(page).fill('First observations.');
  await expect.poll(() => state.saves.length).toBe(1);
  await editor(page).fill('Newer observations while saving.');
  await page.getByRole('button', { name: 'Save now', exact: true }).click();
  expect(await page.evaluate(key => JSON.parse(sessionStorage.getItem(key)).blocks[0].data.text, draftKey)).toBe('Newer observations while saving.');
  release();
  await expect(page.getByText('Saved as r3', { exact: true })).toBeVisible();
  expect(state.maxActive).toBe(1);
  expect(state.text).toBe('Newer observations while saving.');
  expect(state.saves[1].expected_revision_public_id).toBe('b80955b7-2b44-4e83-bf10-e6c7f5bb0002');
  expect(await page.evaluate(key => sessionStorage.getItem(key), draftKey)).toBeNull();
});

test('blocked recovery storage shows a truthful warning and keeps editing usable', async ({ page }) => {
  await setup(page, { failSave: true });
  await page.addInitScript(() => { const original = Storage.prototype.setItem; Storage.prototype.setItem = function (key, value) { if (key.startsWith('openlims:notebook-draft:')) throw new Error('Storage disabled'); return original.call(this, key, value); }; });
  await page.goto('/notebook'); await editor(page).fill('Open edits remain usable.');
  await expect(page.getByText('Browser recovery storage is unavailable or full. Keep this page open until your edits are saved to the server.', { exact: true })).toBeVisible();
  await expect(editor(page)).toHaveValue('Open edits remain usable.');
});

test('sample filters, sort, columns and page return after opening a record', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/samples'); await expect(page.getByRole('link', { name: 'BIO-001', exact: true })).toBeVisible();
  await page.getByPlaceholder('Search by sample ID', { exact: true }).fill('BIO');
  await page.getByLabel('Sort by', { exact: true }).selectOption('-sample_id');
  await page.getByLabel('Rows per page', { exact: true }).selectOption('10');
  await page.getByText('Visible columns', { exact: true }).click();
  await page.getByRole('checkbox', { name: 'Created By', exact: true }).uncheck();
  await page.getByRole('button', { name: 'Next sample page', exact: true }).click();
  await expect(page.getByRole('link', { name: 'BIO-025', exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'BIO-025', exact: true }).scrollIntoViewIfNeeded();
  const scrollPosition = await page.evaluate(() => window.scrollY);
  await page.getByRole('link', { name: 'BIO-025', exact: true }).click();
  await expect(page).toHaveURL(/\/samples\/25$/);
  await page.goBack();
  await expect(page.getByRole('link', { name: 'BIO-025', exact: true })).toBeVisible();
  await expect(page.getByPlaceholder('Search by sample ID', { exact: true })).toHaveValue('BIO');
  await expect(page.getByLabel('Sort by', { exact: true })).toHaveValue('-sample_id');
  await expect(page.getByRole('columnheader', { name: 'Created By', exact: true })).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThanOrEqual(scrollPosition - 30);
  expect(state.sampleRequests.at(-1)).toMatchObject({ search: 'BIO', page: '2', ordering: '-sample_id' });
});

test('table views do not leak to another account and reset restores defaults', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/samples'); await expect(page.getByRole('link', { name: 'BIO-001', exact: true })).toBeVisible();
  await page.getByPlaceholder('Search by sample ID', { exact: true }).fill('BIO-002');
  await expect(page.getByRole('link', { name: 'BIO-002', exact: true })).toBeVisible();
  state.user = { id: 2, username: 'second-technician', roles: ['tech'], is_active: true };
  await page.reload();
  await expect(page.getByRole('link', { name: 'BIO-001', exact: true })).toBeVisible();
  await expect(page.getByPlaceholder('Search by sample ID', { exact: true })).toHaveValue('');
  state.user.id = 1; await page.reload();
  await expect(page.getByPlaceholder('Search by sample ID', { exact: true })).toHaveValue('BIO-002');
  await page.getByRole('button', { name: 'Reset table view', exact: true }).click();
  await expect(page.getByPlaceholder('Search by sample ID', { exact: true })).toHaveValue('');
  await expect(page.getByRole('link', { name: 'BIO-001', exact: true })).toBeVisible();
});

test('inventory lot views remember query, numeric sorting, hidden columns and page across reloads', async ({ page }) => {
  await setup(page); await page.goto('/inventory');
  const table = page.getByRole('region', { name: 'Lots', exact: true });
  await expect(table.getByRole('cell', { name: 'LOT-001', exact: true })).toBeVisible();
  await table.getByLabel('Search this table', { exact: true }).fill('LOT');
  await table.getByLabel('Sort by', { exact: true }).selectOption('-available');
  await table.getByText('Visible columns', { exact: true }).click();
  await table.getByRole('checkbox', { name: 'Container', exact: true }).uncheck();
  await table.getByRole('button', { name: 'Next page', exact: true }).click();
  await expect(table.getByRole('cell', { name: 'LOT-025', exact: true })).toBeVisible();
  await page.reload();
  await expect(table.getByRole('cell', { name: 'LOT-025', exact: true })).toBeVisible();
  await expect(table.getByLabel('Search this table', { exact: true })).toHaveValue('LOT');
  await expect(table.getByLabel('Sort by', { exact: true })).toHaveValue('-available');
  await expect(table.getByRole('columnheader', { name: 'Container', exact: true })).toHaveCount(0);
});

test('work queue filter choices and table presentation survive reloads', async ({ page }) => {
  await setup(page); await page.goto('/work-queue');
  const table = page.getByRole('region', { name: 'Active and recent work', exact: true });
  await table.getByLabel('Work type', { exact: true }).selectOption('SEQUENCING');
  await table.getByLabel('Work status', { exact: true }).selectOption('PENDING');
  await table.getByLabel('Rows per page', { exact: true }).selectOption('25');
  await page.reload();
  await expect(table.getByLabel('Work type', { exact: true })).toHaveValue('SEQUENCING');
  await expect(table.getByLabel('Work status', { exact: true })).toHaveValue('PENDING');
  await expect(table.getByLabel('Rows per page', { exact: true })).toHaveValue('25');
  await expect(table.getByRole('cell', { name: 'PCR', exact: true })).toHaveCount(0);
  await expect(table.getByRole('cell', { name: 'Read-only', exact: true })).toHaveCount(17);
  await expect(table.getByRole('combobox', { name: /^Update work / })).toHaveCount(0);
});

test('explicit project links override another remembered project and preserve page when returning', async ({ page }) => {
  const state = await setup(page);
  await page.addInitScript(() => localStorage.setItem('openlims:table:v1:1:samples', JSON.stringify({ query: 'BIO', sort: 'sample_id', page: 999, pageSize: 10, columns: ['status'], filters: { status: '', project: '2', container: '' } })));
  await page.goto('/samples?project=1');
  await expect(page.getByRole('link', { name: 'BIO-001', exact: true })).toBeVisible();
  expect(state.sampleRequests.at(-1).project).toBe('1');
  await page.getByRole('button', { name: 'Next sample page', exact: true }).click();
  await page.getByRole('link', { name: 'BIO-011', exact: true }).click();
  await expect(page).toHaveURL(/\/samples\/11$/); await page.goBack();
  await expect(page.getByRole('link', { name: 'BIO-011', exact: true })).toBeVisible();
  expect(state.sampleRequests.at(-1)).toMatchObject({ project: '1', page: '2' });
});

test('a server revision conflict preserves edits and offers recovery against the latest version', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/notebook'); await expect(editor(page)).toBeVisible();
  state.text = 'Colleague saved this text.'; state.revision = 'b80955b7-2b44-4e83-bf10-e6c7f5bb0099'; state.number = 99;
  await editor(page).fill('My pending edit.');
  await expect(page.getByText('The saved experiment changed. Review the latest saved version before restoring your edits.', { exact: true })).toBeVisible();
  expect(state.text).toBe('Colleague saved this text.');
  await expect(editor(page)).toHaveValue('My pending edit.');
  await page.getByRole('button', { name: 'Review latest saved version', exact: true }).click();
  await page.getByRole('button', { name: 'Review recovered draft', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Colleague saved this text.');
  await expect(page.getByRole('dialog')).toContainText('My pending edit.');
  await expect(page.getByRole('button', { name: 'Restore draft for editing', exact: true })).toBeDisabled();
});

test('recovery and personal table controls are available in Spanish', async ({ page }) => {
  await setup(page, { language: 'es' });
  await page.goto('/notebook'); await expect(editor(page)).toBeVisible(); await seedDraft(page); await page.reload();
  await expect(page.getByRole('button', { name: 'Revisar borrador recuperado', exact: true })).toBeVisible();
  await page.goto('/samples');
  await expect(page.getByLabel('Ordenar por', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Restablecer vista de tabla', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'BIO-001', exact: true })).toBeVisible();
});

test('unavailable optional registration lists do not hide authorized samples or remembered views', async ({ page }) => {
  await setup(page, { failForms: true });
  await page.goto('/samples');
  await expect(page.getByRole('link', { name: 'BIO-001', exact: true })).toBeVisible();
  await expect(page.getByText('Some filters or registration options could not load. Refresh this page to retry.', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Sort by', { exact: true })).toBeVisible();
});
