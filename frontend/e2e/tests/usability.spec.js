const { test, expect } = require('@playwright/test');

const user = { id: 91, username: 'ux-reviewer', roles: ['admin'], is_active: true };
const work = {
  summary: { assigned: 3, requests: 1, experiments: 1, qc: 1, inventory_alerts: 0, unread_notifications: 0, overdue: 1 },
  assigned_work: [
    { id: 1, name: 'Routine analysis', sample_code: 'S-1', status: 'PENDING', qc_status: 'NOT_REQUIRED' },
    { id: 2, name: 'Results awaiting review', sample_code: 'S-2', status: 'IN_PROGRESS', qc_status: 'PENDING_REVIEW' },
    { id: 3, name: 'Overdue extraction', sample_code: 'S-3', status: 'IN_PROGRESS', due_at: '2000-01-01T00:00:00Z' },
  ],
  overdue: [{ key: 'work-3', name: 'Overdue extraction', to: '/work-queue', type: 'Work item', due_at: '2000-01-01T00:00:00Z' }],
  notifications: [], notebook_enabled: true,
};

async function mockAPI(page, overrides = {}) {
  await page.context().addCookies([{ name: 'csrftoken', value: 'ux-test-csrf', url: 'http://127.0.0.1:5173' }]);
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1/', '/api/');
    const defaults = {
      '/api/session/': { user, feature_flags: { notebook_enabled: true }, unread_notification_count: 0 },
      '/api/me/': user,
      '/api/my-work/': work,
      '/api/assistant/status/': {},
      '/api/assistant/conversations/': [],
    };
    await route.fulfill({ json: overrides[path] ?? defaults[path] ?? [] });
  });
}

test('My Work orders overdue work before reviews and provides task actions', async ({ page }) => {
  await mockAPI(page);
  await page.goto('/my-work');
  const rows = page.getByTestId('my-work-page').locator('tbody tr');
  await expect(rows).toHaveCount(3);
  await expect(rows.nth(0)).toContainText('Overdue extraction');
  await expect(rows.nth(1)).toContainText('Results awaiting review');
  await expect(rows.nth(1).getByRole('button', { name: /Review results/ })).toHaveAttribute('href', '/qc-review');
  await expect(page.getByRole('button', { name: /Continue experiment/ })).toHaveAttribute('href', '/notebook');
  await expect(page.getByRole('button', { name: /Check overdue work/ })).toHaveAttribute('href', '#overdue');
});

test('project options retain values when collapsed and submit with required fields', async ({ page }) => {
  await mockAPI(page);
  let payload;
  await page.route('**/api/v1/projects/', async route => {
    if (route.request().method() === 'POST') {
      payload = route.request().postDataJSON();
      return route.fulfill({ status: 201, json: { id: 1, ...payload } });
    }
    return route.fulfill({ json: [] });
  });
  await page.goto('/projects');
  await page.getByLabel('Project name', { exact: true }).fill('First study');
  await page.getByLabel('Project code', { exact: true }).fill('FIRST');
  const options = page.locator('details').filter({ hasText: 'More options' });
  await expect(options).not.toHaveAttribute('open', '');
  await options.locator('summary').click();
  await page.getByLabel('Description', { exact: true }).fill('Keep this optional description');
  await options.locator('summary').click();
  await page.getByRole('button', { name: 'Create Project', exact: true }).click();
  await expect.poll(() => payload?.description).toBe('Keep this optional description');
  expect(payload.name).toBe('First study');
});

test('empty import history offers an assistant command without sending it', async ({ page }) => {
  await mockAPI(page);
  let posted = false;
  page.on('request', request => { if (request.method() === 'POST') posted = true; });
  await page.goto('/imports');
  await expect(page.getByText('No import jobs yet.', { exact: true })).toBeVisible();
  await page.getByRole('link', { name: 'Import an instrument file', exact: true }).click();
  await expect(page.getByPlaceholder('Compare samples or projects, graph results, find outliers...')).toHaveValue('Import an instrument file');
  expect(posted).toBe(false);
});


test('a server error inside collapsed optional fields reveals the field', async ({ page }) => {
  await mockAPI(page);
  await page.route('**/api/v1/projects/', route => route.fulfill({ status: 400, json: { description: ['Please shorten the description.'] } }));
  await page.goto('/projects');
  await page.getByLabel('Project name', { exact: true }).fill('First study');
  await page.getByLabel('Project code', { exact: true }).fill('FIRST');
  await page.getByRole('button', { name: 'Create Project', exact: true }).click();
  await expect(page.getByLabel('Description', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Description', { exact: true })).toBeFocused();
});

test('sample intake keeps required configured fields visible and optional fields collapsed', async ({ page }) => {
  await mockAPI(page, { '/api/sample-forms/': [{ code: 'DNA', published: true, fields: [
    { key: 'notes', en: 'Collection notes', es: 'Notas de recogida', type: 'text', required: false },
    { key: 'volume', en: 'Volume', es: 'Volumen', type: 'number', unit: 'mL', required: true },
  ] }] });
  await page.goto('/samples');
  await page.getByRole('combobox', { name: 'Sample Type', exact: true }).fill('DNA');
  await expect(page.getByLabel('Volume (mL) *', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Collection notes', { exact: true })).toBeHidden();
  const options = page.locator('details').filter({ has: page.getByLabel('Collection notes', { exact: true }) });
  await options.locator('summary').click();
  await expect(page.getByLabel('Collection notes', { exact: true })).toBeVisible();
});

test('new priority and assistant actions follow the instance Spanish language', async ({ page }) => {
  await mockAPI(page, { '/api/ui-settings/': { ui_language: 'es' }, '/api/my-work/': {
    ...work, summary: { ...work.summary, assigned: 0, qc: 0, overdue: 0, experiments: 0, requests: 0 }, assigned_work: [], overdue: [],
  } });
  await page.goto('/my-work');
  await expect(page.getByRole('heading', { name: 'Tus prioridades' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Registrar muestras', exact: true })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Importar un archivo de instrumento', exact: true })).toBeVisible();
});
