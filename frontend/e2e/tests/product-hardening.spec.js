const { test, expect } = require("@playwright/test");

async function loginAsDirector(page, context) {
  await page.goto("/login");
  await page.getByLabel("Username").fill("director");
  await page.getByLabel("Password").fill("Director123!");

  const loginResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("/api/v1/auth/login/") &&
      response.request().method() === "POST"
  );

  await page.getByRole("button", { name: "Sign in" }).click();
  const loginResponse = await loginResponsePromise;

  if (!loginResponse.ok()) {
    const cookies = await context.cookies();
    const requestHeaders = await loginResponse.request().allHeaders();
    const responseBody = await loginResponse.text();
    const hasCsrfCookie = cookies.some((cookie) => cookie.name === "csrftoken");
    const hasCsrfHeader = Boolean(requestHeaders["x-csrftoken"]);

    throw new Error(
      `Login failed with HTTP ${loginResponse.status()}; ` +
        `csrfCookie=${hasCsrfCookie}; csrfHeader=${hasCsrfHeader}; ` +
        `response=${responseBody}`
    );
  }

  await expect(page.getByRole("heading", { name: "My Work" })).toBeVisible();
}

test("browser session uses HttpOnly cookies and no stored JWTs", async ({ page, context }) => {
  const apiRequests = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/")) apiRequests.push(url.pathname);
  });

  await loginAsDirector(page, context);

  await expect(page.getByTestId("current-user-name")).toHaveText("director");
  await expect(page.getByTestId("current-user-roles")).toContainText("admin");

  const storage = await page.evaluate(() => ({
    local: Object.keys(localStorage),
    session: Object.keys(sessionStorage),
  }));
  const tokenKey = /(access|refresh|token)/i;
  expect(storage.local.filter((key) => tokenKey.test(key))).toEqual([]);
  expect(storage.session.filter((key) => tokenKey.test(key))).toEqual([]);

  const cookies = await context.cookies();
  const access = cookies.find((cookie) => cookie.name === "openlims_access");
  const refresh = cookies.find((cookie) => cookie.name === "openlims_refresh");
  expect(access).toBeTruthy();
  expect(refresh).toBeTruthy();
  expect(access.httpOnly).toBe(true);
  expect(refresh.httpOnly).toBe(true);

  await page.reload();
  await expect(page.getByTestId("my-work-page")).toBeVisible();

  const nonVersionedBusinessRequests = apiRequests.filter(
    (path) => !path.startsWith("/api/v1/") && !["/api/health/", "/api/schema/", "/api/docs/"].includes(path)
  );
  expect(nonVersionedBusinessRequests).toEqual([]);
});

test("authenticated header falls back to me when session bootstrap is unavailable", async ({ page, context }) => {
  await page.route("**/api/v1/session/", async (route) => {
    await route.fulfill({
      status: 404,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Not found" }),
    });
  });

  await loginAsDirector(page, context);

  await expect(page.getByTestId("current-user-name")).toHaveText("director");
  await expect(page.getByTestId("current-user-roles")).toContainText("admin");
  await expect(page.getByText("Unknown", { exact: true })).toHaveCount(0);
  await expect(page.getByText("No role", { exact: true })).toHaveCount(0);
});

test("Notebook works when crypto.randomUUID is unavailable", async ({ page, context }) => {
  await page.addInitScript(() => {
    try {
      Object.defineProperty(globalThis.crypto, "randomUUID", {
        configurable: true,
        value: undefined,
      });
    } catch {
      // The compatibility helper is still exercised in browsers that allow this override.
    }
  });

  await loginAsDirector(page, context);
  expect(await page.evaluate(() => typeof globalThis.crypto?.randomUUID)).toBe("function");

  await page.goto("/notebook");
  await expect(page.getByRole("heading", { name: "Laboratory Notebook" })).toBeVisible();
});

test("Notebook defers large provenance catalogs during initial load", async ({ page, context }) => {
  await loginAsDirector(page, context);
  const notebookRequests = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname.startsWith("/api/v1/")) notebookRequests.push(url);
  });

  await page.goto("/notebook");
  await expect(page.getByRole("heading", { name: "Laboratory Notebook" })).toBeVisible();

  expect(notebookRequests.some(
    (url) => url.pathname === "/api/v1/experiments/" && url.searchParams.get("summary") === "1"
  )).toBe(true);
  const deferredPaths = new Set([
    "/api/v1/registry-records/", "/api/v1/samples/", "/api/v1/inventory-lots/",
    "/api/v1/pipeline-runs/", "/api/v1/work-items/", "/api/v1/results/",
    "/api/v1/sop-documents/", "/api/v1/sequences/",
  ]);
  expect(notebookRequests.filter((url) => deferredPaths.has(url.pathname))).toEqual([]);
});

test("workflow navigation is cohesive and logout invalidates the browser session", async ({ page, context }) => {
  await loginAsDirector(page, context);

  const nav = page.getByTestId("workflow-navigation");
  await expect(nav.getByText("Plan", { exact: true })).toBeVisible();
  await expect(nav.getByText("Receive", { exact: true })).toBeVisible();
  await expect(nav.getByText("Execute", { exact: true })).toBeVisible();
  await expect(nav.getByText("Review", { exact: true })).toBeVisible();
  await expect(nav.getByText("Report", { exact: true })).toBeVisible();

  await page.getByText("Plan", { exact: true }).click();
  await expect(page.getByRole("link", { name: "Projects" })).toHaveAttribute("href", "/projects");

  await page.getByText("Receive", { exact: true }).click();
  await expect(page.getByRole("link", { name: "Samples", exact: true })).toHaveAttribute("href", "/samples");

  await page.getByText("Execute", { exact: true }).click();
  await expect(page.getByRole("link", { name: "Work Queue" })).toHaveAttribute("href", "/work-queue");

  await page.getByText("Review", { exact: true }).click();
  await expect(page.getByRole("link", { name: "Result QC" })).toHaveAttribute("href", "/qc-review");

  await page.getByText("Report", { exact: true }).click();
  await expect(page.getByRole("link", { name: "Reports" })).toHaveAttribute("href", "/reports");

  await page.getByRole("button", { name: "Logout" }).click();
  await expect(page).toHaveURL(/\/login$/);

  const cookies = await context.cookies();
  expect(cookies.some((cookie) => cookie.name === "openlims_access")).toBe(false);
  expect(cookies.some((cookie) => cookie.name === "openlims_refresh")).toBe(false);
});
