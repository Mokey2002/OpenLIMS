const { test, expect } = require("@playwright/test");

async function mockNavigation(page) {
  const user = { id: 1, username: "scientist", roles: ["tech"] };
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1/", "/api/");
    let body = [];
    if (path === "/api/session/") body = { user, feature_flags: {} };
    else if (path === "/api/me/") body = user;
    else if (path === "/api/ui-settings/") body = { ui_language: "en", assistant_helper_enabled: false };
    else if (path === "/api/my-work/") body = { summary: {}, assigned_work: [], overdue: [], notifications: [], notebook_enabled: false };
    else if (path === "/api/projects/") body = [{ id: 1, name: "Navigation project", code: "NAV", members: [] }];
    await route.fulfill({ json: body });
  });
}

async function openProjects(page) {
  await page.getByRole("button", { name: "Plan", exact: true }).click();
  await page.getByRole("link", { name: "Projects", exact: true }).click();
}

const projectModule = /\/(?:src\/pages\/Projects\.jsx|assets\/Projects-[^/]+\.js)(?:\?.*)?$/;

test("navigation from My Work shows the next page without a document reload", async ({ page }) => {
  await mockNavigation(page);
  let documents = 0;
  page.on("request", request => { if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents++; });
  await page.goto("/");
  await openProjects(page);
  await expect(page.getByText("Navigation project", { exact: true })).toBeVisible();
  expect(documents).toBe(1);
});

test("missing lazy page recovers automatically at the selected destination", async ({ page }) => {
  await mockNavigation(page);
  let requests = 0;
  await page.route(projectModule, async route => {
    requests++;
    if (requests === 1) return route.fulfill({ status: 404, contentType: "text/plain", body: "Old deployment file removed" });
    await route.continue();
  });
  await page.goto("/");
  await openProjects(page);
  await expect(page.getByText("Navigation project", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/\/projects$/);
  expect(requests).toBe(2);
});

test("persistent module failure stops reloading and keeps navigation available", async ({ page }) => {
  await mockNavigation(page);
  let requests = 0;
  await page.route(projectModule, route => { requests++; return route.fulfill({ status: 404, contentType: "text/plain", body: "Unavailable" }); });
  await page.goto("/");
  await openProjects(page);
  await expect(page.getByRole("alert")).toContainText("This page could not be loaded");
  expect(requests).toBe(2);
  await page.getByRole("link", { name: "Return to My Work", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("button", { name: "Plan", exact: true })).toBeVisible();
});
