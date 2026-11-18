const { test, expect } = require("@playwright/test");

test.beforeEach(async ({ page }) => {
  const user = { id: 1, username: "director", roles: ["admin"] };
  const responses = {
    "/api/session/": { user, feature_flags: {} },
    "/api/me/": user,
    "/api/my-work/": { summary: {}, assigned_work: [], overdue: [], notifications: [], notebook_enabled: false },
    "/api/ui-settings/": { ui_language: "en", assistant_helper_enabled: false },
    "/api/import-jobs/42/": {
      id: 42, status: "COMPLETED", source_type: "UPLOAD", uploaded_file: "export.csv",
      summary: { csv_metadata: { fieldnames: ["reading"] } },
    },
    "/api/import-jobs/42/qc-runs/": {
      workflow: { filename: "export.csv", columns: ["reading"], default_reading_column: "reading" },
      runs: [{
        id: 1, filename: "export.csv", parameters: { reading_column: "reading" },
        summary: { outcome: "PASS", rows_checked: 1, invalid_readings: 0 },
      }],
    },
  };
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1/", "/api/");
    await route.fulfill({ json: responses[path] ?? [] });
  });
});

test("navigation hints appear on focus and hover and the Imports link still works", async ({ page }) => {
  await page.goto("/");
  const plan = page.getByRole("button", { name: "Plan", exact: true });
  await plan.click();
  const designer = page.getByRole("link", { name: "Workflow Designer", exact: true });
  await designer.focus();
  await expect(designer).toHaveAccessibleDescription("Build reusable workflow templates with ordered steps.");
  await expect(page.locator(".tooltip", { hasText: "Build reusable workflow templates with ordered steps." })).toBeVisible();
  await designer.press("Escape");
  await expect(designer).toBeHidden();

  await page.getByRole("button", { name: "Receive", exact: true }).click();
  const imports = page.getByRole("link", { name: "Imports", exact: true });
  await imports.hover();
  await expect(page.locator(".tooltip", { hasText: "Preview and import CSV or Excel results." })).toBeVisible();
  await imports.click();
  await expect(page).toHaveURL(/\/imports$/);
});

test("import terms expand with keyboard or pointer input", async ({ page }) => {
  await page.goto("/imports");
  const source = page.locator("summary").filter({ hasText: "About Source system" });
  const sourceExample = page.getByText(/Plate Reader A/);
  await expect(sourceExample).toBeHidden();
  await source.press("Enter");
  await expect(sourceExample).toBeVisible();
  await expect(page.getByLabel("Source system", { exact: true })).toHaveAccessibleDescription(
    "For safe retries, enter the source system and include an external_id column."
  );

  const externalId = page.locator("summary").filter({ hasText: "About External ID" });
  const idExample = page.getByText(/RUN-042-A01/);
  await expect(idExample).toBeHidden();
  await externalId.click();
  await expect(idExample).toBeVisible();
});

test("QC actions describe their effect and analysis opens column selection", async ({ page }) => {
  await page.goto("/imports/42");
  const run = page.getByRole("button", { name: "Run analysis", exact: true });
  const report = page.getByRole("button", { name: "Download QC report", exact: true });
  await expect(run).toHaveAccessibleDescription("Choose columns to check readings and, optionally, well coverage.");
  await expect(report).toHaveAccessibleDescription("Download a CSV of flagged rows and wells.");
  await run.click();
  await expect(page.getByLabel("Numeric reading column")).toHaveValue("reading");
});
