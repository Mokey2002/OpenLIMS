const { test, expect } = require("@playwright/test");

for (const surface of ["page", "widget"]) {
  test(`read plan sources open an accessible full SOP section from ${surface}`, async ({ page, context }) => {
    const user = { id: 1, username: "technician", roles: ["tech"] };
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
        body = {
          answer: "Recorded QC failure; the SOP recommends checking the calibration control.", context: {},
          citations: [{ kind: "sop", label: "SOP-CONCENTRATION version 3, section 4.2", url: "/sops/7",
            scope: "Current approved section.", excerpt: "Check the calibration control.", excerpt_truncated: true }],
          read_plan: { read_only: true, partial: true, scope: "One sample was unavailable; sources are checked independently.",
            steps: [{ operation: "sample_evidence", status: "unavailable" }, { operation: "sop_search", status: "completed" }] },
        };
      } else if (path.endsWith("/sop-documents/7/")) body = {
        document_code: "SOP-CONCENTRATION", title: "Concentration review", version: "3", section: "4.2",
        approved: true, status: "CURRENT", content: "Full instructions: check the calibration control and record the review.",
      };
      await route.fulfill({ json: body });
    });
    await page.goto(surface === "page" ? "/assistant" : "/samples");
    if (surface === "widget") await page.getByRole("button", { name: "Open OpenLIMS Assistant", exact: true }).click();
    await page.getByPlaceholder(surface === "page" ? "Compare samples or projects, graph results, find outliers..." : "Ask OpenLIMS...")
      .fill("Show evidence for sample S-100; show the SOP for concentration");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    const sources = page.getByLabel("Answer sources and scope");
    await sources.locator("summary").click();
    await expect(sources.getByText("Some requested information was unavailable.", { exact: true })).toBeVisible();
    await expect(sources.getByText("Check the calibration control.", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Confirm action", exact: true })).toHaveCount(0);
    await sources.getByRole("link", { name: "SOP-CONCENTRATION version 3, section 4.2", exact: true }).click();
    await expect(page).toHaveURL(/\/sops\/7$/);
    await expect(page.getByText("Full instructions: check the calibration control and record the review.", { exact: true })).toBeVisible();
    expect(sent).toHaveLength(1);
  });
}

test("SOP source handles access revocation without showing the old section", async ({ page }) => {
  const user = { id: 1, username: "technician", roles: ["tech"] };
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/sop-documents/7/")) return route.fulfill({ status: 404, json: { detail: "Not found." } });
    const body = path.endsWith("/session/") ? { user, feature_flags: {} }
      : path.endsWith("/me/") ? user : path.endsWith("/ui-settings/") ? { ui_language: "en" } : [];
    await route.fulfill({ json: body });
  });
  await page.goto("/sops/7");
  await expect(page.getByText("This SOP section is unavailable or you no longer have access.", { exact: true })).toBeVisible();
});
