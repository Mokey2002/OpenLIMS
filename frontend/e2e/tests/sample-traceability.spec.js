const { test, expect } = require("@playwright/test");

async function mockRecord(page, { failHistory = false, empty = false } = {}) {
  const requests = [];
  const user = { id: 1, username: "reader", roles: ["viewer"] };
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/v1/", "/api/");
    requests.push(path);
    let body = [];
    if (path === "/api/session/") body = { user, feature_flags: { notebook: true } };
    if (path === "/api/me/") body = user;
    if (path === "/api/ui-settings/") body = { ui_language: "en", assistant_helper_enabled: false };
    if (path === "/api/samples/1/") body = { id: 1, public_id: "sample-public-id", sample_id: "TRACE-001", status: "RECEIVED", can_modify: false };
    if (path.endsWith("/allowed-transitions/")) body = { allowed_transitions: [] };
    if (path === "/api/samples/1/history/") {
      if (failHistory) return route.fulfill({ status: 503, json: { detail: "History temporarily unavailable" } });
      body = empty ? [] : url.searchParams.has("page")
        ? { count: 2, next: null, results: [{ id: 1, action: "CREATED", entity_type: "Sample", entity_id: "1", timestamp: "2026-09-01T10:00:00Z", payload: {} }] }
        : { count: 2, next: "/api/v1/samples/1/history/?page=2", results: [{ id: 2, action: "SHARED_ATTACHMENT_UPLOADED", entity_type: "sample", entity_id: "sample-public-id", timestamp: "2026-10-01T10:00:00Z", payload: {} }] };
    }
    if (!empty && path === "/api/samples/1/experiments/") body = [{ public_id: "experiment-id", title: "Plasmid extraction", notebook_name: "Lab notebook", status: "IN_PROGRESS", step_count: 3, completed_steps: 1 }];
    if (!empty && path === "/api/work-items/") body = url.searchParams.has("page")
      ? { count: 2, next: null, results: [{ id: 59, name: "DNA Extraction", status: "PENDING", qc_status: "APPROVED", results: [{ id: 100, key: "concentration", value_type: "NUMBER", value_number: 43 }] }] }
      : { count: 2, next: "/api/v1/work-items/?sample=1&page=2", results: [{ id: 58, name: "Receiving", status: "COMPLETED", results: [] }] };
    if (!empty && path === "/api/shared-attachments/") {
      expect(url.searchParams.get("target_type")).toBe("sample");
      expect(url.searchParams.get("target_public_id")).toBe("sample-public-id");
      body = [{ public_id: "file-id", display_name: "Extraction report.pdf", file: "/media/report.pdf", uploaded_by_username: "operator" }];
    }
    await route.fulfill({ json: body });
  });
  return requests;
}

test("sample joins experiments, paginated results, shared files and old/new history", async ({ page }) => {
  const requests = await mockRecord(page);
  await page.goto("/samples/1");
  await expect(page.getByRole("heading", { name: "TRACE-001" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Plasmid extraction" })).toHaveAttribute("href", "/notebook?experiment=experiment-id");
  await expect(page.getByText("1 / 3 steps complete")).toBeVisible();
  await expect(page.getByText("PENDING / APPROVED", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: "DNA Extraction", exact: true }).click();
  await expect(page).toHaveURL(/#work-item-59$/);
  await expect(page.getByRole("link", { name: "Extraction report.pdf" })).toHaveAttribute("href", "/media/report.pdf");
  await expect(page.getByRole("link", { name: "History (2)" })).toBeVisible();
  await expect(page.getByText("Sample created", { exact: true })).toBeVisible();
  await expect(page.getByText("OpenLIMS v0.36.0", { exact: false })).toBeVisible();
  expect(requests).not.toContain("/api/events/");
});

test("empty record explains how to link a saved experiment", async ({ page }) => {
  await mockRecord(page, { empty: true });
  await page.goto("/samples/1");
  await expect(page.getByText(/No accessible linked experiments/)).toBeVisible();
  await expect(page.getByText("No result values yet.")).toBeVisible();
  await expect(page.getByText("No attachments yet.")).toBeVisible();
});

test("failed history is not presented as an empty successful record", async ({ page }) => {
  await mockRecord(page, { failHistory: true });
  await page.goto("/samples/1");
  await expect(page.getByRole("alert").filter({ hasText: "503" })).toBeVisible();
  await expect(page.getByText("No timeline events yet.")).toHaveCount(0);
});
