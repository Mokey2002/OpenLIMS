const { test, expect } = require('@playwright/test');

const projectId = 'c387c5d2-2540-4b7f-a6e8-6e929650cd09';
const requester = { id: 2, username: 'scientist', roles: ['viewer'] };
const administrator = { id: 1, username: 'director', roles: ['admin'] };
function requestRow(index = 1, changes = {}) {
  return {
    id: `0e3fb05c-c514-4d2b-a6a3-${String(index).padStart(12, '0')}`,
    requester_username: 'scientist', kind: 'PROJECT', project_code: `ALPHA-${index}`,
    role: '', reason: 'Please add me to this laboratory project', status: 'PENDING',
    reviewer_username: '', decision_reason: '', access_changed: false,
    created_at: '2026-11-09T10:00:00Z', reviewed_at: null,
    can_withdraw: true, can_review: false, ...changes,
  };
}

async function setup(page, options = {}) {
  const state = { user: requester, language: 'en', rows: [], submissions: [], decisions: [], queries: [], ...options };
  await page.context().addCookies([{ name: 'csrftoken', value: 'access-csrf', url: 'http://127.0.0.1:5173' }]);
  await page.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace('/api/v1/', '/api/');
    if (state.intercept && await state.intercept(route, path)) return;
    let body = [], status = 200;
    if (path === '/api/ui-settings/') body = { ui_language: state.language, assistant_helper_enabled: false };
    else if (path === '/api/session/') body = { user: state.user, feature_flags: {} };
    else if (path === '/api/me/') body = state.user;
    else if (path === '/api/my-work/') body = { summary: {}, assigned_work: [], overdue: [], notifications: [] };
    else if (path === '/api/feature-flags/') body = {};
    else if (path === '/api/access-requests/' && request.method() === 'GET') {
      state.queries.push(Object.fromEntries(url.searchParams));
      const filtered = state.rows.filter(row => !url.searchParams.get('status') || row.status === url.searchParams.get('status'));
      const start = (Number(url.searchParams.get('page') || 1) - 1) * 25;
      body = { count: filtered.length, results: filtered.slice(start, start + 25) };
    } else if (path === '/api/access-requests/' && request.method() === 'POST') {
      const data = request.postDataJSON();
      state.submissions.push(data);
      body = state.rows.find(row => row.status === 'PENDING' && row.kind === data.kind && (row.role || row.project_code).toLowerCase() === (data.role || data.project_code).toLowerCase());
      if (!body) { body = requestRow(state.rows.length + 1, data); state.rows.unshift(body); status = 201; }
    } else if (path.endsWith('/preview/')) {
      const row = state.rows.find(row => path.includes(row.id));
      body = {
        request: row, current_roles: ['viewer'], requester_active: true,
        project: row.kind === 'PROJECT' ? { public_id: projectId, code: row.project_code, name: 'Private sequencing study' } : null,
        already_granted: false, can_approve: true, blockers: [], ...state.preview,
      };
    } else if (path.endsWith('/review/')) {
      const data = request.postDataJSON();
      state.decisions.push(data);
      body = state.rows.find(row => path.includes(row.id));
      Object.assign(body, { status: data.decision, decision_reason: data.decision_reason, can_review: false, can_withdraw: false });
    } else if (path.endsWith('/withdraw/')) {
      body = state.rows.find(row => path.includes(row.id));
      Object.assign(body, { status: 'CANCELLED', can_withdraw: false });
    } else if (path === '/api/admin-users/') body = state.users || [];
    else if (path.match(/^\/api\/admin-users\/\d+\/$/) && request.method() === 'PATCH') {
      state.saved = request.postDataJSON();
      body = state.users.find(user => path.includes(`/${user.id}/`));
      Object.assign(body, state.saved);
      if (state.saved.role) body.roles = [state.saved.role];
    }
    await route.fulfill({ status, json: body });
  });
  return state;
}

test('requester submits without getting access and repeated submissions explain the existing request', async ({ page }) => {
  const state = await setup(page);
  await page.goto('/access-requests');
  await expect(page.getByRole('heading', { name: 'Request additional access' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Review request', exact: true })).toHaveCount(0);
  await expect(page.getByText('Private sequencing study')).toHaveCount(0);
  await page.getByLabel('Project code', { exact: true }).fill('ALPHA');
  await page.getByLabel('Reason (at least 10 characters)', { exact: true }).fill('Need to work on the sequencing project');
  await page.getByRole('button', { name: 'Submit request', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Access has not been granted yet.' })).toContainText('Access has not been granted yet.');
  expect(state.submissions[0]).toEqual({ kind: 'PROJECT', project_code: 'ALPHA', role: '', reason: 'Need to work on the sequencing project' });
  await expect(page.getByRole('button', { name: 'Withdraw request' })).toBeVisible();
  await page.getByLabel('Project code', { exact: true }).fill('alpha');
  await page.getByLabel('Reason (at least 10 characters)', { exact: true }).fill('A different reason for the same access');
  await page.getByRole('button', { name: 'Submit request', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Its original reason is unchanged.' })).toContainText('Its original reason is unchanged.');
  expect(state.rows).toHaveLength(1);
  await page.getByRole('button', { name: 'Withdraw request' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Request withdrawn.' })).toContainText('Request withdrawn.');
  await expect(page.getByText('No requests match this status.')).toBeVisible();
  await page.getByLabel('Filter by status').selectOption('');
  await expect(page.getByRole('cell', { name: 'Withdrawn', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Withdraw request' })).toHaveCount(0);
});

test('administrator previews a project and binds approval to its public identity', async ({ page }) => {
  const state = await setup(page, { user: administrator, rows: [requestRow(1, { can_review: true, can_withdraw: false })] });
  await page.goto('/access-requests');
  await expect(page.getByRole('heading', { name: 'Administrator review queue' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Request additional access' })).toHaveCount(0);
  await page.getByRole('button', { name: 'Review request', exact: true }).click();
  await expect(page.getByText('ALPHA-1 — Private sequencing study', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Approve access', exact: true }).click();
  expect(state.decisions).toHaveLength(0);
  await page.getByLabel('Decision reason (at least 10 characters)', { exact: true }).fill('Approved with the laboratory manager');
  await page.getByRole('button', { name: 'Approve access', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Access request approved.' })).toContainText('Access request approved.');
  expect(state.decisions).toEqual([{ decision: 'APPROVED', decision_reason: 'Approved with the laboratory manager', project_public_id: projectId }]);
  await expect(page.getByRole('button', { name: 'Review request', exact: true })).toHaveCount(0);
});

test('blocked requests remain rejectable without granting access', async ({ page }) => {
  const blocker = 'The project code is missing or ambiguous. Reject the request and ask for clarification.';
  const state = await setup(page, {
    user: administrator, rows: [requestRow(1, { can_review: true, can_withdraw: false, project_code: 'UNKNOWN' })],
    preview: { project: null, can_approve: false, blockers: [blocker] },
  });
  await page.goto('/access-requests');
  await page.getByRole('button', { name: 'Review request', exact: true }).click();
  await expect(page.getByText(blocker)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Approve access' })).toBeDisabled();
  await page.getByRole('button', { name: 'Reject request', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Give a decision reason' })).toBeVisible();
  expect(state.decisions).toHaveLength(0);
  await page.getByLabel('Decision reason (at least 10 characters)', { exact: true }).fill('Please confirm the project code with your manager');
  await page.getByRole('button', { name: 'Reject request', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Access request rejected.' })).toContainText('Access request rejected.');
  expect(state.decisions[0].decision).toBe('REJECTED');
  expect(state.decisions[0].project_public_id).toBeUndefined();
});

test('stale approval requires a refreshed preview before retrying with a new project identity', async ({ page }) => {
  const replacement = 'c387c5d2-2540-4b7f-a6e8-6e929650cd10';
  let failed;
  const state = await setup(page, {
    user: administrator, rows: [requestRow(1, { can_review: true, can_withdraw: false })],
    intercept: async (route, path) => {
      if (path.endsWith('/review/') && !failed) {
        failed = route.request().postDataJSON();
        await route.fulfill({ status: 409, json: { detail: 'The project changed.' } });
        return true;
      }
      return false;
    },
  });
  await page.goto('/access-requests');
  await page.getByRole('button', { name: 'Review request', exact: true }).click();
  await page.getByLabel('Decision reason (at least 10 characters)', { exact: true }).fill('Approved after the manager reviewed the request');
  await page.getByRole('button', { name: 'Approve access' }).click();
  await expect(page.getByText('The request or project changed. Refresh the preview before deciding.')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Approve access' })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Reject request' })).toBeDisabled();
  state.preview = { project: { public_id: replacement, code: 'ALPHA-1', name: 'Replacement project' } };
  await page.getByRole('button', { name: 'Refresh preview' }).click();
  await expect(page.getByText('ALPHA-1 — Replacement project', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Approve access' }).click();
  await expect(page.getByRole('status').filter({ hasText: 'Access request approved.' })).toContainText('Access request approved.');
  expect(failed.project_public_id).toBe(projectId);
  expect(state.decisions[0].project_public_id).toBe(replacement);
});

test('queue pagination resets on filter changes and notification links show decided requests', async ({ page }) => {
  const rows = Array.from({ length: 26 }, (_, index) => requestRow(index + 1));
  rows.push(requestRow(27, { status: 'APPROVED', can_withdraw: false }));
  const state = await setup(page, { rows });
  await page.goto('/access-requests');
  await expect(page.getByText('ALPHA-1', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Next', exact: true }).click();
  await expect(page.getByText('ALPHA-26', { exact: true })).toBeVisible();
  await expect(page.getByText('ALPHA-1', { exact: true })).toHaveCount(0);
  await page.getByLabel('Filter by status').selectOption('APPROVED');
  await expect(page.getByText('ALPHA-27', { exact: true })).toBeVisible();
  expect(state.queries.at(-1)).toEqual({ page: '1', page_size: '25', status: 'APPROVED' });
  await page.goto('/access-requests?status=ALL');
  await expect(page.getByLabel('Filter by status')).toHaveValue('');
  await expect(page.getByText('Requests: 27', { exact: true })).toBeVisible();
  expect(state.queries.at(-1).status).toBeUndefined();
});

test('a new account can request a role in Spanish without requesting administrator privileges', async ({ page }) => {
  const state = await setup(page, { user: { ...requester, roles: [] }, language: 'es' });
  await page.goto('/access-requests');
  await expect(page.getByRole('heading', { name: 'Solicitudes de acceso', exact: true })).toBeVisible();
  await page.getByLabel('Tipo de solicitud').selectOption('ROLE');
  await expect(page.getByLabel('Rol solicitado').locator('option')).toHaveCount(4);
  await page.getByLabel('Rol solicitado').selectOption('viewer');
  await page.getByLabel('Motivo (mínimo 10 caracteres)', { exact: true }).fill('Necesito consultar mis muestras de laboratorio');
  await page.getByRole('button', { name: 'Enviar solicitud', exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: 'El acceso todavía no se ha concedido.' })).toContainText('El acceso todavía no se ha concedido.');
  expect(state.submissions[0].role).toBe('viewer');
  expect(state.submissions[0].project_code).toBe('');
});

test('editing account details preserves additional roles and deliberate role changes still work', async ({ page }) => {
  const state = await setup(page, {
    user: administrator, users: [{ ...requester, roles: ['viewer', 'tech', 'qc_reviewer'], email: 'old@example.org', is_active: true }],
  });
  await page.goto('/users');
  await expect(page.getByRole('link', { name: 'Review access requests', exact: true })).toHaveAttribute('href', '/access-requests');
  let row = page.getByRole('row').filter({ has: page.getByText('scientist', { exact: true }) });
  await row.getByRole('button', { name: 'Edit', exact: true }).click();
  await row.locator('td').nth(1).locator('input').fill('updated@example.org');
  await row.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('updated@example.org', { exact: true })).toBeVisible();
  expect(state.saved.role).toBeUndefined();
  expect(state.users[0].roles).toEqual(['viewer', 'tech', 'qc_reviewer']);
  row = page.getByRole('row').filter({ has: page.getByText('scientist', { exact: true }) });
  await row.getByRole('button', { name: 'Edit', exact: true }).click();
  await row.locator('select').selectOption('qc_reviewer');
  await row.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByText('User updated successfully.')).toBeVisible();
  expect(state.saved.role).toBe('qc_reviewer');
});
