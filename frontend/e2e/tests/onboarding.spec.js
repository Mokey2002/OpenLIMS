const { test, expect } = require("@playwright/test");

async function mockOnboarding(page, { enabled = true, empty = false, failCreate = false, language = "en" } = {}) {
  let experiment = null;
  const writes = [];
  const user = { id: 1, username: "scientist", roles: ["tech"] };
  await page.context().addCookies([{ name: "csrftoken", value: "test-csrf", url: "http://127.0.0.1:5173" }]);
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/v1/", "/api/");
    let body = [];
    if (path === "/api/session/") body = { user, feature_flags: { notebook: enabled } };
    if (path === "/api/me/") body = user;
    if (path === "/api/ui-settings/") body = { ui_language: language, assistant_helper_enabled: false };
    if (path === "/api/onboarding/") {
      if (route.request().method() === "POST") {
        writes.push(route.request().postDataJSON());
        if (failCreate) return route.fulfill({ status: 400, json: { detail: "Template unavailable" } });
        experiment = { public_id: "first-experiment", title: writes.at(-1).title, status: "IN_PROGRESS", can_write: true, steps: [{ position: 1, name: "Measure concentration", status: "PENDING" }] };
      }
      body = { enabled, experiment };
    }
    if (path === "/api/experiment-templates/") {
      expect(enabled).toBe(true);
      expect(url.searchParams.get("for_onboarding")).toBe("1");
      body = empty ? [] : [{ id: 4, name: "Our DNA workflow", notebook_name: "Lab notebook", description: "Our validated extraction", workflow_steps: [
        { name: "Measure concentration", instructions: "Use the lab instrument", completion_criteria: "At least 10 ng/µL", fields: [{ label: "Concentration", required: true }] },
      ] }];
    }
    await route.fulfill({ json: body });
  });
  return { writes, finish: () => { experiment.status = "COMPLETED"; experiment.steps[0].status = "COMPLETED"; } };
}

test("choose a real workflow, preview requirements, create once and resume progress", async ({ page }) => {
  const state = await mockOnboarding(page);
  await page.goto("/getting-started");
  await expect(page.getByRole("button", { name: "Create my first experiment" })).toBeDisabled();
  await page.getByLabel("Workflow template").selectOption("4");
  await expect(page.getByText("Fields: Concentration *")).toBeVisible();
  await expect(page.getByText("Completion criteria: At least 10 ng/µL")).toBeVisible();
  await page.getByLabel("Experiment title").fill("Muestra-001 extraction");
  await page.getByRole("button", { name: "Create my first experiment" }).click();
  await expect(page.getByRole("button", { name: "Open experiment", exact: true })).toHaveAttribute("href", "/notebook?experiment=first-experiment");
  expect(state.writes).toEqual([{ template: 4, title: "Muestra-001 extraction" }]);
  await page.reload();
  await expect(page.getByText("0 / 1 steps complete")).toBeVisible();
  await expect(page.getByLabel("Workflow template")).toHaveCount(0);
  state.finish();
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByRole("heading", { name: "First experiment completed" })).toBeVisible();
  await expect(page.getByText("1 / 1 steps complete")).toBeVisible();
  expect(state.writes).toHaveLength(1);
});

test("read-only or unconfigured lab has actionable next steps", async ({ page }) => {
  const state = await mockOnboarding(page, { empty: true });
  await page.goto("/getting-started");
  await expect(page.getByText(/No workflows are available for you yet/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Create my first experiment" })).toHaveCount(0);
  expect(state.writes).toHaveLength(0);
});

test("disabled notebook does not request templates", async ({ page }) => {
  await mockOnboarding(page, { enabled: false });
  await page.goto("/getting-started");
  await expect(page.getByText(/The notebook module is disabled/)).toBeVisible();
  await expect(page.getByLabel("Workflow template")).toHaveCount(0);
});

test("failed creation preserves input and offers recovery", async ({ page }) => {
  await mockOnboarding(page, { failCreate: true });
  await page.goto("/getting-started");
  await page.getByLabel("Workflow template").selectOption("4");
  await page.getByLabel("Experiment title").fill("My extraction");
  await page.getByRole("button", { name: "Create my first experiment" }).click();
  await expect(page.getByText(/Could not confirm experiment creation/)).toBeVisible();
  await expect(page.getByLabel("Experiment title")).toHaveValue("My extraction");
  await expect(page.getByRole("button", { name: "Create my first experiment" })).toBeEnabled();
});

test("Spanish onboarding uses the same lab workflow", async ({ page }) => {
  await mockOnboarding(page, { language: "es" });
  await page.goto("/getting-started");
  await expect(page.getByRole("heading", { name: "Primeros pasos", exact: true })).toBeVisible();
  await page.getByLabel("Plantilla del flujo").selectOption("4");
  await expect(page.getByText("Campos: Concentration *")).toBeVisible();
  await page.getByLabel("Título del experimento").fill("Extracción inicial");
  await expect(page.getByRole("button", { name: "Crear mi primer experimento" })).toBeEnabled();
});

test("administrator can see a failed invitation and resend without losing setup status", async ({ page }) => {
  const user = { id: 1, username: "admin", roles: ["admin"] };
  let event = "USER_INVITATION_FAILED";
  let sends = 0;
  await page.context().addCookies([{ name: "csrftoken", value: "test-csrf", url: "http://127.0.0.1:5173" }]);
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1/", "/api/");
    let body = [];
    if (path === "/api/session/") body = { user, feature_flags: {} };
    if (path === "/api/me/") body = user;
    if (path === "/api/ui-settings/") body = { ui_language: "en", assistant_helper_enabled: false };
    if (path === "/api/admin-users/") body = [{ id: 2, username: "new-scientist", email: "scientist@example.org", roles: ["tech"], is_active: true, password_ready: false, invitation_event: event }];
    if (path === "/api/admin-users/2/invite/") { sends++; event = "USER_INVITATION_SENT"; body = { invitation_status: "sent" }; }
    await route.fulfill({ json: body });
  });
  await page.goto("/users");
  await expect(page.getByText("Invitation email failed — resend needed")).toBeVisible();
  await page.getByRole("button", { name: "Send invitation", exact: true }).click();
  await expect(page.getByText("Invitation submitted to email service")).toBeVisible();
  await expect(page.getByText("Password setup pending")).toBeVisible();
  await page.reload();
  await expect(page.getByText("Invitation submitted to email service")).toBeVisible();
  expect(sends).toBe(1);
});
