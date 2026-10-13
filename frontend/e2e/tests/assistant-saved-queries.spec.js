const { test, expect } = require("@playwright/test");

for (const surface of ["page", "widget"]) {
  test(`personal saved questions persist, load without running, and delete in ${surface}`, async ({ page, context }) => {
    const user = { id: 1, username: "director", roles: ["admin"] };
    let saved = [], chats = [], creates = [];
    await context.addCookies([{ name: "csrftoken", value: "test-token", url: "http://127.0.0.1:5173" }]);
    await page.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      let body = [], status = 200;
      if (path.endsWith("/session/")) body = { user, feature_flags: {} };
      else if (path.endsWith("/me/")) body = user;
      else if (path.endsWith("/ui-settings/")) body = { ui_language: "en" };
      else if (path.endsWith("/assistant/status/")) body = { provider: "openlims", suggestions: [] };
      else if (path.endsWith("/assistant/saved-queries/")) {
        if (route.request().method() === "POST") {
          const payload = route.request().postDataJSON();
          creates.push(payload);
          body = { id: 1, name: payload.name, query: { ...payload.query, assignee: "director" } };
          saved = [body]; status = 201;
        } else body = saved;
      } else if (path.endsWith("/assistant/saved-queries/1/")) {
        saved = []; return route.fulfill({ status: 204 });
      } else if (path.endsWith("/assistant/chat/")) {
        chats.push(route.request().postDataJSON());
        body = { answer: "Fresh results", context: {}, suggestions: [] };
      }
      await route.fulfill({ json: body, status });
    });
    async function openBuilder() {
      if (surface === "widget") await page.getByRole("button", { name: "Open OpenLIMS Assistant", exact: true }).click();
      const builder = page.locator(".workflow-query-builder");
      await builder.locator("summary").click();
      return builder;
    }
    await page.goto(surface === "page" ? "/assistant" : "/samples");
    let builder = await openBuilder();
    await builder.getByLabel("Project code", { exact: true }).fill("DEMO-360");
    await builder.getByRole("button", { name: "My overdue work", exact: true }).click();
    await builder.getByLabel("Name this question", { exact: true }).fill("Morning review");
    await builder.getByRole("button", { name: "Save builder settings", exact: true }).click();
    await expect(builder.getByRole("status")).toHaveText("Question saved to your account.");
    expect(creates).toHaveLength(1);
    expect(creates[0].query.filters).toEqual(["assigned", "overdue"]);
    expect(chats).toHaveLength(0);
    await page.reload();
    builder = await openBuilder();
    await builder.getByRole("combobox", { name: "Saved question", exact: true }).selectOption("1");
    await builder.getByRole("button", { name: "Load saved question", exact: true }).click();
    await expect(builder.getByLabel("Project code", { exact: true })).toHaveValue("DEMO-360");
    await expect(builder.getByLabel("Exact username or me", { exact: true })).toHaveValue("director");
    expect(chats).toHaveLength(0);
    await builder.getByRole("button", { name: "Run question", exact: true }).click();
    await expect.poll(() => chats.length).toBe(1);
    expect(chats[0].message).toBe("Which samples in project DEMO-360 are assigned to director and are overdue on the same step?");
    await builder.getByRole("button", { name: "Delete saved question", exact: true }).click();
    expect(saved).toHaveLength(1);
    await builder.getByRole("button", { name: "Confirm deletion", exact: true }).click();
    await expect(builder.getByRole("status")).toHaveText("Saved question deleted.");
    await expect.poll(() => saved.length).toBe(0);
    expect(chats).toHaveLength(1);
  });
}
