const { test, expect } = require("@playwright/test");

for (const surface of ["page", "widget"]) {
  test(`comparison focus preserves query context and displays actual differences in ${surface}`, async ({ page, context }) => {
    const user = { id: 1, username: "technician", roles: ["tech"] };
    const requests = [];
    const filters = { qc: "failed", period: "yesterday", compare_period: "this_week", operator: "alice" };
    await context.addCookies([{ name: "csrftoken", value: "test-token", url: "http://127.0.0.1:5173" }]);
    await page.route("**/api/**", async route => {
      const path = new URL(route.request().url()).pathname;
      let body = [];
      if (path.endsWith("/session/")) body = { user, feature_flags: {} };
      else if (path.endsWith("/me/")) body = user;
      else if (path.endsWith("/ui-settings/")) body = { ui_language: "en" };
      else if (path.endsWith("/assistant/status/")) body = { provider: "openlims", suggestions: [] };
      else if (path.endsWith("/assistant/chat/")) {
        const payload = route.request().postDataJSON();
        requests.push(payload);
        const focus = { "Explain failure-rate differences": "qc_rates", "Explain numeric differences": "numeric", "Explain count differences": "counts" }[payload.message] || "overview";
        const text = {
          overview: "Comparison overview: result counts, assessed-check rates and compatible measurements.",
          qc_rates: "Selected 50.00% (2/4 failed/assessed), comparison 20.00% (1/5 failed/assessed); increase of 30.00 percentage points.",
          numeric: "Selected mean 15 ng/µL (n=2), comparison mean 10 ng/µL (n=1); difference 5 ng/µL.",
          counts: "Largest count difference: concentration, 2 versus 1 (+1)."
        }[focus];
        if (payload.message === "Clear comparison filter") delete filters.compare_period;
        body = { answer: text, answer_overview: { text }, context: { read_plan_memory: `signed-${requests.length}`,
          result_query_context: { kind: "project", target: "ALPHA", filters: { ...filters }, focus } },
          citations: [{ kind: "project", label: "ALPHA · comparison aggregate scope", url: "/projects/1", scope: "Aggregates use all currently accessible matching records, not just displayed examples." }],
          read_plan: { steps: [{ operation: "project_results_compare", status: "completed", answer: text,
            statistics_tables: [{ title: "Numeric results in compatible units", columns: [{ key: "delta", label: "Mean difference (selected minus comparison)" }], rows: [{ delta: "5" }] }] }] } };
      }
      await route.fulfill({ json: body });
    });
    await page.goto(surface === "page" ? "/assistant" : "/samples");
    if (surface === "widget") await page.getByRole("button", { name: "Open OpenLIMS Assistant", exact: true }).click();
    const input = page.getByPlaceholder(surface === "page" ? "Compare samples or projects, graph results, find outliers..." : "Ask OpenLIMS...");
    await input.fill("Compare selected results");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    const select = page.getByLabel("Comparison answer focus", { exact: true });
    const lastAnswer = page.locator(surface === "widget" ? ".assistant-widget-message-assistant" : ".assistant-message-assistant").last();
    await expect(select).toHaveValue("overview");
    await select.selectOption("qc_rates");
    await expect(select).toHaveValue("qc_rates");
    await expect(lastAnswer).toContainText("increase of 30.00 percentage points");
    expect(requests.at(-1).message).toBe("Explain failure-rate differences");
    expect(requests.at(-1).context.read_plan_memory).toBe("signed-1");
    await select.selectOption("numeric");
    await expect(select).toHaveValue("numeric");
    await expect(lastAnswer).toContainText("difference 5 ng/µL");
    expect(requests.at(-1).context.result_query_context.filters.qc).toBe("failed");
    expect(requests.at(-1).context.result_query_context.filters.operator).toBe("alice");
    const evidence = page.getByLabel("Answer sources and scope").last();
    await evidence.locator("summary").click();
    await expect(evidence.getByRole("columnheader", { name: "Mean difference (selected minus comparison)" })).toBeVisible();
    await expect(evidence.getByRole("link", { name: "ALPHA · comparison aggregate scope" })).toHaveAttribute("href", "/projects/1");
    await select.selectOption("counts");
    await expect(select).toHaveValue("counts");
    await expect(lastAnswer).toContainText("Largest count difference");
    await page.getByRole("button", { name: "Remove Compare with filter", exact: true }).click();
    await expect(select).toHaveCount(0);
    expect(requests.at(-1).message).toBe("Clear comparison filter");
  });
}
