const { test, expect } = require('@playwright/test');

const admin = { id: 1, username: 'director', roles: ['admin'], is_active: true, is_superuser: true, is_last_active_admin: true };
const departing = { id: 2, username: 'departing-scientist', roles: ['tech'], is_active: true };
const successor = { id: 3, username: 'replacement-scientist', roles: ['tech', 'qc_reviewer'], is_active: true };
const previewId = '54f357b3-b793-4a7e-86fa-293ce03f3900';
const reason = 'Confirmed departure and laboratory handover';

function snapshot(custody = false) {
  return {
    user: departing, responsibilities: {
      samples: [{ id: 10, label: 'PROTEIN-100', status: 'IN_PROGRESS' }],
      work_items: [{ id: 11, label: 'PROTEIN-100: Concentration', status: 'PENDING' }],
      ...(custody ? { custody: [{ id: 10, label: 'PROTEIN-100', status: 'IN_PROGRESS' }] } : {}),
    },
    total_responsibilities: custody ? 3 : 2, counts: { samples: 1, work_items: 1, ...(custody ? { custody: 1 } : {}) },
    projects: [{ id: 5, code: 'PROTEIN', name: 'Protein study' }], notebook_grants: { editors: [{ id: 7, name: 'Protein notebook' }] },
    pending_access_requests: [], proposed_actions: [], subscriptions: [], chat_requests: [],
    continuing_jobs: [], open_requests: [], future_bookings: [],
  };
}

async function setup(page, options = {}) {
  const state = { user: { ...admin }, users: [{ ...admin }, { ...departing }, { ...successor }], review: { snapshot: snapshot(options.custody), blockers: [], successors: [admin, successor] },
    previews: [], confirmations: [], transfers: 0, language: 'en', ...options };
  await page.context().addCookies([{ name: 'csrftoken', value: 'offboarding-csrf', url: 'http://127.0.0.1:5173' }]);
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace('/api/v1/', '/api/');
    let body = [], status = 200;
    if (path === '/api/session/') body = { user: state.user, feature_flags: {} };
    else if (path === '/api/me/') body = state.user;
    else if (path === '/api/ui-settings/') body = { ui_language: state.language, assistant_helper_enabled: false };
    else if (path === '/api/feature-flags/') body = {};
    else if (path === '/api/admin-users/') body = { results: state.users };
    else if (path.endsWith('/2/offboarding/')) body = state.review;
    else if (path.endsWith('/2/offboarding/preview/')) {
      const submitted = request.postDataJSON();
      state.previews.push(submitted);
      expect(request.headers()['x-csrftoken']).toBe('offboarding-csrf');
      if (state.previewBlocker) { status = 400; body = { detail: 'Resolve the offboarding blockers before continuing.', blockers: [state.previewBlocker] }; }
      else body = { preview_id: previewId, expires_at: new Date(Date.now() + 900000).toISOString(), snapshot: state.review.snapshot, successor, reason: submitted.reason };
    } else if (path.endsWith('/2/offboarding/confirm/')) {
      state.confirmations.push(request.postDataJSON());
      expect(request.headers()['x-csrftoken']).toBe('offboarding-csrf');
      if (state.confirmFailure) { status = state.confirmFailure; body = { detail: status === 409 ? 'Responsibilities or access changed. Review a new offboarding preview.' : 'Your administrator access changed. Refresh the page and sign in again if needed.' }; }
      else {
        if (!state.receipt) {
          state.transfers += 1;
          state.receipt = { offboarding_id: previewId, completed_at: new Date().toISOString(), user: departing.username, successor: successor.username,
            total_transferred: state.review.snapshot.total_responsibilities, projects_removed: 1, notebook_grants_removed: 1 };
          Object.assign(state.users[1], { is_active: false, roles: [] });
        }
        if (state.loseResponse && state.confirmations.length === 1) return state.loseResponse === 'gateway'
          ? route.fulfill({ status: 503, json: { detail: 'Gateway response unavailable' } }) : route.abort('failed');
        body = state.receipt;
      }
    }
    await route.fulfill({ status, json: body });
  });
  return state;
}

async function open(page) {
  await page.goto('/users');
  await page.getByRole('row').filter({ hasText: departing.username }).getByRole('button', { name: 'Offboard', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  return page.getByRole('dialog');
}

async function prepare(dialog, custody = false) {
  await dialog.getByLabel('Replacement', { exact: true }).selectOption(String(successor.id));
  await dialog.getByLabel('Offboarding reason (at least 10 characters)', { exact: true }).fill(reason);
  if (custody) await dialog.getByLabel('I verified the physical sample handoff to the replacement.', { exact: true }).check();
  await dialog.getByRole('button', { name: 'Preview offboarding', exact: true }).click();
  await expect(dialog.getByText('Review and confirm', { exact: true })).toBeVisible();
}

test('review names responsibilities and requires a preview and confirmation before changing access', async ({ page }) => {
  const state = await setup(page);
  const dialog = await open(page);
  await expect(dialog.getByRole('button', { name: 'Preview offboarding' })).toBeDisabled();
  await dialog.getByText('Sample assignments (1)', { exact: true }).click();
  await expect(dialog.getByRole('cell', { name: 'PROTEIN-100', exact: true })).toBeVisible();
  expect(state.transfers).toBe(0);
  await prepare(dialog);
  expect(state.previews).toEqual([{ successor_id: 3, reason, custody_confirmed: false }]);
  const confirm = dialog.getByRole('button', { name: 'Confirm offboarding', exact: true });
  await expect(confirm).toBeDisabled();
  await dialog.getByLabel('I reviewed the responsibility transfers and access removal.', { exact: true }).check();
  await confirm.click();
  await expect(dialog.getByText('Offboarding completed: departing-scientist', { exact: true })).toBeVisible();
  expect(state.confirmations).toEqual([{ preview_id: previewId, confirmed: true }]);
  expect(state.transfers).toBe(1);
  await dialog.getByRole('button', { name: 'Done', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('row').filter({ hasText: departing.username }).getByText('Disabled', { exact: true })).toBeVisible();
});

test('physical custody requires an explicit verified handoff', async ({ page }) => {
  const state = await setup(page, { custody: true });
  const dialog = await open(page);
  await dialog.getByLabel('Replacement', { exact: true }).selectOption('3');
  await dialog.getByLabel('Offboarding reason (at least 10 characters)', { exact: true }).fill(reason);
  await expect(dialog.getByRole('button', { name: 'Preview offboarding' })).toBeDisabled();
  await dialog.getByLabel('I verified the physical sample handoff to the replacement.', { exact: true }).check();
  await dialog.getByRole('button', { name: 'Preview offboarding', exact: true }).click();
  await expect(dialog.getByText('Review and confirm', { exact: true })).toBeVisible();
  expect(state.previews[0].custody_confirmed).toBe(true);
  expect(state.transfers).toBe(0);
});

test('ineligible replacements show the server blocker without changing the account', async ({ page }) => {
  const state = await setup(page, { previewBlocker: 'PROTEIN-100: add the replacement to project PROTEIN first.' });
  const dialog = await open(page);
  await dialog.getByLabel('Replacement', { exact: true }).selectOption('3');
  await dialog.getByLabel('Offboarding reason (at least 10 characters)', { exact: true }).fill(reason);
  await dialog.getByRole('button', { name: 'Preview offboarding', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText(state.previewBlocker);
  await expect(dialog.getByRole('button', { name: 'Confirm offboarding', exact: true })).toHaveCount(0);
  expect(state.transfers).toBe(0);
});

test('stale confirmation invalidates the preview and requires another review', async ({ page }) => {
  const state = await setup(page, { confirmFailure: 409 });
  const dialog = await open(page);
  await prepare(dialog);
  await dialog.getByLabel('I reviewed the responsibility transfers and access removal.', { exact: true }).check();
  await dialog.getByRole('button', { name: 'Confirm offboarding', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('Responsibilities or access changed. Review a new offboarding preview.');
  await expect(dialog.getByRole('button', { name: 'Confirm offboarding', exact: true })).toHaveCount(0);
  await expect(dialog.getByRole('button', { name: 'Preview offboarding', exact: true })).toBeEnabled();
  expect(state.transfers).toBe(0);
});

for (const loseResponse of ['network', 'gateway']) test(`a lost ${loseResponse} completion response recovers the same receipt without transferring twice`, async ({ page }) => {
  const state = await setup(page, { loseResponse });
  const dialog = await open(page);
  await prepare(dialog);
  await dialog.getByLabel('I reviewed the responsibility transfers and access removal.', { exact: true }).check();
  await dialog.getByRole('button', { name: 'Confirm offboarding', exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Retry confirmation', exact: true })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Edit handover', exact: true })).toBeDisabled();
  await dialog.getByRole('button', { name: 'Retry confirmation', exact: true }).click();
  await expect(dialog.getByText('Offboarding completed: departing-scientist', { exact: true })).toBeVisible();
  expect(state.confirmations).toHaveLength(2);
  expect(state.confirmations[1]).toEqual(state.confirmations[0]);
  expect(state.transfers).toBe(1);
});

test('revoked administrator access prevents another confirmation', async ({ page }) => {
  await setup(page, { confirmFailure: 403 });
  const dialog = await open(page);
  await prepare(dialog);
  await dialog.getByLabel('I reviewed the responsibility transfers and access removal.', { exact: true }).check();
  await dialog.getByRole('button', { name: 'Confirm offboarding', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('Your administrator access changed.');
  await expect(dialog.getByRole('button', { name: 'Confirm offboarding', exact: true })).toBeDisabled();
});

test('self offboarding is disabled and continuing activity is clearly identified', async ({ page }) => {
  const review = { snapshot: snapshot(), blockers: [], successors: [successor] };
  review.snapshot.continuing_jobs = [{ id: 5, summary: 'Protein sequence analysis is queued' }];
  review.snapshot.open_requests = [{ id: 7, request_number: 'REQ-42', title: 'Protein assay request' }];
  await setup(page, { review });
  const dialog = await open(page);
  await expect(dialog.getByText('Protein sequence analysis is queued', { exact: true })).toBeVisible();
  await expect(dialog.getByText('REQ-42: Protein assay request', { exact: true })).toBeVisible();
  await expect(dialog.getByText('Already queued jobs, submitted requests and instrument bookings are preserved. Offboarding does not stop instrument runs or cancel these records. Review their existing controls if cancellation is needed.', { exact: true })).toBeVisible();
  await dialog.locator('.modal-footer').getByRole('button', { name: 'Close', exact: true }).click();
  await expect(page.getByRole('row').filter({ hasText: 'director' }).getByRole('button', { name: 'Offboard', exact: true })).toBeDisabled();
});

test('the offboarding review and handoff controls are available in Spanish', async ({ page }) => {
  await setup(page, { language: 'es' });
  await page.goto('/users');
  await page.getByRole('row').filter({ hasText: departing.username }).getByRole('button', { name: 'Dar de baja', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('Baja coordinada de usuarios: departing-scientist', { exact: true })).toBeVisible();
  await expect(dialog.getByLabel('Persona de reemplazo', { exact: true })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Vista previa de la baja', exact: true })).toBeDisabled();
});

test('a previous handover receipt can be inspected after reopening the review', async ({ page }) => {
  const review = { snapshot: snapshot(), blockers: [], successors: [successor], latest_receipt: {
    completed_at: new Date().toISOString(), total_transferred: 9, successor: successor.username, reason: 'Previous handover for the protein study',
  } };
  await setup(page, { review });
  const dialog = await open(page);
  await dialog.getByText(/A previous offboarding receipt is available/).click();
  await expect(dialog.getByText('Responsibilities transferred: 9', { exact: false })).toBeVisible();
  await expect(dialog.getByText('Reason: Previous handover for the protein study', { exact: true })).toBeVisible();
});
