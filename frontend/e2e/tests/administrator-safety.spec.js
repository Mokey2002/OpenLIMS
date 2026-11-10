const { test, expect } = require('@playwright/test');

const message = 'Keep at least one active administrator. Create or activate another administrator before removing this access.';
const root = { id: 1, username: 'director', roles: ['admin'], is_active: true, is_superuser: true, is_staff: true, email: 'owner@example.org', is_last_active_admin: true };
const scientist = { id: 2, username: 'scientist', roles: ['viewer'], is_active: true, email: 'scientist@example.org', is_last_active_admin: false };

async function setup(page, options = {}) {
  const state = { user: { ...root }, users: [{ ...root }, { ...scientist }], changes: [], language: 'en', ...options };
  await page.context().addCookies([{ name: 'csrftoken', value: 'safety-csrf', url: 'http://127.0.0.1:5173' }]);
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1/', '/api/');
    let body = [], status = 200;
    if (path === '/api/session/') body = { user: state.user, feature_flags: {} };
    else if (path === '/api/me/') body = state.user;
    else if (path === '/api/ui-settings/') body = { ui_language: state.language, assistant_helper_enabled: false };
    else if (path === '/api/feature-flags/') body = {};
    else if (path === '/api/admin-users/') body = { results: state.users };
    else if (/^\/api\/admin-users\/\d+\/$/.test(path) && ['PATCH', 'DELETE'].includes(request.method())) {
      const change = { method: request.method(), body: request.postData() ? request.postDataJSON() : undefined };
      state.changes.push(change);
      expect(request.headers()['x-csrftoken']).toBe('safety-csrf');
      if (state.failure === 409) {
        state.users = [{ ...root, is_last_active_admin: true }, { ...scientist }];
        status = 409; body = { code: 'last_active_administrator', detail: message };
      } else if (state.failure === 403) {
        state.user = { ...root, roles: ['viewer'], is_superuser: false };
        status = 403; body = { detail: 'Permission denied.' };
      } else {
        const user = state.users.find(user => path.includes(`/${user.id}/`));
        if (request.method() === 'DELETE') { state.users = state.users.filter(row => row !== user); status = 204; }
        else {
          Object.assign(user, change.body);
          if (change.body.role) user.roles = [change.body.role];
          if (user.id === state.user.id) state.user = { ...user };
          body = user;
        }
      }
    }
    if (status === 204) return route.fulfill({ status, body: '' });
    await route.fulfill({ status, json: body });
  });
  return state;
}

function userRow(page, username = 'director') {
  return page.getByRole('row').filter({ has: page.getByText(username, { exact: true }) });
}

test('last administrator controls explain the protection while profile edits remain available', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/users');
  const row = userRow(page);
  await expect(row.getByText('Last active administrator', { exact: true })).toBeVisible();
  await expect(page.getByText(message, { exact: true })).toBeVisible();
  for (const name of ['Disable', 'Delete']) await expect(row.getByRole('button', { name, exact: true })).toBeDisabled();
  await expect(userRow(page, 'scientist').getByRole('button', { name: 'Disable', exact: true })).toBeEnabled();
  await row.getByRole('button', { name: 'Edit', exact: true }).click();
  await expect(row.locator('select')).toBeDisabled();
  await expect(row.getByRole('checkbox', { name: 'Active', exact: true })).toBeDisabled();
  await row.locator('td').nth(1).locator('input').fill('updated@example.org');
  await row.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('updated@example.org', { exact: true })).toBeVisible();
  expect(state.changes[0].body.role).toBeUndefined();
  expect(state.changes[0].body.is_active).toBe(true);
});

test('a second active administrator leaves ordinary handover controls available', async ({ page }) => {
  const state = await setup(page, { users: [
    { ...root, is_last_active_admin: false }, { ...scientist, roles: ['admin'] },
  ] });
  await page.goto('/users');
  const row = userRow(page);
  await expect(row.getByRole('button', { name: 'Disable', exact: true })).toBeEnabled();
  await expect(row.getByRole('button', { name: 'Delete', exact: true })).toBeEnabled();
  await row.getByRole('button', { name: 'Edit', exact: true }).click();
  await expect(row.locator('select')).toBeEnabled();
  await row.locator('select').selectOption('viewer');
  await row.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('User updated successfully.')).toBeVisible();
  expect(state.changes[0].body.role).toBe('viewer');
  await expect(page.getByRole('button', { name: 'Create User', exact: true })).toHaveCount(0);
});

for (const action of ['Disable', 'Delete']) {
  test(`a stale ${action.toLowerCase()} action refreshes protection and displays a useful conflict`, async ({ page }) => {
    const state = await setup(page, { users: [{ ...root, is_last_active_admin: false }, { ...scientist }], failure: 409 });
    await page.goto('/users');
    page.once('dialog', dialog => dialog.accept());
    await userRow(page).getByRole('button', { name: action, exact: true }).click();
    await expect(page.getByRole('alert').filter({ hasText: message }).first()).toBeVisible();
    await expect(userRow(page).getByText('Last active administrator', { exact: true })).toBeVisible();
    await expect(userRow(page).getByRole('button', { name: action, exact: true })).toBeDisabled();
    expect(state.changes).toHaveLength(1);
    expect(state.changes[0].method).toBe(action === 'Delete' ? 'DELETE' : 'PATCH');
    await expect(page.getByText(/(?:PATCH|DELETE) \/api/)).toHaveCount(0);
    await expect(page.getByText(/User "director" disabled\.|User deleted successfully\./)).toHaveCount(0);
  });
}

test('a stale role edit is closed after the server protects the last administrator', async ({ page }) => {
  await setup(page, { users: [{ ...root, is_last_active_admin: false }], failure: 409 });
  await page.goto('/users');
  await userRow(page).getByRole('button', { name: 'Edit', exact: true }).click();
  await userRow(page).locator('select').selectOption('tech');
  await userRow(page).getByRole('button', { name: 'Save', exact: true }).click();
  await expect(userRow(page).getByRole('button', { name: 'Edit', exact: true })).toBeVisible();
  await expect(page.getByRole('alert').filter({ hasText: message }).first()).toBeVisible();
  await expect(page.getByText('User updated successfully.')).toHaveCount(0);
});

test('revoked administrator access removes management controls after a denied write', async ({ page }) => {
  await setup(page, { failure: 403 });
  await page.goto('/users');
  await userRow(page, 'scientist').getByRole('button', { name: 'Edit', exact: true }).click();
  await userRow(page, 'scientist').locator('td').nth(1).locator('input').fill('new@example.org');
  await userRow(page, 'scientist').getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('Your administrator access changed. Refresh the page and sign in again if needed.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Create User', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Delete', exact: true })).toHaveCount(0);
});

test('protection is explained in Spanish', async ({ page }) => {
  await setup(page, { language: 'es' });
  await page.goto('/users');
  await expect(page.getByText('Último administrador activo', { exact: true })).toBeVisible();
  await expect(page.getByText('Conserva al menos un administrador activo. Crea o activa otro administrador antes de quitar este acceso.', { exact: true })).toBeVisible();
  await expect(userRow(page).locator('button.btn-outline-danger')).toBeDisabled();
});
