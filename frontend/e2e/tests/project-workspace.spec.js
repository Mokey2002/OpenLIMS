const { test, expect } = require('@playwright/test');

for (const role of ['admin', 'viewer']) {
  test(`project navigation and sample search for ${role}`, async ({ page }) => {
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      let body = [];
      if (path.endsWith('/me/')) body = { id: 1, username: 'tester', roles: [role] };
      else if (path.endsWith('/ui-settings/')) body = { ui_language: 'en' };
      else if (path === '/api/v1/projects/1/') body = { id: 1, code: 'TEST', name: 'Test project', members: [], member_usernames: [] };
      else if (path === '/api/v1/samples/') body = { count: 1, next: null, results: [{ id: 1, sample_id: 'S-101', status: 'QC' }] };
      else if (path.endsWith('/custom-fields/')) body = { fields: {} };
      await route.fulfill({ json: body });
    });
    await page.goto('/projects/1');
    await expect(page.getByRole('heading', { name: 'Test project', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Project at a glance' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Add project samples', exact: true })).toHaveCount(role === 'admin' ? 1 : 0);
    await page.getByRole('button', { name: 'Samples', exact: true }).click();
    await expect(page.getByRole('link', { name: 'S-101', exact: true })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Project at a glance' })).toHaveCount(0);
    await page.getByRole('searchbox', { name: 'Search project samples' }).fill('missing');
    await expect(page.getByText('No samples match your search.')).toBeVisible();
    await page.getByRole('searchbox', { name: 'Search project samples' }).fill('s-101');
    await expect(page.getByRole('link', { name: 'S-101', exact: true }).last()).toBeVisible();
    await page.getByRole('button', { name: 'Team', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Save Team', exact: true })).toHaveCount(role === 'admin' ? 1 : 0);
  });
}
