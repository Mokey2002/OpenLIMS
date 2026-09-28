const { test, expect } = require('@playwright/test');

// Browser regression with controlled API responses; backend authorization is
// tested separately against the real database, not inferred from these mocks.
for (const query of ['experiment=missing', 'notebook=999']) {
  test(`unavailable notebook link does not open an unrelated record: ${query}`, async ({ page }) => {
    const detailRequests = [];
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/api/**', async route => {
      const path = new URL(route.request().url()).pathname;
      const user = { id: 1, username: 'tester', roles: ['admin'] };
      let body = [];
      if (path.endsWith('/session/')) body = { user, feature_flags: { notebook: true } };
      else if (path.endsWith('/me/')) body = user;
      else if (path.endsWith('/ui-settings/')) body = { ui_language: 'en' };
      else if (path.endsWith('/notebooks/')) body = [{ id: 1, name: 'Accessible notebook', permissions: { read: true, write: true } }];
      else if (path.endsWith('/experiments/')) body = [{ id: 11, public_id: 'available', notebook: 1, title: 'Unrelated experiment', status: 'DRAFT', assignees: [] }];
      else if (/\/experiments\/\d+\/$/.test(path)) {
        detailRequests.push(path);
        return route.fulfill({ status: 500, json: { detail: 'Should not fetch another experiment' } });
      }
      await route.fulfill({ json: body });
    });
    await page.goto(`/notebook?${query}`);
    await expect(page.getByText('This linked record is unavailable or you no longer have access. Choose a notebook to continue.')).toBeVisible();
    await expect(page.getByText('No experiment selected', { exact: true })).toBeVisible();
    expect(detailRequests).toEqual([]);
    expect(errors).toEqual([]);
  });
}
