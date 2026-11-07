const { test, expect } = require("@playwright/test");
const { readFile } = require("node:fs/promises");

async function setup(page, context) {
  const state = { language: "en", refreshes: 0, downloads: [], expireExports: false, expired: new Set() };
  const user = { id: 1, username: "director", roles: ["admin"] };
  await context.addCookies([{ name: "csrftoken", value: "test-csrf", url: "http://127.0.0.1:5173" }]);
  await page.route("**/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/v1/", "/api/");
    let body = [];
    if (path === "/api/auth/refresh/") {
      state.refreshes++;
      expect(request.headers()["x-csrftoken"]).toBe("test-csrf");
      body = { detail: "Refreshed" };
    } else if (path === "/api/auth/login/" || path === "/api/me/") body = user;
    else if (path === "/api/session/") body = { user, feature_flags: {} };
    else if (path === "/api/ui-settings/") body = { ui_language: state.language, assistant_helper_enabled: false };
    else if (path === "/api/my-work/") body = { summary: {}, assigned_work: [], overdue: [], notifications: [], notebook_enabled: false };
    else if (path === "/api/migration-jobs/1/") body = { id: 1, status: "COMPLETED", profile: 1, summary: {} };
    else if (path === "/api/migration-jobs/1/reconciliation/") body = {};
    else if (/\/export-(rows|reconciliation)\/$/.test(path)) {
      state.downloads.push({ path, query: url.search, authorization: request.headers().authorization, versioned: url.pathname.startsWith("/api/v1/") });
      if (state.expireExports && !state.expired.has(path)) {
        state.expired.add(path);
        return route.fulfill({ status: 401, json: { detail: "Token expired" } });
      }
      return route.fulfill({
        contentType: "text/csv",
        headers: { "Content-Disposition": state.disposition || 'attachment; filename="migration-report.csv"' },
        body: "row,status\n1,IMPORTED\n",
      });
    }
    await route.fulfill({ json: body });
  });
  return state;
}

for (const denied of ["localStorage", "sessionStorage", "removal", "writes"]) {
  test(`login, logout and server language settings work with blocked storage: ${denied}`, async ({ page, context }) => {
    const state = await setup(page, context);
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.addInitScript(mode => {
      const blocked = () => { throw new DOMException("Storage is unavailable", "SecurityError"); };
      if (mode === "removal") Storage.prototype.removeItem = blocked;
      else if (mode === "writes") Storage.prototype.setItem = blocked;
      else Object.defineProperty(window, mode, { configurable: true, get: blocked });
    }, denied);
    await page.goto("/login");
    await page.locator("#openlims-username").fill("director");
    await page.locator("#openlims-password").fill("test-password");
    await page.locator('button[type="submit"]').click();
    await expect(page.getByTestId("current-user-name")).toHaveText("director");
    await page.getByRole("button", { name: "Logout", exact: true }).click();
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.locator("#openlims-username")).toBeVisible();
    state.language = "es";
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("lang", "es");
    await expect(page.locator("#openlims-username")).toBeVisible();
    expect(errors).toEqual([]);
  });
}

test("migration row and reconciliation exports refresh expired cookies and retain filters", async ({ page, context }) => {
  const state = await setup(page, context);
  state.expireExports = true;
  await page.goto("/data-migration/jobs/1");
  await expect(page.getByRole("heading", { name: "Migration Job #1", exact: true })).toBeVisible();
  await page.getByPlaceholder("Search project code, sample ID, or raw row text").fill("S-100");
  for (const [button, expectedPath] of [
    ["Export Errors", "/api/migration-jobs/1/export-rows/"],
    ["Export Reconciliation", "/api/migration-jobs/1/export-reconciliation/"],
  ]) {
    const pending = page.waitForEvent("download", { timeout: 10_000 });
    await page.getByRole("button", { name: button, exact: true }).click();
    const download = await pending;
    expect(await download.failure()).toBeNull();
    expect(await readFile(await download.path(), "utf8")).toBe("row,status\n1,IMPORTED\n");
    const requests = state.downloads.filter(item => item.path === expectedPath);
    expect(requests).toHaveLength(2);
    expect(requests.every(item => item.versioned && item.authorization === undefined)).toBe(true);
    if (button === "Export Errors") {
      for (const request of requests) {
        const query = new URLSearchParams(request.query);
        expect(query.get("status")).toBe("ERROR");
        expect(query.get("search")).toBe("S-100");
      }
    }
  }
  expect(state.refreshes).toBe(2);
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("CSV export downloads keep percent signs, semicolons and extended UTF-8 names", async ({ page, context }) => {
  const state = await setup(page, context);
  await page.goto("/data-migration/jobs/1");
  for (const [disposition, filename] of [
    ['attachment; filename="100% recovery; final.csv"', "100% recovery; final.csv"],
    ["attachment; filename=legacy.csv; filename*=UTF-8''an%C3%A1lisis.csv", "análisis.csv"],
    ["attachment; filename=usable.csv; filename*=UTF-8''invalid%ZZ.csv", "usable.csv"],
  ]) {
    state.disposition = disposition;
    const pending = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export Rows", exact: true }).click();
    const download = await pending;
    expect(download.suggestedFilename()).toBe(filename);
    expect(await download.failure()).toBeNull();
    expect(await readFile(await download.path(), "utf8")).toContain("1,IMPORTED");
  }
});
