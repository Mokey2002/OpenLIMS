const { test, expect } = require('@playwright/test');
test('local TeselaGen viewer displays gapped alignment tracks', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body = [];
    if (path.endsWith('/me/')) body = { id: 1, username: 'viewer', roles: ['viewer'] };
    if (path.endsWith('/ui-settings/')) body = { ui_language: 'en' };
    if (path.endsWith('/alignment-jobs/')) body = [{ id: 1, name: 'DNA comparison', status: 'COMPLETED', aligned_fasta: '>Reference\nACGT--ACGT\n>Query\nACGTTTACGT', sequences_detail: [{ sequence_type: 'DNA' }] }];
    await route.fulfill({ json: body });
  });
  await page.goto('/alignments');
  const viewer = page.frameLocator('iframe[title="TeselaGen alignment viewer"]');
  await expect(viewer.getByText('Reference', { exact: true }).first()).toBeVisible();
  await expect(viewer.getByText('Query', { exact: true }).first()).toBeVisible();
  await page.getByRole('button', { name: 'Table view', exact: true }).click();
  await expect(page.getByText('Columns 1–10')).toBeVisible();
  expect(errors).toEqual([]);
});
