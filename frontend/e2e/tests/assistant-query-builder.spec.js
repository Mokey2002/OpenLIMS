const { test, expect } = require("@playwright/test");

for (const surface of ["page", "widget"]) {
  test(`workflow builder previews and submits explicit questions in ${surface}`, async ({ page, context }) => {
    const user = { id: 1, username: "director", roles: ["admin"] };
    const sent = [];
    await context.addCookies([{ name: "csrftoken", value: "test-token", url: "http://127.0.0.1:5173" }]);
    await page.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      let body = [];
      if (path.endsWith("/session/")) body = { user, feature_flags: {} };
      else if (path.endsWith("/me/")) body = user;
      else if (path.endsWith("/ui-settings/")) body = { ui_language: "en" };
      else if (path.endsWith("/assistant/status/")) body = { provider: "openlims", suggestions: [] };
      else if (path.endsWith("/assistant/chat/")) {
        sent.push(route.request().postDataJSON());
        body = { answer: "Current results", context: { project_workflows: { project_code: "DEMO-360", filters: ["assigned", "overdue"], match: "all", scope: "step", assignee: "director", language: "en" } }, suggestions: [] };
      }
      await route.fulfill({ json: body });
    });
    await page.goto(surface === "page" ? "/assistant" : "/samples");
    if (surface === "widget") await page.getByRole("button", { name: "Open OpenLIMS Assistant", exact: true }).click();
    const builder = page.locator(".workflow-query-builder");
    await builder.locator("summary").click();
    await expect(builder.getByRole("button", { name: "Run question", exact: true })).toBeDisabled();
    await builder.getByLabel("Project code", { exact: true }).fill("DEMO-360");
    await builder.getByRole("button", { name: "My overdue work", exact: true }).click();
    await expect(builder.getByRole("combobox", { name: "Scope", exact: true })).toHaveValue("step");
    await expect(builder.getByText("Which samples in project DEMO-360 are assigned to me and are overdue on the same step?", { exact: true })).toBeVisible();
    expect(sent).toHaveLength(0);
    await builder.getByRole("button", { name: "Run question", exact: true }).click();
    await expect.poll(() => sent.length).toBe(1);
    expect(sent[0].message).toBe("Which samples in project DEMO-360 are assigned to me and are overdue on the same step?");
    await builder.getByRole("button", { name: "Load current query", exact: true }).click();
    await expect(builder.getByLabel("Exact username or me", { exact: true })).toHaveValue("director");
    await builder.getByRole("combobox", { name: "Language", exact: true }).selectOption("es");
    await builder.getByRole("button", { name: "Próximo a vencer, sin asignar", exact: true }).click();
    await builder.getByLabel("Código del proyecto", { exact: true }).fill("SECOND");
    await builder.getByRole("button", { name: "Ejecutar consulta", exact: true }).click();
    await expect.poll(() => sent.length).toBe(2);
    expect(sent[1].message).toBe("¿Qué muestras en proyecto SECOND están sin asignar y vencen en los próximos 7 días en el mismo paso?");
  });
}
