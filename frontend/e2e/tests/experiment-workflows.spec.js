const { test, expect } = require('@playwright/test');

async function workspace(page, { writable = true, unassigned = false } = {}) {
  const user = { id: 1, username: 'scientist', roles: ['admin'] };
  const definitions = [
    { name: 'DNA extraction', instructions: 'Measure DNA', completion_criteria: 'Concentration at least 10', assignee: 1, fields: [{ key: 'concentration', label: 'Concentration', type: 'NUMBER', required: true, minimum: 10 }] },
    { name: 'Review result', instructions: 'Check the measurement', completion_criteria: 'Record a conclusion', assignee: 1, fields: [{ key: 'conclusion', label: 'Conclusion', type: 'STRING', required: true }] },
  ];
  let template = { id: 2, notebook: 1, name: 'DNA workflow', description: '', blocks: [], workflow_steps: definitions, active: true, updated_at: '2026-09-30T00:00:00Z' };
  const experiment = { id: 11, public_id: 'workflow-run', title: 'Workflow trial', notebook: 1, notebook_name: 'Bench', status: 'IN_PROGRESS', assignees: [1], permissions: { read: true, write: writable }, comments: [], revisions: [], current_revision_detail: { number: 1, public_id: 'revision-1', blocks: [], links: [] }, workflow_steps: definitions.map((definition, i) => ({ position: i + 1, definition, assignee: unassigned ? null : 1, assignee_username: unassigned ? "" : 'scientist', values: {}, status: 'PENDING', version: 1 })) };
  const submissions = [];
  let templatePayload;
  let rejectSave = false;
  await page.context().addCookies([{ name: 'csrftoken', value: 'test-csrf', url: 'http://127.0.0.1:5173' }]);
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let body = [];
    if (path.endsWith('/session/')) body = { user, feature_flags: { notebook: true } };
    else if (path.endsWith('/me/')) body = user;
    else if (path.endsWith('/ui-settings/')) body = { ui_language: 'en' };
    else if (path.endsWith('/notebooks/')) body = [{ id: 1, name: 'Bench', scope: 'USER', permissions: { read: true, write: writable } }];
    else if (path.endsWith('/collaborators/')) body = [user];
    else if (path.endsWith('/experiment-templates/')) body = [template];
    else if (path.endsWith('/experiment-templates/2/')) {
      templatePayload = route.request().postDataJSON();
      template = { ...template, ...templatePayload };
      body = template;
    }
    else if (path.endsWith('/experiments/')) body = [experiment];
    else if (path.endsWith('/experiments/11/')) body = experiment;
    else if (path.includes('/workflow-steps/')) {
      const input = route.request().postDataJSON();
      submissions.push(input);
      if (rejectSave) return route.fulfill({ status: 400, json: { detail: 'This step changed. Reload the experiment before saving.' } });
      const position = Number(path.split('/').filter(Boolean).at(-1));
      const step = experiment.workflow_steps[position - 1];
      Object.assign(step, { version: step.version + 1 });
      if (input.operation === "assign") Object.assign(step, { assignee: input.assignee, assignee_username: "scientist" });
      else step.values = input.values;
      if (input.operation === 'complete') Object.assign(step, { status: 'COMPLETED', completed_by_username: 'scientist', completed_at: '2026-09-30T12:00:00Z', completion_note: input.note });
      body = step;
    }
    await route.fulfill({ json: body });
  });
  await page.goto('/notebook');
  await expect(page.getByRole('heading', { name: 'Workflow trial', exact: true })).toBeVisible();
  return { submissions, templatePayload: () => templatePayload, rejectSaves: () => { rejectSave = true; } };
}

test('design reusable ordered steps with typed requirements and responsible people', async ({ page }) => {
  const api = await workspace(page);
  await page.getByRole('tab', { name: 'Templates', exact: true }).click();
  await page.getByRole('button', { name: 'Edit structure', exact: true }).click();
  const steps = page.getByTestId('workflow-design-step');
  await steps.first().getByRole('textbox', { name: 'Step name', exact: true }).fill('DNA extraction v2');
  await steps.first().getByRole('spinbutton', { name: 'Minimum', exact: true }).fill('15');
  await page.getByRole('button', { name: 'Add workflow step', exact: true }).click();
  const last = steps.last();
  await last.getByRole('textbox', { name: 'Step name', exact: true }).fill('Confirm storage');
  await last.getByRole('combobox', { name: 'Default responsible person', exact: true }).selectOption('1');
  await last.getByRole('button', { name: 'Add required field', exact: true }).click();
  await last.getByRole('textbox', { name: 'Field label', exact: true }).fill('Stored');
  await last.getByRole('textbox', { name: 'Field key', exact: true }).fill('stored');
  await last.getByRole('combobox', { name: 'Field type', exact: true }).selectOption('BOOLEAN');
  await last.getByRole('combobox', { name: 'Required value', exact: true }).selectOption('true');
  await last.getByRole('button', { name: 'Move up', exact: true }).click();
  await page.getByRole('button', { name: 'Save structure', exact: true }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  const payload = api.templatePayload();
  expect(payload.workflow_steps.map(step => step.name)).toEqual(['DNA extraction v2', 'Confirm storage', 'Review result']);
  expect(payload.workflow_steps[0].fields[0].minimum).toBe(15);
  expect(payload.workflow_steps[1].fields[0].equals).toBe(true);
  expect(payload.workflow_steps[1].assignee).toBe(1);
  expect(payload.expected_updated_at).toBe('2026-09-30T00:00:00Z');
  await page.getByRole('tab', { name: 'Experiment workspace', exact: true }).click();
  await page.getByRole('tab', { name: /^Workflow / }).click();
  await expect(page.getByTestId('experiment-workflow-step').first().getByRole('heading')).toContainText('DNA extraction');
  await expect(page.getByTestId('experiment-workflow-step')).toHaveCount(2);
});

test('complete experiment steps in one screen with explicit criteria confirmation', async ({ page }) => {
  const api = await workspace(page);
  await page.getByRole('tab', { name: /^Workflow / }).click();
  const steps = page.getByTestId('experiment-workflow-step');
  await expect(steps.nth(1).getByLabel('Conclusion')).toBeDisabled();
  await expect(steps.first().getByRole('button', { name: 'Complete step', exact: true })).toBeDisabled();
  await steps.first().getByLabel('Concentration').fill('43');
  await steps.first().getByRole('button', { name: 'Save progress', exact: true }).click();
  await expect.poll(() => api.submissions.length).toBe(1);
  await expect(steps.first().getByLabel('Concentration')).toHaveValue('43');
  await steps.first().getByLabel('Completion note / assignment reason').fill('Measurement accepted');
  await steps.first().getByRole('checkbox').check();
  await steps.first().getByRole('button', { name: 'Complete step', exact: true }).click();
  await expect(steps.nth(1).getByLabel('Conclusion')).toBeEnabled();
  await expect(steps.first().getByLabel('Concentration')).toBeDisabled();
  await steps.nth(1).getByLabel('Conclusion').fill('Ready for reporting');
  await steps.nth(1).getByLabel('Completion note / assignment reason').fill('Results reviewed');
  await steps.nth(1).getByRole('checkbox').check();
  await steps.nth(1).getByRole('button', { name: 'Complete step', exact: true }).click();
  await expect(page.getByText('2 / 2 steps completed')).toBeVisible();
  await expect(page.getByText('Workflow finished.', { exact: false })).toBeVisible();
  expect(api.submissions[1]).toMatchObject({ operation: 'complete', values: { concentration: 43 }, expected_version: 2, confirmed: true });
});

test('server conflicts retain entered values and reader workflows are read-only', async ({ page }) => {
  const api = await workspace(page);
  api.rejectSaves();
  await page.getByRole('tab', { name: /^Workflow / }).click();
  const first = page.getByTestId('experiment-workflow-step').first();
  await first.getByLabel('Concentration').fill('52');
  await first.getByRole('button', { name: 'Save progress', exact: true }).click();
  await expect(first.getByRole('alert')).toContainText('This step changed');
  await expect(first.getByLabel('Concentration')).toHaveValue('52');
  await page.unroute('**/api/**');
  await workspace(page, { writable: false });
  await page.getByRole('tab', { name: /^Workflow / }).click();
  await expect(page.getByTestId('experiment-workflow-step').first().getByLabel('Concentration')).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Complete step', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Save assignment', exact: true })).toHaveCount(0);
});


test('assignment saves preserve unsaved measurements', async ({ page }) => {
  const api = await workspace(page, { unassigned: true });
  await page.getByRole('button', { name: 'Open workflow steps', exact: true }).click();
  const first = page.getByTestId('experiment-workflow-step').first();
  await first.getByLabel('Concentration').fill('43');
  await first.getByRole('combobox', { name: 'Responsible person', exact: true }).selectOption('1');
  await first.getByLabel('Completion note / assignment reason').fill('Assign to bench scientist');
  await first.getByRole('button', { name: 'Save assignment', exact: true }).click();
  await expect(first.getByRole('alert')).toContainText('Assignment saved');
  await expect(first.getByLabel('Concentration')).toHaveValue('43');
  await first.getByRole('button', { name: 'Save progress', exact: true }).click();
  await expect(first.getByRole('alert')).toContainText('Progress saved');
  expect(api.submissions.at(-1)).toMatchObject({ expected_version: 2, values: { concentration: 43 } });
});
