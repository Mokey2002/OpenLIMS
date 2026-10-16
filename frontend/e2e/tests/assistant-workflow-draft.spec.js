const { test, expect } = require("@playwright/test");

for (const surface of ["page", "widget"]) {
  test(`assistant workflow requires review and explicit save from ${surface}`, async ({ page, context }) => {
    const user = { id: 1, username: "director", roles: ["admin"] };
    const writes = [];
    await context.addCookies([{ name: "csrftoken", value: "test-token", url: "http://127.0.0.1:5173" }]);
    await page.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      let body = [];
      if (path.endsWith("/session/")) body = { user, feature_flags: {} };
      else if (path.endsWith("/me/")) body = user;
      else if (path.endsWith("/ui-settings/")) body = { ui_language: "en" };
      else if (path.endsWith("/assistant/status/")) body = { provider: "openlims", suggestions: [] };
      else if (path.endsWith("/assistant/chat/")) body = {
        answer: "Review your draft", suggestions: [], context: {},
        draft: { text: "Extraction draft", workflow: { steps: [{ procedure: 1, code: "EX", version: "1" }] } },
      };
      else if (path.endsWith("/procedure-definitions/")) body = [{ id: 1, code: "EX", version: "1", name: "Extraction", active: true }];
      else if (path.endsWith("/pipeline-templates/") && route.request().method() === "POST") {
        writes.push(route.request().postDataJSON());
        body = { id: 1, code: writes[0].code };
      }
      await route.fulfill({ json: body });
    });
    await page.goto(surface === "page" ? "/assistant" : "/samples");
    if (surface === "widget") await page.getByRole("button", { name: "Open OpenLIMS Assistant", exact: true }).click();
    await page.getByPlaceholder(surface === "page" ? "Compare samples or projects, graph results, find outliers..." : "Ask OpenLIMS...").fill("Create a workflow with EX@1");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await page.getByRole("button", { name: /Review workflow in designer/ }).click();
    await expect(page).toHaveURL(/workflow-designer/);
    await expect(page.getByPlaceholder("Optional step name")).toHaveValue("Extraction");
    await expect(page.getByLabel("Active pipeline", { exact: true })).not.toBeChecked();
    expect(writes).toHaveLength(0);
    const form = page.getByPlaceholder("DNA-WORKFLOW").locator("xpath=ancestor::form");
    await page.getByPlaceholder("DNA-WORKFLOW").fill("DRAFT");
    await form.locator("input").nth(1).fill("Reviewed workflow");
    await page.getByRole("button", { name: "Create pipeline", exact: true }).click();
    await expect.poll(() => writes.length).toBe(1);
    expect(writes[0].active).toBe(false);
    expect(writes[0].steps[0].procedure).toBe(1);
    expect(writes[0].steps[0].dependency_positions).toEqual([]);
    expect(writes[0].steps[0].requires_qc).toBe(false);
    await expect(page.getByPlaceholder("Optional step name")).toHaveValue("");
  });
}
