const { test, expect } = require('@playwright/test');

async function mockAccession(page, { existing = false, readonly = false, hidden = false, requiredField = false, language = 'en' } = {}) {
  const user = { id: 91, username: 'receiver', roles: [readonly ? 'viewer' : 'admin'] };
  const sample = { id: 42, sample_id: 'TUBE-42', sample_type: requiredField ? 'DNA' : 'GENERAL', project_code: 'LAB', can_modify: !readonly, status: 'RECEIVED' };
  const result = { sample, barcode: sample.sample_id, receipt: null, label_verified_at: null, label_verified_by: null };
  const calls = [];
  await page.context().addCookies([{ name: 'csrftoken', value: 'accession-test-csrf', url: 'http://127.0.0.1:5173' }]);
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1/', '/api/');
    let body = [];
    if (path === '/api/session/') body = { user, feature_flags: {}, unread_notification_count: 0 };
    if (path === '/api/ui-settings/') body = { ui_language: language, assistant_helper_enabled: false };
    if (path === '/api/me/') body = user;
    if (path === '/api/projects/') body = [{ id: 7, code: 'LAB', name: 'Receiving lab', members: [91] }];
    if (path === '/api/sample-forms/') body = requiredField ? [{ id: 5, code: 'DNA', published: true, fields: [{ key: 'volume', en: 'Volume', es: 'Volumen', unit: 'mL', type: 'number', required: true }] }] : [];
    if (path === '/api/samples/accession-lookup/') {
      if (hidden) return route.fulfill({ status: 404, json: { detail: 'Barcode unavailable. Check the code or contact the project owner.' } });
      body = existing ? { kind: 'existing', ...result } : { kind: 'new', barcode: 'TUBE-42' };
    }
    if (request.method() === 'POST') {
      const payload = request.postDataJSON();
      calls.push({ path, payload });
      if (path === '/api/samples/accession-register/') { existing = true; body = { kind: 'existing', ...result }; }
      if (path === '/api/samples/42/receive/') { result.receipt = { received_by: 'receiver', received_at: '2026-11-16T19:00:00Z' }; body = result; }
      if (path === '/api/samples/42/verify-label/') {
        if (payload.barcode !== 'TUBE-42') return route.fulfill({ status: 400, json: { barcode: ['Wrong label. Nothing was changed.'] } });
        result.label_verified_at = '2026-11-16T19:01:00Z'; result.label_verified_by = 'receiver'; body = result;
      }
      if (path === '/api/samples/42/accession-label/') return route.fulfill({ contentType: 'application/pdf', headers: { 'Content-Disposition': 'attachment; filename="sample-42-label.pdf"' }, body: '%PDF-1.4\n' });
    }
    return route.fulfill({ json: body });
  });
  return { calls };
}

async function scan(page, code = 'TUBE-42') {
  await page.getByLabel('Tube barcode', { exact: true }).fill(code);
  await page.getByLabel('Tube barcode', { exact: true }).press('Enter');
}

test('scanner registration, explicit receipt, printable label and matching confirmation', async ({ page }) => {
  const state = await mockAccession(page, { requiredField: true });
  await page.goto('/receive-sample');
  await scan(page);
  await expect(page.getByRole('heading', { name: '1. Register new sample' })).toBeVisible();
  expect(state.calls).toHaveLength(0);
  await page.getByLabel('Receiving project', { exact: true }).selectOption('7');
  await page.getByLabel('Sample type', { exact: true }).selectOption('DNA');
  await page.getByRole('button', { name: 'Register sample', exact: true }).click();
  expect(state.calls).toHaveLength(0);
  await page.getByLabel('Volume (mL) *', { exact: true }).fill('0.5');
  await page.getByRole('button', { name: 'Register sample', exact: true }).click();
  await expect(page.getByRole('link', { name: 'Open sample record' })).toBeVisible();
  expect(state.calls[0].payload).toMatchObject({ barcode: 'TUBE-42', sample_type: 'DNA', project: 7, form_values: { volume: 0.5 } });
  await page.getByLabel('Receipt note / reason', { exact: true }).fill('Tube received intact at the bench');
  await page.getByRole('button', { name: 'Record receipt', exact: true }).click();
  await expect(page.getByLabel('Scan attached label', { exact: true })).toBeFocused();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download printable label' }).click();
  expect((await download).suggestedFilename()).toBe('sample-42-label.pdf');
  await page.getByLabel('Scan attached label', { exact: true }).fill('TUBE-42');
  await page.getByLabel('Scan attached label', { exact: true }).press('Enter');
  await expect(page.getByTestId('receive-sample-page').getByRole('status')).toContainText('Label confirmed by');
  await expect(page.getByLabel('Tube barcode', { exact: true })).toBeFocused();
  await scan(page);
  await expect(page.getByTestId('receive-sample-page').getByRole('status')).toContainText('Label confirmed by');
  expect(state.calls.filter(call => call.path.endsWith('/accession-register/'))).toHaveLength(1);
  expect(state.calls.filter(call => call.path.endsWith('/receive/'))).toHaveLength(1);
});

test('wrong-label scan keeps the selected sample and never confirms it', async ({ page }) => {
  const state = await mockAccession(page, { existing: true });
  await page.goto('/receive-sample');
  await scan(page);
  await page.getByLabel('Receipt note / reason', { exact: true }).fill('Tube received intact at the bench');
  await page.getByRole('button', { name: 'Record receipt', exact: true }).click();
  await page.getByLabel('Scan attached label', { exact: true }).fill('OTHER-TUBE');
  await page.getByLabel('Scan attached label', { exact: true }).press('Enter');
  await expect(page.getByRole('alert').filter({ hasText: 'Wrong label' })).toContainText('Wrong label');
  await expect(page.getByRole('link', { name: 'Open sample record' })).toHaveAttribute('href', '/samples/42');
  await expect(page.getByTestId('receive-sample-page').getByRole('status')).toHaveCount(0);
  expect(state.calls.filter(call => call.path.endsWith('/accession-register/'))).toHaveLength(0);
  // A keyboard scanner replaces the rejected code without manual clearing.
  await page.keyboard.type('TUBE-42');
  await page.keyboard.press('Enter');
  await expect(page.getByTestId('receive-sample-page').getByRole('status')).toContainText('Label confirmed by');
});

test('read-only users can look up existing tubes but cannot record receipt or print', async ({ page }) => {
  const state = await mockAccession(page, { existing: true, readonly: true });
  await page.goto('/receive-sample');
  await scan(page);
  await expect(page.getByText(/Receipt, label generation and confirmation require permission/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Record receipt', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Download printable label' })).toHaveCount(0);
  expect(state.calls).toHaveLength(0);
});

test('an unavailable code cannot start registration', async ({ page }) => {
  await mockAccession(page, { hidden: true });
  await page.goto('/receive-sample');
  await scan(page, 'PRIVATE-TUBE');
  await expect(page.getByRole('alert')).toContainText('Barcode unavailable');
  await expect(page.getByRole('button', { name: 'Register sample', exact: true })).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Open sample record' })).toHaveCount(0);
});


test('Spanish receiving screen supports a keyboard scan into registration', async ({ page }) => {
  await mockAccession(page, { language: 'es' });
  await page.goto('/receive-sample');
  await expect(page.getByRole('heading', { name: 'Recibir muestra', exact: true })).toBeVisible();
  await page.getByLabel('Código del tubo', { exact: true }).fill('TUBE-42');
  await page.getByLabel('Código del tubo', { exact: true }).press('Enter');
  await expect(page.getByRole('heading', { name: '1. Registrar nueva muestra' })).toBeVisible();
  await expect(page.getByLabel('Proyecto receptor', { exact: true })).toBeVisible();
});

test('an unavailable next scan clears the previous tube selection', async ({ page }) => {
  const state = await mockAccession(page, { existing: true });
  await page.goto('/receive-sample');
  await scan(page);
  await expect(page.getByRole('link', { name: 'Open sample record' })).toBeVisible();
  await page.route(url => url.pathname === '/api/v1/samples/accession-lookup/', route => route.fulfill({ status: 404, json: { detail: 'Barcode unavailable.' } }));
  await scan(page, 'PRIVATE-TUBE');
  await expect(page.getByRole('link', { name: 'Open sample record' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Record receipt', exact: true })).toHaveCount(0);
  expect(state.calls).toHaveLength(0);
});
