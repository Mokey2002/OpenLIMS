const { test, expect } = require("@playwright/test");

async function mockApp(page, context, language = "en") {
  const state = { views: [], templates: [], preview: null };
  const user = { id: 1, username: "director", roles: ["admin"] };
  await context.addCookies([{ name: "csrftoken", value: "test-token", url: "http://127.0.0.1:5173" }]);
  await page.route("**/api/**", async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    let body = [];
    if (path.endsWith("/session/")) body = { user, feature_flags: {} };
    else if (path.endsWith("/me/")) body = user;
    else if (path.endsWith("/ui-settings/")) body = { ui_language: language };
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
