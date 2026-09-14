const { test, expect } = require('@playwright/test');

test('invitation creation and public password setup', async ({ page }) => {
  let created, submitted;
  const user = { id: 1, username: 'director', roles: ['admin'] };
  await page.context().addCookies([{ name: 'csrftoken', value: 'test-csrf-token', url: 'http://127.0.0.1:5173' }]);
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body = [];
    if (path.endsWith('/ui-settings/')) body = { ui_language: 'en', assistant_helper_enabled: false };
    if (path.endsWith('/session/')) body = { user, feature_flags: {} };
    if (path.endsWith('/me/')) body = user;
    if (path.endsWith('/admin-users/') && route.request().method() === 'POST') {
      created = route.request().postDataJSON();
      body = { id: 2, invitation_status: 'failed' };
    }
    if (path.endsWith('/auth/set-password/')) {
      submitted = route.request().postDataJSON();
      expect(route.request().headers()['x-csrftoken']).toBe('test-csrf-token');
      body = { detail: 'Password saved.' };
    }
    await route.fulfill({ json: body });
  });
  await page.goto('/users');
  await page.getByPlaceholder('username', { exact: true }).fill('scientist');
  await page.getByPlaceholder('email@example.com').fill('scientist@example.org');
  await expect(page.getByPlaceholder('Temporary password')).toBeDisabled();
  await page.getByRole('button', { name: 'Create User', exact: true }).click();
  await expect(page.getByText('User created, but invitation email failed. Check email settings and resend the invitation.')).toBeVisible();
  expect(created.send_invitation).toBe(true);
  expect(created.password).toBeUndefined();
  await page.goto('/set-password#uid=Mg&token=one-time-link');
  await page.getByLabel('New password', { exact: true }).fill('Long-private-password-927!');
  await page.getByLabel('Confirm password', { exact: true }).fill('different');
  await page.getByRole('button', { name: 'Save password' }).click();
  await expect(page.getByText('Passwords do not match.')).toBeVisible();
  expect(submitted).toBeUndefined();
  await page.getByLabel('Confirm password', { exact: true }).fill('Long-private-password-927!');
  await page.getByRole('button', { name: 'Save password' }).click();
  await expect(page.getByText('Password saved. You can now sign in.')).toBeVisible();
  expect(submitted.uid).toBe('Mg');
  expect(submitted.token).toBe('one-time-link');
  await expect(page).toHaveURL('/set-password');
});
