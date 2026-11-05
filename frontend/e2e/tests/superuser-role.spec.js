const { test, expect } = require("@playwright/test");

// Backend regressions exercise createsuperuser + cookie login with no groups.
// These fixtures exercise the effective-role response through the real UI.
async function setup(page, context, user, fallback = false) {
  const created = [];
  await context.addCookies([{ name: "csrftoken", value: "test-token", url: "http://127.0.0.1:5173" }]);
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1/", "/api/");
    let body = [];
    if (path === "/api/session/") {
      if (fallback) return route.fulfill({ status: 404, json: { detail: "Session unavailable" } });
      body = { user, feature_flags: {} };
    } else if (path === "/api/me/") body = user;
    else if (path === "/api/ui-settings/") body = { ui_language: "en", assistant_helper_enabled: false };
    else if (path === "/api/projects/") body = [{ id: 7, code: "PROTEIN-LAB", name: "Protein lab", members: [] }];
    else if (path === "/api/samples/") {
      if (route.request().method() === "POST") {
        created.push({ id: 12, ...route.request().postDataJSON() });
        return route.fulfill({ status: 201, json: created.at(-1) });
      }
      body = { count: created.length, next: null, previous: null, results: created };
    }
    await route.fulfill({ json: body });
  });
  return created;
}

for (const fallback of [false, true]) {
  test(`root superuser can create protein samples with ${fallback ? "me fallback" : "session bootstrap"}`, async ({ page, context }) => {
    const user = { id: 1, username: "root", roles: ["admin"], is_superuser: true, is_staff: true };
    const created = await setup(page, context, user, fallback);
    await page.goto("/samples");
    await expect(page.getByTestId("current-user-name")).toHaveText("root");
    await expect(page.getByTestId("current-user-roles")).toHaveText("admin");
    const form = page.locator("form").filter({ has: page.getByPlaceholder("New sample id, e.g. S-002") });
    await form.getByPlaceholder("New sample id, e.g. S-002").fill("PROTEIN-001");
    await form.getByPlaceholder("Sample type, e.g. DNA").fill("PROTEIN");
    await form.getByRole("combobox").filter({ has: page.locator('option[value="7"]') }).selectOption("7");
    await form.getByRole("button", { name: "Create", exact: true }).click();
    await expect(page.getByText("Sample created.", { exact: true })).toBeVisible();
    expect(created).toEqual([{ id: 12, sample_id: "PROTEIN-001", sample_type: "PROTEIN", project: 7, status: "RECEIVED", form_values: {} }]);
    await expect(page.getByRole("link", { name: "PROTEIN-001", exact: true })).toBeVisible();
    await page.goto("/projects");
    await expect(page.getByRole("heading", { name: "Create Project", exact: true })).toBeVisible();
    await page.getByPlaceholder("Project name", { exact: true }).fill("Protein experiments");
    await page.getByPlaceholder("Project code", { exact: true }).fill("NEW-PROTEIN");
    await expect(page.getByRole("button", { name: "Create Project", exact: true })).toBeEnabled();
    await page.goto("/me");
    await expect(page.getByText("Director / administrator", { exact: true })).toBeVisible();
    await expect(page.getByText("No assigned role", { exact: true })).toHaveCount(0);
  });
}

for (const user of [{ id: 2, username: "root", roles: [], is_superuser: false },
  { id: 3, username: "staff", roles: [], is_staff: true, is_superuser: false }]) {
  test(`${user.username} without an admin/tech role has no creation controls`, async ({ page, context }) => {
    const created = await setup(page, context, user);
    await page.goto("/samples");
    await expect(page.getByTestId("current-user-name")).toHaveText(user.username);
    await expect(page.getByTestId("current-user-roles")).toHaveText("No assigned role");
    await expect(page.getByText("Create Sample", { exact: true })).toHaveCount(0);
    await page.goto("/projects");
    await expect(page.getByRole("heading", { name: "Projects", exact: true })).toBeVisible();
    await expect(page.getByText("Create Project", { exact: true })).toHaveCount(0);
    expect(created).toEqual([]);
  });
}
