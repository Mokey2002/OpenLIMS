const { test, expect } = require("@playwright/test");

async function mockApp(page, context, language = "en") {
  const state = { views: [], templates: [], preview: null, notebookTemplate: { id: 1, notebook: 1, name: "Core protocol", description: "", active: true, updated_at: "2026-01-01T00:00:00Z", blocks: [{ block_type: "HEADING", data: { text: "Objective", level: 2 } }] } };
  const user = { id: 1, username: "director", roles: ["admin"] };
  await context.addCookies([{ name: "csrftoken", value: "test-token", url: "http://127.0.0.1:5173" }]);
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname.replace("/api/v1/", "/api/");
    let body = [];
    if (path.endsWith("/session/")) body = { user, feature_flags: { notebook: true } };
    else if (path.endsWith("/me/")) body = user;
    else if (path.endsWith("/ui-settings/")) body = { ui_language: language };
    else if (path === "/api/notebooks/") body = [{ id: 1, name: "Core", scope: "USER", permissions: { write: true }, readers: [], editors: [], commenters: [], reviewers: [], lockers: [], team_members: [] }];
    else if (path === "/api/experiment-templates/") body = [state.notebookTemplate];
    else if (path === "/api/experiment-templates/1/") { state.savedStructure = request.postDataJSON(); state.notebookTemplate = { ...state.notebookTemplate, ...state.savedStructure }; body = state.notebookTemplate; }
    else if (path === "/api/assistant/investigations/") body = { answer: "Synthetic evidence", investigation: {}, context: { investigation: { identifier: "S-1" } } };
    else if (path === "/api/assistant/chat/") { state.exportRequest = request.postDataJSON(); body = { answer: "Preview captured" }; }
    else if (path.endsWith("/my-work/")) body = {
      summary: { assigned: 1, requests: 0, experiments: 0, qc: 0, inventory_alerts: 0, unread_notifications: 0, overdue: 0 },
      assigned_work: [{ id: 1, name: "DNA extraction", sample_code: "S-1", status: "PENDING", qc_status: "PENDING_REVIEW" }],
      overdue: [], notifications: [], notebook_enabled: false,
    };
    else if (path.endsWith("/workspace-views/")) {
      if (request.method() === "POST") { body = { ...request.postDataJSON(), id: 1, owner: 1 }; state.views = [body]; }
      else body = state.views;
    } else if (path.endsWith("/print-templates/preview/")) {
      state.preview = request.postDataJSON();
      return route.fulfill({ contentType: "application/pdf", headers: { "Content-Disposition": 'attachment; filename="template-preview.pdf"' }, body: "%PDF-1.4\n%%EOF" });
    } else if (path.endsWith("/print-templates/")) {
      if (request.method() === "POST") { body = { ...request.postDataJSON(), id: 1, revision: 1, archived: false }; state.templates = [body]; }
      else body = state.templates;
    }
    await route.fulfill({ json: body });
  });
  return state;
}

test("personal dashboard view survives reload and restores columns", async ({ page, context }) => {
  const state = await mockApp(page, context);
  await page.goto("/my-work");
  await expect(page.getByRole("columnheader", { name: "QC", exact: true })).toBeVisible();
  await page.getByText("Customize My Work", { exact: true }).click();
  await page.getByLabel("Attention", { exact: true }).uncheck();
  await page.getByLabel("QC", { exact: true }).uncheck();
  await page.getByLabel("New view name", { exact: true }).fill("Bench");
  await page.getByRole("button", { name: "Save new view", exact: true }).click();
  await expect.poll(() => state.views.length).toBe(1);
  await page.reload();
  await expect(page.getByRole("columnheader", { name: "QC", exact: true })).toHaveCount(0);
  await page.getByText("Customize My Work", { exact: true }).click();
  await expect(page.getByLabel("Saved view", { exact: true })).toHaveValue("1");
  await page.getByLabel("Saved view", { exact: true }).selectOption("");
  await expect(page.getByRole("columnheader", { name: "QC", exact: true })).toBeVisible();
});

test("director saves and previews a label template", async ({ page, context }) => {
  const state = await mockApp(page, context);
  await page.goto("/labels");
  await page.getByText("Edit print templates", { exact: true }).click();
  await page.getByLabel("Template name", { exact: true }).fill("Core labels");
  await page.getByLabel("Heading / lab name", { exact: true }).fill("Genomics Core");
  await page.getByLabel("Paper", { exact: true }).selectOption("A4");
  await page.getByLabel("Columns", { exact: true }).selectOption("1");
  await page.getByRole("button", { name: "Save template", exact: true }).click();
  await expect.poll(() => state.templates[0]?.config.columns).toBe(1);
  await expect(page.getByLabel("Print template", { exact: true })).toHaveValue("1");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Preview PDF (synthetic data)", exact: true }).click();
  expect((await download).suggestedFilename()).toBe("template-preview.pdf");
  expect(state.preview.config.title).toBe("Genomics Core");
  await page.reload();
  await page.getByLabel("Print template", { exact: true }).selectOption("1");
  await page.getByText("Edit print templates", { exact: true }).click();
  await expect(page.getByLabel("Heading / lab name", { exact: true })).toHaveValue("Genomics Core");
});

test("Spanish customization controls have explicit labels", async ({ page, context }) => {
  await mockApp(page, context, "es");
  await page.goto("/labels");
  await page.getByText("Editar plantillas de impresión", { exact: true }).click();
  await expect(page.getByLabel("Nombre de plantilla", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Columnas", { exact: true })).toBeVisible();
});

test("director configures a landscape report template", async ({ page, context }) => {
  const state = await mockApp(page, context);
  await page.goto("/reports");
  await page.getByText("Edit print templates", { exact: true }).click();
  await page.getByLabel("Template name", { exact: true }).fill("Audit landscape");
  await page.getByLabel("Orientation", { exact: true }).selectOption("landscape");
  await page.getByRole("button", { name: "Save template", exact: true }).click();
  await expect.poll(() => state.templates[0]?.config.orientation).toBe("landscape");
  expect(state.templates[0].kind).toBe("REPORT");
});


test("notebook designer reorders and saves reusable sections", async ({ page, context }) => {
  const state = await mockApp(page, context);
  await page.goto("/notebook");
  await page.getByRole("tab", { name: "Templates", exact: true }).click();
  await page.getByRole("button", { name: "Edit structure", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "Add Heading", exact: true }).click();
  await dialog.getByPlaceholder("Section heading").nth(1).fill("Conclusions");
  await dialog.getByRole("button", { name: "Move block up", exact: true }).nth(1).click();
  await dialog.getByRole("button", { name: "Save structure", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  expect(state.savedStructure.blocks.map(b => b.data.text)).toEqual(["Conclusions", "Objective"]);
  expect(state.savedStructure.expected_updated_at).toBe("2026-01-01T00:00:00Z");
  await page.reload();
  await page.getByRole("tab", { name: "Templates", exact: true }).click();
  await page.getByRole("button", { name: "Edit structure", exact: true }).click();
  await expect(page.getByRole("dialog").getByPlaceholder("Section heading").first()).toHaveValue("Conclusions");
});

test("investigation PDF carries the selected template and previews its layout", async ({ page, context }) => {
  const state = await mockApp(page, context);
  await page.goto("/investigations");
  await page.getByPlaceholder("Example: S-ALPHA-003").fill("S-1");
  await page.getByRole("button", { name: "Run investigation", exact: true }).click();
  await page.getByText("Edit print templates", { exact: true }).click();
  await page.getByLabel("Template name", { exact: true }).fill("Evidence");
  await page.getByLabel("Summary placement", { exact: true }).selectOption("after");
  await page.getByLabel("Chart placement", { exact: true }).selectOption("after");
  await page.getByRole("button", { name: "Save template", exact: true }).click();
  await expect(page.getByLabel("Print template", { exact: true })).toHaveValue("1");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Preview PDF (synthetic data)", exact: true }).click();
  await download;
  expect(state.preview.report_type).toBe("investigation");
  expect(state.preview.config.chart_position).toBe("after");
  await page.getByRole("button", { name: "Export PDF evidence package", exact: true }).click();
  await expect.poll(() => state.exportRequest?.context.print_template_id).toBe(1);
  await page.getByRole("button", { name: "Export CSV", exact: true }).click();
  await expect.poll(() => state.exportRequest?.message).toContain("CSV");
  expect(state.exportRequest.context.print_template_id).toBeUndefined();
});
