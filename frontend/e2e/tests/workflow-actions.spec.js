const { test, expect } = require("@playwright/test");

// Mock only the API: exercise the real designer, save payload, and edit roundtrip.
test("director configures activation actions and reloads them for editing", async ({ page, context }) => {
  const user = { id: 1, username: "director", roles: ["admin"] };
  let templates = [], saved;
  await context.addCookies([{ name: "csrftoken", value: "test-token", url: "http://127.0.0.1:5173" }]);
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let body = [];
    if (path.endsWith("/session/")) body = { user, feature_flags: {} };
    else if (path.endsWith("/me/")) body = user;
    else if (path.endsWith("/ui-settings/")) body = { ui_language: "en" };
    else if (path.endsWith("/action-users/")) body = [{ ...user, can_assign: true }, { id: 2, username: "maria", can_assign: true }];
    else if (path.endsWith("/procedure-definitions/")) body = [{ id: 1, code: "EXT", name: "Extraction", version: "1", active: true }];
    else if (path.endsWith("/pipeline-templates/")) {
      if (route.request().method() === "POST") {
        saved = route.request().postDataJSON();
        templates = [{ ...saved, id: 1, steps: saved.steps.map((s, i) => ({ ...s, id: i + 1, display_name: "Extraction" })) }];
        body = templates[0];
      } else body = templates;
    }
    await route.fulfill({ json: body });
  });
  await page.goto("/workflow-designer");
  const form = page.locator("form").filter({ has: page.getByRole("button", { name: "Create pipeline", exact: true }) });
  await form.locator('input[placeholder="DNA-WORKFLOW"]').fill("FLOW");
  await form.locator("input[required]").nth(1).fill("Flow");
  await form.locator("select[required]").selectOption("1");
  await page.getByLabel("Assign work to", { exact: true }).selectOption("2");
  await page.getByLabel("Notify the assignee in the app", { exact: true }).check();
  await page.getByLabel("Additional in-app recipients", { exact: true }).selectOption(["1", "2"]);
  await page.getByRole("button", { name: "Create pipeline", exact: true }).click();
  await expect.poll(() => saved?.steps[0].automation).toEqual({ assigned_to: 2, notify_assignee: true, notify_users: [1, 2] });
  const pipelineCard = page.locator(".feed-item").filter({ has: page.getByText("FLOW — Flow", { exact: true }) });
  await pipelineCard.getByRole("button", { name: "Edit", exact: true }).click();
  await expect(page.getByLabel("Assign work to", { exact: true })).toHaveValue("2");
  await expect(page.getByLabel("Notify the assignee in the app", { exact: true })).toBeChecked();
  await expect(page.getByLabel("Additional in-app recipients", { exact: true })).toHaveValues(["1", "2"]);
  await page.getByLabel("Assign work to", { exact: true }).selectOption("");
  await expect(page.getByLabel("Notify the assignee in the app", { exact: true })).not.toBeChecked();
  await expect(page.getByLabel("Notify the assignee in the app", { exact: true })).toBeDisabled();
});
