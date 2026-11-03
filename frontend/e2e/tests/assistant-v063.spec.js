const { test, expect } = require("@playwright/test");

for (const surface of ["page", "widget"]) {
  test(`result filters, drill-down navigation and statistics work in ${surface}`, async ({ page, context }) => {
    const user = { id: 1, username: "technician", roles: ["tech"] };
    const requests = [];
    const filters = { qc: "failed", period: "yesterday", instrument: "SEQ-1", operator: "alice", compare_period: "last_week" };
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
        const message = payload.message;
        if (message === "Clear operator filter") delete filters.operator;
        if (message === "Only instrument SEQ-2") filters.instrument = "SEQ-2";
        if (message.startsWith("From ")) {
          delete filters.period;
          filters.created_from = "2026-10-01"; filters.created_before = "2026-11-01";
        }
        const detail = message === "Explain the first result";
        body = {
          answer: "Recorded evidence", answer_overview: { text: detail ? "R-42: concentration 45 ng/uL; above configured maximum; recorded QC reason: control drift." : "Filtered result comparison." },
          context: { read_plan_memory: `signed-${requests.length}`, ...(detail
            ? { investigation_navigation: { can_return: true, comparison: true } }
            : { result_query_context: { kind: "project", target: "ALPHA", filters: { ...filters } } }) },
          citations: [{ label: "R-42 concentration", url: "/samples/1#result-42" }],
          read_plan: { scope: "Current accessible records", steps: [{ operation: detail ? "result_detail" : "project_results_compare", status: "completed", answer: "Full recorded evidence", statistics_tables: detail ? [] : [{
            title: "QC failure rates among assessed checks", columns: [{ key: "checks", label: "Failed / assessed" }, { key: "rate", label: "Failure rate", format: "percent" }],
            rows: [{ checks: "1/4", rate: 25 }], notes: ["Unassessed results are reported separately."]
          }] }] },
        };
      }
      await route.fulfill({ json: body });
    });
    await page.goto(surface === "page" ? "/assistant" : "/samples");
    if (surface === "widget") await page.getByRole("button", { name: "Open OpenLIMS Assistant", exact: true }).click();
    const input = page.getByPlaceholder(surface === "page" ? "Compare samples or projects, graph results, find outliers..." : "Ask OpenLIMS...");
    const send = async text => { await input.fill(text); await page.getByRole("button", { name: "Send", exact: true }).click(); await expect(input).toBeEnabled(); };
    await send("Show results for project ALPHA yesterday");
    const panel = page.getByLabel("Result query filters");
    await expect(panel.getByRole("button", { name: "Remove Entered by filter" })).toBeVisible();
    await panel.getByRole("button", { name: "Remove Entered by filter" }).click();
    await expect(panel.getByRole("button", { name: "Remove Entered by filter" })).toHaveCount(0);
    expect(requests.at(-1).context.read_plan_memory).toBe("signed-1");
    await panel.getByText("Edit result filters", { exact: true }).click();
    await panel.getByLabel("Result filter value", { exact: true }).fill("SEQ-2");
    await panel.getByRole("button", { name: "Apply filter", exact: true }).click();
    await expect(panel.getByRole("button", { name: "Remove Instrument filter" })).toContainText("SEQ-2");
    await panel.getByLabel("Result filter field", { exact: true }).selectOption("date");
    await panel.getByLabel("Result filter value", { exact: true }).fill("2026-10-01");
    await panel.getByLabel("Result filter end date", { exact: true }).fill("2026-11-01");
    await panel.getByRole("button", { name: "Apply filter", exact: true }).click();
    await expect(panel.getByRole("button", { name: "Remove From filter" })).toContainText("2026-10-01");
    expect(requests.at(-1).message).toBe("From 2026-10-01 until 2026-11-01");
    const evidence = page.getByLabel("Answer sources and scope").last();
    await evidence.locator("summary").click();
    await expect(evidence.getByText("1/4", { exact: true })).toBeVisible();
    await expect(evidence.getByText("25.0%", { exact: true })).toBeVisible();
    await send("Explain the first result");
    await expect(panel.getByRole("button", { name: "Back to comparison", exact: true })).toBeVisible();
    await panel.getByRole("button", { name: "Back to comparison", exact: true }).click();
    await expect(panel.getByRole("button", { name: "Remove Instrument filter" })).toContainText("SEQ-2");
    expect(requests.at(-1).message).toBe("Back to comparison");
    expect(requests.at(-1).context.read_plan_memory).toBe("signed-5");
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(panel.getByRole("button", { name: "Remove Instrument filter" })).toBeVisible();
  });
}
