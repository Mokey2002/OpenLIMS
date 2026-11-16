const { test, expect } = require('@playwright/test');
const admin = { id: 91, username: 'setup-admin', roles: ['admin'] };
const empty = { users_added: false, project_created: false, sample_registered: false, can_add_users: true, can_create_project: true, can_register_sample: true };
async function mock(page, { setup = empty, user = admin, status = 'RECEIVED', runs = [], allowed = ['IN_PROGRESS', 'CANCELLED'], language = 'en' } = {}) {
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1/', '/api/');
    const data = {
      '/api/session/': { user, feature_flags: {}, unread_notification_count: 0 },
      '/api/me/': user,
      '/api/ui-settings/': { ui_language: language },
      '/api/onboarding/': { enabled: false, experiment: null, lab_setup: setup },
      '/api/samples/1/': { id: 1, public_id: 'sample-public-1', sample_id: 'S-FIRST', status, sample_type: 'GENERAL', can_modify: user.roles.includes('admin'), linked_project_summaries: [], form_values: {} },
      '/api/samples/1/allowed-transitions/': { allowed_transitions: allowed },
      '/api/pipeline-runs/': runs,
    };
    return route.fulfill({ json: data[path] ?? [] });
  });
}

test('lab checklist works with Notebook disabled and refreshes from saved progress', async ({ page }) => {
  let setup = { ...empty };
  await mock(page);
  await page.route('**/api/v1/onboarding/', route => route.fulfill({ json: { enabled: false, experiment: null, lab_setup: setup } }));
  await page.goto('/getting-started');
  const checklist = page.getByTestId('lab-setup-checklist');
  await expect(checklist.getByText('Not started', { exact: true })).toHaveCount(3);
  await expect(checklist.getByRole('link', { name: 'Manage users' })).toHaveAttribute('href', '/users');
  await expect(checklist.getByRole('link', { name: 'Open projects' })).toHaveAttribute('href', '/projects');
  await expect(checklist.getByRole('link', { name: 'Open samples' })).toHaveAttribute('href', '/samples');
  setup = { ...empty, users_added: true, project_created: true, sample_registered: true };
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect(checklist.getByText('Complete', { exact: true })).toHaveCount(3);
});

test('viewer checklist explains who can help without a user-management link', async ({ page }) => {
  await mock(page, { user: { ...admin, roles: ['viewer'] }, setup: { ...empty, users_added: null, can_add_users: false, can_create_project: false, can_register_sample: false } });
  await page.goto('/getting-started');
  const checklist = page.getByTestId('lab-setup-checklist');
  await expect(checklist.getByRole('link', { name: 'Manage users' })).toHaveCount(0);
  await expect(checklist.getByText('Administrator check', { exact: true })).toBeVisible();
  await expect(checklist.getByText(/Ask an administrator or technician/)).toBeVisible();
});

test('sample guidance surfaces failed parallel steps and links to the actual workflow section', async ({ page }) => {
  await mock(page, { status: 'IN_PROGRESS', runs: [{ id: 4, template_name: 'DNA extraction', status: 'ACTIVE', steps: [
    { id: 1, position: 1, name: 'Extract', status: 'FAILED', failure_reason: 'Missing required yield', dependency_positions: [], required_fields: [] },
    { id: 2, position: 2, name: 'Quantify', status: 'BLOCKED', dependency_positions: [1], required_fields: [] },
  ] }] });
  await page.goto('/samples/1');
  const guide = page.getByTestId('sample-workflow-guide');
  await expect(guide.getByText(/A workflow step failed/)).toBeVisible();
  await expect(guide.getByText('Missing required yield', { exact: true })).toBeVisible();
  await guide.getByRole('link', { name: 'Review workflow' }).click();
  await expect(page).toHaveURL(/#sample-workflow$/);
  await expect(page.locator('#sample-workflow')).toBeVisible();
  await expect(page.locator('#sample-status')).toHaveCount(1);
});

test('read-only sample explains quality review without offering editing controls', async ({ page }) => {
  await mock(page, { status: 'QC', user: { ...admin, roles: ['viewer'] }, allowed: ['REPORTED'] });
  await page.goto('/samples/1');
  const guide = page.getByTestId('sample-workflow-guide');
  await expect(guide.getByText(/Quality review is needed/)).toBeVisible();
  await expect(guide.getByText(/You have read-only access/)).toBeVisible();
  await expect(guide.getByRole('link', { name: 'Review status options' })).toHaveCount(0);
  await expect(guide.getByRole('link', { name: 'View results' })).toHaveAttribute('href', '#sample-results');
});

test('archived sample never suggests starting an old active step', async ({ page }) => {
  await mock(page, { status: 'ARCHIVED', allowed: [] });
  await page.goto('/samples/1');
  const guide = page.getByTestId('sample-workflow-guide');
  await expect(guide.getByText(/The sample is archived/)).toBeVisible();
  await expect(guide.getByRole('link', { name: 'Review status options' })).toHaveCount(0);
});

test('setup and sample guidance support Spanish', async ({ page }) => {
  await mock(page, { language: 'es' });
  await page.goto('/getting-started');
  await expect(page.getByRole('heading', { name: 'Configura tu laboratorio' })).toBeVisible();
  await page.goto('/samples/1');
  await expect(page.getByRole('heading', { name: 'Dónde está esta muestra' })).toBeVisible();
});

test('starting an optional experiment retains the lab setup checklist', async ({ page }) => {
  await mock(page);
  await page.context().addCookies([{ name: 'csrftoken', value: 'setup-test-csrf', url: 'http://127.0.0.1:5173' }]);
  await page.route('**/api/v1/onboarding/', route => route.fulfill({ json: route.request().method() === 'POST'
    ? { enabled: true, experiment: { public_id: 'first-experiment', title: 'First extraction', status: 'IN_PROGRESS', can_write: true, steps: [] } }
    : { enabled: true, experiment: null, lab_setup: empty } }));
  await page.route('**/api/v1/experiment-templates/**', route => route.fulfill({ json: [{ id: 1, notebook_name: 'Our lab', name: 'Extraction', workflow_steps: [] }] }));
  await page.goto('/getting-started');
  await page.getByLabel('Workflow template', { exact: true }).selectOption('1');
  await page.getByLabel('Experiment title', { exact: true }).fill('First extraction');
  await page.getByRole('button', { name: 'Create my first experiment' }).click();
  await expect(page.getByRole('button', { name: 'Open experiment' })).toBeVisible();
  await expect(page.getByTestId('lab-setup-checklist')).toBeVisible();
});
