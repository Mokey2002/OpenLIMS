const { test, expect } = require('@playwright/test');

const uuid = '3c834c15-53d3-4e65-8ffe-67314e7d28e0';
const experiment = { id: 30, entity_type: 'experiment', entity_id: uuid, action: 'EXPERIMENT_REVISION_CREATED', actor: 1, actor_username: 'director',
  timestamp: '2026-11-06T04:34:11Z', payload: { entity: { type: 'experiment', public_id: uuid, label: 'Protein stability study' },
    before: { revision: 3 }, after: { revision: 4 }, details: { changes: { blocks_modified: 1 } }, reason: 'Notebook autosave' } };
const inventory = { id: 31, entity_type: 'Container', entity_id: '13', action: 'CONTAINER_CREATED', actor_username: 'director',
  timestamp: '2026-11-07T08:55:23Z', payload: { container_id: 'Protein box A' } };

async function setup(page, options = {}) {
  const state = { events: [inventory, experiment], queries: [], language: 'en', ...options };
  const user = { id: 1, username: 'director', roles: ['admin'] };
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace('/api/v1/', '/api/');
    if (state.intercept && await state.intercept(route, path, url)) return;
    let body = [];
    if (path === '/api/session/') body = { user, feature_flags: {} };
    else if (path === '/api/me/') body = user;
    else if (path === '/api/ui-settings/') body = { ui_language: state.language, assistant_helper_enabled: false };
    else if (path === '/api/feature-flags/') body = {};
    else if (path === '/api/events/') {
      state.queries.push(Object.fromEntries(url.searchParams));
      body = { count: state.events.length, results: state.events };
    } else if (path === '/api/events/summary/') body = { total_events: state.events.length, entity_types: ['experiment', 'Container'], actions: ['EXPERIMENT_REVISION_CREATED', 'CONTAINER_CREATED'] };
    await route.fulfill({ json: body });
  });
  return state;
}

test('dashboard activity shows the action, experiment title and revision instead of opaque IDs', async ({ page }) => {
  await setup(page);
  await page.goto('/dashboard');
  const row = page.getByRole('row').filter({ hasText: 'Protein stability study' });
  await expect(row.getByText('Experiment saved', { exact: true })).toBeVisible();
  await expect(row).toContainText('Revision 3 → 4; 1 block modified');
  await expect(page.getByText(`experiment #${uuid}`, { exact: true })).toHaveCount(0);
  await expect(page.getByRole('row').filter({ hasText: 'Protein box A' })).toContainText('Container created');
});

test('audit log keeps raw IDs and codes available under collapsed technical details', async ({ page }) => {
  await setup(page);
  await page.goto('/events');
  const row = page.getByRole('row').filter({ hasText: 'Protein stability study' });
  await expect(row.getByText('Experiment saved', { exact: true })).toBeVisible();
  await expect(row).toContainText('Revision 3 → 4; 1 block modified');
  const rawId = row.getByText(`experiment #${uuid}`, { exact: true });
  await expect(rawId).toBeHidden();
  await row.getByText('Technical details', { exact: true }).click();
  await expect(rawId).toBeVisible();
  await expect(row.getByText('EXPERIMENT_REVISION_CREATED', { exact: true })).toBeVisible();
});

test('clear filters refreshes the actual list and action choices have readable labels', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/events');
  await expect(page.getByRole('row').filter({ hasText: 'Protein stability study' })).toBeVisible();
  await page.getByLabel('Action', { exact: true }).selectOption('EXPERIMENT_REVISION_CREATED');
  await expect(page.getByLabel('Action', { exact: true }).locator('option:checked')).toHaveText('Experiment saved');
  await page.getByLabel('Search', { exact: true }).fill('Protein');
  await page.getByRole('button', { name: 'Apply Filters', exact: true }).click();
  await expect.poll(() => state.queries.at(-1)?.search).toBe('Protein');
  await page.getByRole('button', { name: 'Clear', exact: true }).click();
  await expect.poll(() => state.queries.at(-1)?.search).toBeUndefined();
  await expect(page.getByLabel('Search', { exact: true })).toHaveValue('');
});

test('an older audit response cannot overwrite the latest filtered results', async ({ page }) => {
  let release, started = false;
  const gate = new Promise(resolve => { release = resolve; });
  await setup(page, {
    events: [{ ...experiment, payload: { ...experiment.payload, entity: { label: 'Latest protein study' } } }],
    intercept: async (route, path, url) => {
      if (path === '/api/events/' && !url.searchParams.get('search') && !started) {
        started = true;
        await gate;
        await route.fulfill({ json: { results: [{ ...inventory, payload: { container_id: 'Outdated box' } }] } }).catch(() => {});
        return true;
      }
      return false;
    },
  });
  try {
    await page.goto('/events');
    await expect.poll(() => started).toBe(true);
    await page.getByLabel('Search', { exact: true }).fill('Latest');
    await page.getByRole('button', { name: 'Apply Filters', exact: true }).click();
    await expect(page.getByRole('row').filter({ hasText: 'Latest protein study' })).toBeVisible();
  } finally { release(); }
  await expect(page.getByRole('row').filter({ hasText: 'Outdated box' })).toHaveCount(0);
});

test('revision explanations and action labels are readable in Spanish', async ({ page }) => {
  await setup(page, { language: 'es' });
  await page.goto('/events');
  const row = page.getByRole('row').filter({ hasText: 'Protein stability study' });
  await expect(row.getByText('Experimento guardado', { exact: true })).toBeVisible();
  await expect(row).toContainText('Revisión 3 → 4; 1 bloque modificado');
  await expect(row.getByText('Detalles técnicos', { exact: true })).toBeVisible();
});

for (const lostResponse of [false, true]) {
  test(`notebook retries preserve one history entry and the server status: lost response=${lostResponse}`, async ({ page }) => {
    await setup(page);
    await page.context().addCookies([{ name: 'csrftoken', value: 'audit-csrf', url: 'http://127.0.0.1:5173' }]);
    const first = { id: 1, public_id: 'revision-one', number: 1, checksum: 'a'.repeat(64), blocks: [{ block_type: 'RICH_TEXT', data: { text: 'Original notes' } }], links: [], change_summary: 'Original draft' };
    const recovered = { ...first, id: 2, public_id: 'revision-two', number: 2, checksum: 'b'.repeat(64), change_summary: 'Saved before response was lost', blocks: [{ block_type: 'RICH_TEXT', data: { text: 'Updated notes' } }] };
    const record = { id: 11, public_id: uuid, notebook: 1, notebook_name: 'Protein notebook', title: 'Protein notebook trial', status: 'DRAFT',
      assignees: [], comments: [], reviews: [], workflow_steps: [], permissions: { read: true, write: true }, revisions: [first], current_revision_detail: first };
    let saves = 0;
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let body;
      if (path.endsWith('/notebooks/')) body = [{ id: 1, name: 'Protein notebook', scope: 'USER', permissions: { read: true, write: true } }];
      else if (path.endsWith('/experiments/')) body = [record];
      else if (path.endsWith('/experiments/11/')) body = record;
      else if (path.endsWith('/experiments/11/autosave/')) {
        saves++;
        if (lostResponse && saves === 1) return route.abort('failed');
        body = { created: false, experiment_status: lostResponse ? 'IN_PROGRESS' : 'DRAFT', revision: lostResponse ? recovered : first };
      } else return route.fallback();
      await route.fulfill({ json: body });
    });
    await page.goto('/notebook');
    await expect(page.getByRole('heading', { name: record.title, exact: true })).toBeVisible();
    if (lostResponse) {
      await page.getByPlaceholder('Write observations, rationale, or conclusions...').fill('Updated notes');
      await page.getByRole('button', { name: 'Save now', exact: true }).click();
      await expect(page.getByText('Save failed — refresh required', { exact: true })).toBeVisible();
    }
    await page.getByRole('button', { name: 'Save now', exact: true }).click();
    await expect(page.getByText('All changes saved', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Save now', exact: true }).click();
    await expect.poll(() => saves).toBe(lostResponse ? 3 : 2);
    await page.getByRole('tab', { name: /^History / }).click();
    const history = page.getByRole('table').filter({ has: page.locator('th').filter({ hasText: /^Checksum$/ }) });
    await expect(history.locator('tbody').getByText(lostResponse ? 'r2' : 'r1', { exact: true })).toHaveCount(1);
    await expect(history.locator('tbody tr')).toHaveCount(lostResponse ? 2 : 1);
    await expect(page.locator('.badge').filter({ hasText: /^In progress$/ })).toHaveCount(lostResponse ? 2 : 0);
  });
}
