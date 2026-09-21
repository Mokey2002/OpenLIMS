const { test, expect } = require('@playwright/test');
test('login links to recovery and submits email without exposing account status', async ({ page }) => {
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/csrf/')) return route.fulfill({ json: {}, headers: { 'Set-Cookie': 'csrftoken=test-csrf; Path=/; SameSite=Lax' } });
    if (path.endsWith('/forgot-password/')) {
      expect(route.request().postDataJSON()).toEqual({ email: 'person@example.org' });
      return route.fulfill({ json: { detail: 'If an eligible account exists, you will receive a password reset email. Check your inbox and spam folder.' } });
    }
    await route.fulfill({ json: {} });
  });
  await page.goto('/login');
  await page.getByRole('link', { name: 'Forgot password?' }).click();
  await page.getByLabel('Email address').fill('person@example.org');
  await page.getByRole('button', { name: 'Send reset link' }).click();
  await expect(page.getByRole('status')).toContainText('If an eligible account exists');
  await page.getByRole('link', { name: 'Sign in', exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
});
