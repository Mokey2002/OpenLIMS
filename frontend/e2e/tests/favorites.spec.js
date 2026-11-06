const { test, expect } = require("@playwright/test");

test.setTimeout(90_000);
const accounts = {
  director: { id: 1, username: "director", roles: ["admin"] },
  peter: { id: 2, username: "peter", roles: ["tech"] },
};

async function setup(page, context, options = {}) {
  const state = { user: accounts.director, ...options };
  await context.addCookies([{ name: "csrftoken", value: "test-csrf", url: "http://127.0.0.1:5173" }]);
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1/", "/api/");
    let body = [];
    if (path === "/api/auth/login/") {
      state.user = accounts[route.request().postDataJSON().username];
      body = { user: state.user };
    } else if (path === "/api/auth/logout/") {
      state.user = null; body = { detail: "Logged out" };
    } else if (path === "/api/session/") {
      if (state.gate) await state.gate;
      if (state.fallback || state.unavailable) return route.fulfill({ status: 404, json: { detail: "Unavailable" } });
      body = { user: state.user, feature_flags: {} };
    } else if (path === "/api/me/") {
      if (state.unavailable) return route.fulfill({ status: 503, json: { detail: "Unavailable" } });
      body = state.user;
    } else if (path === "/api/ui-settings/") body = { ui_language: "en", assistant_helper_enabled: false };
    else if (path === "/api/my-work/") body = { summary: {}, assigned_work: [], overdue: [], notifications: [], notebook_enabled: false };
    else if (path === "/api/feature-flags/") body = {};
    await route.fulfill({ json: body });
  });
  return state;
}

async function signIn(page, username) {
  await page.getByLabel("Username", { exact: true }).fill(username);
  await page.getByLabel("Password", { exact: true }).fill("test-password");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByTestId("current-user-name")).toHaveText(username);
}

async function switchUser(page, username) {
  await page.getByRole("button", { name: "Logout", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await signIn(page, username);
}

async function openFavorites(page) {
  await page.locator("#favorites-nav").click();
  return page.locator("#favorites-nav").locator("..");
}

async function pin(page) {
  const menu = await openFavorites(page);
  await menu.getByText("☆ Pin current page", { exact: true }).click();
}

test("favorites belong to the account across logout, login, reload and unpin", async ({ page, context }) => {
  await setup(page, context);
  await page.goto("/projects");
  await expect(page.getByTestId("current-user-name")).toHaveText("director");
  await pin(page);
  await expect(page.locator("#favorites-nav")).toHaveText("Favorites (1)");

  await switchUser(page, "peter");
  let menu = await openFavorites(page);
  await expect(menu.getByText("No favorites pinned", { exact: true })).toBeVisible();
  await expect(menu.getByRole("link", { name: "Projects", exact: true })).toHaveCount(0);
  await page.locator("#favorites-nav").click();
  await page.goto("/samples");
  await expect(page.getByTestId("current-user-name")).toHaveText("peter");
  await pin(page);
  await page.reload();
  await expect(page.getByTestId("current-user-name")).toHaveText("peter");
  menu = await openFavorites(page);
  await expect(menu.getByRole("link", { name: "Samples", exact: true })).toBeVisible();
  await expect(menu.getByRole("link", { name: "Projects", exact: true })).toHaveCount(0);
  await page.locator("#favorites-nav").click();

  await switchUser(page, "director");
  menu = await openFavorites(page);
  await expect(menu.getByRole("link", { name: "Projects", exact: true })).toBeVisible();
  await expect(menu.getByRole("link", { name: "Samples", exact: true })).toHaveCount(0);
  await menu.getByRole("link", { name: "Projects", exact: true }).click();
  menu = await openFavorites(page);
  await menu.getByText("★ Unpin current page", { exact: true }).click();
  await switchUser(page, "peter");
  menu = await openFavorites(page);
  await expect(menu.getByRole("link", { name: "Samples", exact: true })).toBeVisible();
  await expect(menu.getByRole("link", { name: "Projects", exact: true })).toHaveCount(0);
});

test("legacy pins are ignored and fallback identity loads only its sanitized, permitted pins", async ({ page, context }) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await setup(page, context, { user: accounts.peter, fallback: true });
  await page.addInitScript(() => {
    localStorage.setItem("openlims_favorites", '["/inventory"]');
    localStorage.setItem("openlims_favorites:user:1", '["/samples"]');
    localStorage.setItem("openlims_favorites:user:2", '["/projects",{},"__proto__","/unknown","/projects","/users","/registry"]');
  });
  await page.goto("/projects");
  await expect(page.getByTestId("current-user-name")).toHaveText("peter");
  const menu = await openFavorites(page);
  await expect(menu.getByRole("link", { name: "Projects", exact: true })).toBeVisible();
  for (const name of ["Samples", "Inventory", "Users", "Biological Registry"]) {
    await expect(menu.getByRole("link", { name, exact: true })).toHaveCount(0);
  }
  await expect(page.locator("#favorites-nav")).toHaveText("Favorites (1)");
  expect(await page.evaluate(() => localStorage.getItem("openlims_favorites"))).toBe('["/inventory"]');
  expect(errors).toEqual([]);
});

test("pins are unavailable until the account is identified", async ({ page, context }) => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  await setup(page, context, { gate });
  await page.addInitScript(() => {
    localStorage.setItem("openlims_favorites", '["/inventory"]');
    localStorage.setItem("openlims_favorites:user:1", '["/projects"]');
  });
  await page.goto("/samples");
  try {
    await expect(page.locator("#favorites-nav")).toHaveText("Favorites");
    await expect(page.locator("#favorites-nav")).toBeDisabled();
  } finally {
    release();
  }
  await expect(page.getByTestId("current-user-name")).toHaveText("director");
  const menu = await openFavorites(page);
  await expect(menu.getByRole("link", { name: "Projects", exact: true })).toBeVisible();
  await expect(menu.getByRole("link", { name: "Inventory", exact: true })).toHaveCount(0);
});

test("identity failures do not expose or modify any favorites", async ({ page, context }) => {
  await setup(page, context, { unavailable: true });
  await page.addInitScript(() => {
    localStorage.setItem("openlims_favorites", '["/inventory"]');
    localStorage.setItem("openlims_favorites:user:1", '["/projects"]');
  });
  await page.goto("/samples");
  await expect(page.getByTestId("current-user-name")).toHaveText("Account unavailable");
  await expect(page.locator("#favorites-nav")).toHaveText("Favorites");
  await expect(page.locator("#favorites-nav")).toBeDisabled();
  expect(await page.evaluate(() => localStorage.getItem("openlims_favorites:user:1"))).toBe('["/projects"]');
  expect(await page.evaluate(() => localStorage.getItem("openlims_favorites"))).toBe('["/inventory"]');
});

test("failed storage writes keep the menu usable and explain that the pin was not saved", async ({ page, context }) => {
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await setup(page, context);
  await page.addInitScript(() => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key.startsWith("openlims_favorites:user:")) throw new DOMException("Storage is full", "QuotaExceededError");
      return original.call(this, key, value);
    };
  });
  await page.goto("/projects");
  await expect(page.getByTestId("current-user-name")).toHaveText("director");
  await pin(page);
  const menu = await openFavorites(page);
  await expect(menu.getByRole("link", { name: "Projects", exact: true })).toBeVisible();
  await expect(menu.getByRole("status")).toContainText("Favorites could not be saved in this browser.");
  expect(await page.evaluate(() => localStorage.getItem("openlims_favorites:user:1"))).toBeNull();
  expect(errors).toEqual([]);
});

test("other tabs update only the currently identified account's favorites", async ({ page, context }) => {
  await setup(page, context);
  await page.goto("/projects");
  await expect(page.getByTestId("current-user-name")).toHaveText("director");
  const other = await context.newPage();
  // A same-origin document supplies real browser storage events without a second app session.
  await other.route("**/favorites-storage-fixture", route => route.fulfill({ contentType: "text/html", body: "Storage fixture" }));
  await other.goto("/favorites-storage-fixture");
  await other.evaluate(() => {
    localStorage.setItem("openlims_favorites", '["/samples"]');
    localStorage.setItem("openlims_favorites:user:2", '["/samples"]');
    localStorage.setItem("openlims_favorites:user:1", '["/inventory"]');
  });
  await expect(page.locator("#favorites-nav")).toHaveText("Favorites (1)");
  const menu = await openFavorites(page);
  await expect(menu.getByRole("link", { name: "Inventory", exact: true })).toBeVisible();
  await expect(menu.getByRole("link", { name: "Samples", exact: true })).toHaveCount(0);
  await other.evaluate(() => localStorage.removeItem("openlims_favorites:user:1"));
  await expect(menu.getByText("No favorites pinned", { exact: true })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("openlims_favorites:user:2"))).toBe('["/samples"]');
  await other.close();
});
