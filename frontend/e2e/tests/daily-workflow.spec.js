const { test, expect } = require('@playwright/test');

const user = { id: 1, username: 'tester', roles: ['admin'] };
const notebooks = [1, 2].map(id => ({ id, name: `Notebook ${id}`, scope: 'USER', permissions: { read: true, write: true } }));
const experiments = [11, 12, 21].map(id => ({ id, public_id: `experiment-${id}`, notebook: id === 21 ? 2 : 1, title: `Experiment ${id}`, status: 'DRAFT', assignees: [], permissions: { read: true, write: true }, comments: [], revisions: [], current_revision_detail: { public_id: `rev-${id}`, number: 1, blocks: [], links: [] } }));
const dashboard = name => ({ summary: { assigned: 1, requests: 0, experiments: 0, qc: 0, inventory_alerts: 0, unread_notifications: 0, overdue: 0 }, assigned_work: [{ id: 1, name, status: 'IN_PROGRESS' }], overdue: [], notifications: [], notebook_enabled: true });
async function mockApi(page, handler) {
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (await handler?.(route, path)) return;
    let body = [];
    if (path.endsWith('/session/')) body = { user, feature_flags: { notebook: true } };
    else if (path.endsWith('/me/')) body = user;
    else if (path.endsWith('/ui-settings/')) body = { ui_language: 'en' };
    else if (path.endsWith('/notebooks/')) body = notebooks;
    else if (path.endsWith('/experiments/')) body = experiments;
    else if (/\/experiments\/\d+\/$/.test(path)) body = experiments.find(row => path.endsWith(`/${row.id}/`));
    await route.fulfill({ json: body });
  });
}

test('My Work retries initial failure and preserves data during a failed background refresh', async ({ page }) => {
  let fail = true;
  let name = 'Assignment A';
  await mockApi(page, async (route, path) => {
    if (!path.endsWith('/my-work/')) return false;
    await route.fulfill(fail ? { status: 503, json: { detail: 'Temporary outage' } } : { json: dashboard(name) });
    return true;
  });
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Retry', exact: true })).toBeVisible();
  fail = false;
  await page.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(page.getByText('Assignment A', { exact: true })).toBeVisible();
  fail = true;
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(page.getByText('Could not refresh.', { exact: false })).toBeVisible();
  await expect(page.getByText('Assignment A', { exact: true })).toBeVisible();
  fail = false;
  name = 'Assignment B';
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(page.getByText('Assignment B', { exact: true })).toBeVisible();
  name = 'Assignment C';
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('openlims:request', { detail: { state: 'success' } })));
  await expect(page.getByText('Assignment C', { exact: true })).toBeVisible();
});

test('failed notebook switch keeps the current notebook and experiment together', async ({ page }) => {
  await mockApi(page, async (route, path) => {
    if (!path.endsWith('/experiments/21/')) return false;
    await route.fulfill({ status: 503, json: { detail: 'Detail unavailable' } });
    return true;
  });
  await page.goto('/notebook');
  await expect(page.getByRole('heading', { name: 'Experiment 11', exact: true })).toBeVisible();
  await page.locator('.notebook-sidebar select').first().selectOption('2');
  await expect(page.getByRole('alert').filter({ hasText: 'failed: 503' })).toBeVisible();
  await expect(page.locator('.notebook-sidebar select').first()).toHaveValue('1');
  await expect(page.getByRole('heading', { name: 'Experiment 11', exact: true })).toBeVisible();
});

test('a late detail response cannot replace the latest selection', async ({ page }) => {
  let release;
  let started;
  const pending = new Promise(resolve => { started = resolve; });
  const gate = new Promise(resolve => { release = resolve; });
  await mockApi(page, async (route, path) => {
    if (!path.endsWith('/experiments/12/')) return false;
    started();
    await gate;
    await route.fulfill({ json: experiments[1] });
    return true;
  });
  await page.goto('/notebook');
  await page.getByRole('button', { name: /Experiment 12/ }).click();
  await pending;
  await page.locator('.notebook-sidebar select').first().selectOption('2');
  await expect(page.getByRole('heading', { name: 'Experiment 21', exact: true })).toBeVisible();
  const response = page.waitForResponse('**/experiments/12/?compact=1');
  release();
  await response;
  // A subsequent UI action ensures React processes the older response.
  await page.getByPlaceholder('Search experiments').fill('21');
  await expect(page.getByRole('heading', { name: 'Experiment 21', exact: true })).toBeVisible();
  await expect(page.locator('.notebook-sidebar select').first()).toHaveValue('2');
});

test('slow or failed supporting lists do not hide accessible experiments', async ({ page }) => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  await mockApi(page, async (route, path) => {
    if (!path.endsWith('/experiment-templates/')) return false;
    await gate;
    await route.fulfill({ status: 503, json: { detail: 'Templates unavailable' } });
    return true;
  });
  await page.goto('/notebook');
  await expect(page.getByRole('heading', { name: 'Experiment 11', exact: true })).toBeVisible();
  release();
  await expect(page.getByText('Some supporting lists could not load.', { exact: false })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Experiment 11', exact: true })).toBeVisible();
});

test('editing during a slow selection preserves the current entry', async ({ page }) => {
  let release;
  let started;
  const pending = new Promise(resolve => { started = resolve; });
  const gate = new Promise(resolve => { release = resolve; });
  await mockApi(page, async (route, path) => {
    if (!path.endsWith('/experiments/12/')) return false;
    started();
    await gate;
    await route.fulfill({ json: experiments[1] });
    return true;
  });
  await page.goto('/notebook');
  await page.getByRole('button', { name: /Experiment 12/ }).click();
  await pending;
  await page.getByRole('button', { name: 'Add notes', exact: true }).click();
  await page.getByPlaceholder('Write observations, rationale, or conclusions...').fill('Keep my observation');
  release();
  await expect(page.getByText('Selection cancelled because you edited', { exact: false })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Experiment 11', exact: true })).toBeVisible();
  await expect(page.getByPlaceholder('Write observations, rationale, or conclusions...')).toHaveValue('Keep my observation');
});

test('an unavailable initial experiment does not hide the notebook navigator', async ({ page }) => {
  await mockApi(page, async (route, path) => {
    if (!path.endsWith('/experiments/11/')) return false;
    await route.fulfill({ status: 403, json: { detail: 'Experiment access changed' } });
    return true;
  });
  await page.goto('/notebook');
  await expect(page.getByRole('alert').filter({ hasText: 'failed: 403' })).toBeVisible();
  await page.getByRole('button', { name: /Experiment 12/ }).click();
  await expect(page.getByRole('heading', { name: 'Experiment 12', exact: true })).toBeVisible();
});

test('My Work keeps the latest refresh when an older response arrives late', async ({ page }) => {
  let phase = 'initial';
  let release;
  let started;
  const pending = new Promise(resolve => { started = resolve; });
  const gate = new Promise(resolve => { release = resolve; });
  await mockApi(page, async (route, path) => {
    if (!path.endsWith('/my-work/')) return false;
    const current = phase;
    if (current === 'slow') { started(); await gate; }
    await route.fulfill({ json: dashboard(`Assignment ${current}`) });
    return true;
  });
  await page.goto('/');
  await expect(page.getByText('Assignment initial', { exact: true })).toBeVisible();
  phase = 'slow';
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await pending;
  await expect(page.getByText('Assignment initial', { exact: true })).toBeVisible();
  phase = 'latest';
  await page.evaluate(() => window.dispatchEvent(new Event('focus')));
  await expect(page.getByText('Assignment latest', { exact: true })).toBeVisible();
  release();
  await expect(page.getByTestId('my-work-page')).toHaveAttribute('aria-busy', 'false');
  await expect(page.getByText('Assignment latest', { exact: true })).toBeVisible();
});
