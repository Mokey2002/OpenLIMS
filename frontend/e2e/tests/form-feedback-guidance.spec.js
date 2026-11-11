const { test, expect } = require('@playwright/test');
const experimentId = 'c80955b7-2b44-4e83-bf10-e6c7f5bb0770';

async function setup(page, options = {}) {
  const state = { user: { id: 1, username: 'director', roles: ['admin'], is_active: true, is_superuser: true }, language: 'en', posts: [], errors: {}, schema: [], experimentStatus: 'IN_PROGRESS', notebookWrite: true, steps: [], ...options };
  await page.context().addCookies([{ name: 'csrftoken', value: 'form-csrf', url: 'http://127.0.0.1:5173' }]);
  const experiment = () => ({ id: 11, public_id: experimentId, title: 'Protein experiment', notebook: 1, status: state.experimentStatus,
    permissions: { read: true, write: state.notebookWrite, review: state.notebookReview || false, lock: false }, workflow_steps: state.steps, comments: [], reviews: [], assignees: [],
    current_revision_detail: { id: 1, public_id: experimentId, number: 1, blocks: [{ block_type: 'RICH_TEXT', data: { text: 'Protein protocol.' } }], links: [], checksum: 'a'.repeat(64) } });
  await page.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname.replace('/api/v1/', '/api/');
    let body = [], status = 200;
    if (request.method() === 'POST') {
      state.posts.push({ path, body: request.postDataJSON() });
      if (state.wait) await state.wait;
      const failure = state.errors[path];
      if (failure?.abort) return route.abort('connectionfailed');
      if (failure) return route.fulfill({ status: failure.status || 400, json: failure.body });
      return route.fulfill({ status: 201, json: { id: 99, ...request.postDataJSON() } });
    }
    if (path === '/api/session/') body = { user: state.user, feature_flags: { notebook: true } };
    else if (path === '/api/me/') body = state.user;
    else if (path === '/api/ui-settings/') body = { ui_language: state.language, assistant_helper_enabled: false };
    else if (path === '/api/feature-flags/') body = { notebook: true };
    else if (path === '/api/projects/') body = [{ id: 1, code: 'ALPHA', name: 'Protein project' }];
    else if (path === '/api/samples/') body = { count: (state.samples || []).length, results: state.samples || [], next: null, previous: null };
    else if (path === '/api/sample-forms/') body = [{ id: 1, code: 'PROTEIN', name_en: 'Protein', name_es: 'Proteína', published: true, archived: false, fields: state.schema }];
    else if (path === '/api/admin-users/') body = { results: [state.user] };
    else if (path === '/api/locations/') body = [{ id: 1, name: 'Freezer A', path: 'Freezer A', kind: 'FREEZER' }];
    else if (path === '/api/notebooks/') body = [{ id: 1, name: 'Protein notebook', permissions: { read: true, write: state.notebookWrite } }];
    else if (path === '/api/experiments/') body = [experiment()];
    else if (path === '/api/experiments/11/') body = experiment();
    else if (path === '/api/work-items/') body = state.work || [];
    await route.fulfill({ status, json: body });
  });
  return state;
}
const sampleId = page => page.locator('input[name="sample_id"]');
const sampleForm = page => page.locator('form').filter({ has: sampleId(page) });
const locationForm = page => page.locator('form').filter({ has: page.locator('input[name="name"][placeholder="Location name"]') });
const containerForm = page => page.locator('form').filter({ has: page.locator('input[name="container_id"]') });

test('required errors focus the exact field before posting and clear when corrected', async ({ page }) => {
  const state = await setup(page); await page.goto('/samples');
  const form = sampleForm(page);
  await form.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(sampleId(page)).toBeFocused();
  await expect(sampleId(page)).toHaveAttribute('aria-invalid', 'true');
  await expect(form.locator('.invalid-feedback')).toContainText('Enter or select a value.');
  expect(state.posts).toHaveLength(0);
  await sampleId(page).fill('PROTEIN-001');
  await expect(sampleId(page)).not.toHaveAttribute('aria-invalid', 'true');
  await expect(form.getByRole('alert')).toHaveCount(0);
});

test('server field errors retain all sample inputs and reset only after a confirmed save', async ({ page }) => {
  const state = await setup(page, { errors: { '/api/samples/': { body: { sample_id: ['This sample ID already exists.'] } } } });
  await page.goto('/samples'); const form = sampleForm(page);
  await sampleId(page).fill('PROTEIN-001');
  await form.locator('[name="sample_type"]').fill('PROTEIN');
  await form.locator('[name="project"]').selectOption('1');
  await form.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(sampleId(page)).toBeFocused();
  await expect(form.locator('.invalid-feedback')).toHaveText('This sample ID already exists.');
  await expect(form.locator('[name="sample_type"]')).toHaveValue('PROTEIN');
  await expect(form.locator('[name="project"]')).toHaveValue('1');
  await sampleId(page).fill('PROTEIN-002'); state.errors = {};
  await form.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(sampleId(page)).toHaveValue('');
  expect(state.posts).toHaveLength(2);
  expect(state.posts[1].body).toMatchObject({ sample_id: 'PROTEIN-002', project: 1, sample_type: 'PROTEIN' });
});

test('nested schema errors highlight measurements and accept zero and false as provided values', async ({ page }) => {
  const state = await setup(page, { schema: [
    { key: 'concentration', en: 'Concentration', es: 'Concentración', type: 'number', min: 0, max: 100, required: true },
    { key: 'frozen', en: 'Frozen', es: 'Congelada', type: 'boolean', required: true },
  ], errors: { '/api/samples/': { body: { form_values: { concentration: ['Check the measurement against the instrument result.'] } } } } });
  await page.goto('/samples'); const form = sampleForm(page);
  await sampleId(page).fill('PROTEIN-001'); await form.locator('[name="sample_type"]').fill('PROTEIN');
  const concentration = form.locator('[name="form_values.concentration"]');
  await concentration.fill('0'); await form.locator('[name="form_values.frozen"]').selectOption('false');
  await form.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(concentration).toBeFocused(); await expect(concentration).toHaveAttribute('aria-invalid', 'true');
  await expect(concentration).toHaveValue('0');
  expect(state.posts[0].body.form_values).toEqual({ concentration: 0, frozen: false });
});

test('user email validation and server password errors retain the account details', async ({ page }) => {
  const state = await setup(page, { errors: { '/api/admin-users/': { body: { password: ['This password is too common. Choose a longer unique password.'] } } } });
  await page.goto('/users'); const form = page.locator('form').filter({ has: page.locator('input[name="username"]') });
  await form.locator('[name="username"]').fill('maria.chen'); await form.locator('[name="email"]').fill('invalid');
  await form.getByRole('button', { name: /Create User|Create user/ }).click();
  await expect(form.locator('[name="email"]')).toBeFocused();
  await expect(form.locator('.invalid-feedback')).toContainText('name@example.org');
  expect(state.posts).toHaveLength(0);
  await form.getByRole('checkbox', { name: 'Send invitation email so the user can set a password', exact: true }).uncheck(); await form.locator('[name="email"]').fill('maria@example.org');
  await form.locator('[name="password"]').fill('common-password');
  await form.getByRole('button', { name: /Create User|Create user/ }).click();
  await expect(form.locator('[name="password"]')).toBeFocused();
  await expect(form.locator('[name="username"]')).toHaveValue('maria.chen');
  await expect(form.locator('[name="password"]')).toHaveValue('common-password');
  expect(state.posts).toHaveLength(1);
});

test('inventory errors are isolated per form and plate size errors explain the valid range', async ({ page }) => {
  const state = await setup(page, { errors: { '/api/locations/': { body: { name: ['A location with this name already exists.'] } } } });
  await page.goto('/inventory'); const location = locationForm(page), container = containerForm(page);
  await location.locator('[name="name"]').fill('Freezer A');
  await location.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(location.locator('[name="name"]')).toBeFocused();
  await container.locator('[name="container_id"]').fill('PLATE-001');
  await container.locator('[name="location"]').selectOption('1'); await container.locator('[name="kind"]').selectOption('PLATE');
  await container.locator('[name="rows"]').fill('0');
  await container.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(container.locator('[name="rows"]')).toBeFocused();
  await expect(container.locator('.invalid-feedback')).toContainText('at least 1');
  await expect(location.locator('.invalid-feedback')).toContainText('already exists');
  expect(state.posts).toHaveLength(1);
});

test('a delayed error never steals focus from another form', async ({ page }) => {
  const state = await setup(page, { errors: { '/api/locations/': { body: { name: ['Choose another location name.'] } } } });
  let release; state.wait = new Promise(resolve => { release = resolve; });
  await page.goto('/inventory'); const location = locationForm(page), container = containerForm(page);
  await location.locator('[name="name"]').fill('Freezer A'); await location.getByRole('button', { name: 'Create', exact: true }).click();
  await container.locator('[name="container_id"]').fill('BOX-001'); release();
  await expect(location.locator('.invalid-feedback')).toBeVisible();
  await expect(container.locator('[name="container_id"]')).toBeFocused();
});

test('permission failures retain values and offer a read-only access review link', async ({ page }) => {
  const state = await setup(page, { errors: { '/api/samples/': { status: 403, body: { detail: 'Your project access changed.' } } } });
  await page.goto('/samples'); const form = sampleForm(page);
  await sampleId(page).fill('PROTEIN-001'); await form.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(form.getByRole('alert')).toBeFocused(); await expect(sampleId(page)).toHaveValue('PROTEIN-001');
  await form.getByRole('link', { name: 'Review my access', exact: true }).click();
  await expect(page).toHaveURL(/\/me$/); expect(state.posts).toHaveLength(1);
});

for (const failure of ['network', 'server']) test(`${failure} failure keeps the draft and does not replay the mutation`, async ({ page }) => {
  const state = await setup(page, { errors: { '/api/samples/': failure === 'network' ? { abort: true } : { status: 500, body: { detail: '<html>private traceback</html>' } } } });
  await page.goto('/samples'); const form = sampleForm(page);
  await sampleId(page).fill('PROTEIN-001'); await form.getByRole('button', { name: 'Create', exact: true }).click();
  await expect(form.getByRole('alert')).toBeVisible(); await expect(sampleId(page)).toHaveValue('PROTEIN-001');
  await expect(form.getByRole('alert')).not.toContainText('private traceback');
  if (failure === 'network') await expect(form.getByRole('alert')).toContainText('whether the record was saved');
  expect(state.posts).toHaveLength(1);
});

test('repeated submissions make only one pending request', async ({ page }) => {
  const state = await setup(page); let release; state.wait = new Promise(resolve => { release = resolve; });
  await page.goto('/samples'); const form = sampleForm(page); await sampleId(page).fill('PROTEIN-001');
  await form.evaluate(element => { element.requestSubmit(); element.requestSubmit(); });
  await expect.poll(() => state.posts.length).toBe(1); await expect(form.getByRole('button', { name: 'Create', exact: true })).toBeDisabled();
  release(); await expect(sampleId(page)).toHaveValue(''); expect(state.posts).toHaveLength(1);
});

test('notebook modal errors stay inside the dialog and preserve its description', async ({ page }) => {
  await setup(page, { errors: { '/api/notebooks/': { body: { name: ['This notebook name is already in use.'] } } } });
  await page.goto('/notebook'); await page.getByRole('button', { name: 'New notebook', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Name', { exact: true }).fill('Protein notebook');
  await dialog.getByLabel('Description', { exact: true }).fill('Protein stability measurements.');
  await dialog.getByLabel('Scope', { exact: true }).selectOption('USER');
  await dialog.getByRole('button', { name: 'Create notebook', exact: true }).click();
  await expect(dialog.getByLabel('Name', { exact: true })).toBeFocused();
  await expect(dialog.getByLabel('Description', { exact: true })).toHaveValue('Protein stability measurements.');
  await expect(dialog.locator('.invalid-feedback')).toContainText('already in use');
});

test('locked notebook actions explain their state through keyboard-accessible disclosures', async ({ page }) => {
  const state = await setup(page, { experimentStatus: 'LOCKED' }); await page.goto('/notebook');
  await expect(page.getByRole('button', { name: 'Save now', exact: true })).toBeDisabled();
  const info = page.getByLabel('Why is Save now unavailable?', { exact: true });
  await info.focus(); await page.keyboard.press('Enter');
  await expect(info.locator('..')).toContainText('This experiment is locked.');
  await expect(info.locator('..')).toContainText('Clone this experiment');
  await expect(page.getByRole('button', { name: 'Clone', exact: true })).toBeEnabled();
  expect(state.posts).toHaveLength(0);
});

test('notebook access and unfinished steps explain different blockers without mutations', async ({ page }) => {
  const state = await setup(page, { notebookWrite: false }); await page.goto('/notebook');
  await page.getByLabel('Why is Save now unavailable?', { exact: true }).click();
  await expect(page.getByText('Ask the notebook owner to grant edit access. Project membership alone may not grant editing.').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Clone', exact: true })).toBeDisabled();
  state.notebookWrite = true; state.steps = [{ position: 1, definition: { name: 'Prepare protein', instructions: 'Prepare the sample.', fields: [] }, values: {}, version: 1, status: 'PENDING' }]; await page.reload();
  await expect(page.getByRole('button', { name: 'Save now', exact: true })).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Complete', exact: true })).toBeDisabled();
  const info = page.getByLabel('Why is Complete unavailable?', { exact: true }); await info.click();
  await expect(info.locator('..')).toContainText('Complete the unfinished workflow steps first.');
  expect(state.posts).toHaveLength(0);
});

test('sample and work disclosures use the server decision and never grant permissions', async ({ page }) => {
  const access = { allowed: false, reason: 'Editing samples requires a technician or administrator role.', next_step: 'Request the appropriate role or ask an administrator.', href: '/access-requests' };
  const state = await setup(page, { user: { id: 2, username: 'viewer', roles: ['viewer'], is_active: true },
    samples: [{ id: 1, sample_id: 'PROTEIN-001', status: 'RECEIVED', can_modify: false, modification_access: access, linked_projects: [] }],
    work: [{ id: 1, name: 'Sequence protein', sample_code: 'PROTEIN-001', status: 'PENDING', can_update: false, update_access: { ...access, reason: 'Updating work requires a technician or administrator role.' } }],
  });
  await page.goto('/samples'); const row = page.getByRole('row').filter({ has: page.getByRole('link', { name: 'PROTEIN-001', exact: true }) });
  await row.getByText('Read-only', { exact: true }).click(); await expect(row).toContainText(access.reason);
  await expect(row.getByRole('link', { name: 'Request access', exact: true })).toHaveAttribute('href', '/access-requests');
  await page.goto('/work-queue');
  await expect(page.getByText('Updating work requires a technician or administrator role.', { exact: true })).toBeVisible();
  await expect(page.getByRole('combobox', { name: /^Update work / })).toHaveCount(0); expect(state.posts).toHaveLength(0);
});


test('review workflow validates signed name without breaking the modal', async ({ page }) => {
  const state = await setup(page, { experimentStatus: 'COMPLETED', notebookReview: true });
  await page.goto('/notebook'); await page.getByRole('button', { name: 'Approve', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Signed name', { exact: true }).fill('');
  await dialog.getByRole('button', { name: 'Confirm', exact: true }).click();
  await expect(dialog.getByLabel('Signed name', { exact: true })).toBeFocused();
  await expect(dialog.locator('.invalid-feedback')).toContainText('Enter or select a value.');
  expect(state.posts).toHaveLength(0);
});

test('Spanish forms translate the validation and unavailable-action explanation', async ({ page }) => {
  const state = await setup(page, { language: 'es' }); await page.goto('/samples');
  const form = sampleForm(page); await form.getByRole('button', { name: 'Crear', exact: true }).click();
  await expect(sampleId(page)).toBeFocused();
  await expect(form.locator('.invalid-feedback')).toHaveText('Introduce o selecciona un valor.');
  state.experimentStatus = 'LOCKED'; await page.goto('/notebook');
  await expect(page.getByText('Este experimento está bloqueado.', { exact: true }).first()).toBeVisible();
});
