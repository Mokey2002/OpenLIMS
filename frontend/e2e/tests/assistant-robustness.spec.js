const { test, expect } = require("@playwright/test");
const { readFileSync } = require("node:fs");

test.setTimeout(90_000);

async function mock(page, context, roles, sourceAllowed = true, assistantEnabled = true) {
  const user = { id: 1, username: "operator", roles };
  const requests = [];
  const job = { id: 7, instrument: "SEQ-1", project: "ALPHA", run_id: "RUN-7", filename: "instrument.csv", status: "COMPLETED", state: "completed",
    mappings: [], row_report: [], report_total: 1, counts: { rows_received: 1, rows_imported: 1, rows_accounted: 1, results_created: 1 },
    download_url: "/api/assistant/instrument-imports/7/report/", source_download_url: "/api/assistant/instrument-imports/7/source/" };
  await context.addCookies([{ name: "csrftoken", value: "test-token", url: "http://127.0.0.1:5173" }]);
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1/", "/api/");
    requests.push({ path, method: route.request().method() });
    let body = [];
    if (path.endsWith("/session/")) body = { user, feature_flags: {} };
    else if (path.endsWith("/me/")) body = user;
    else if (path.endsWith("/ui-settings/")) body = { ui_language: "en", assistant_helper_enabled: assistantEnabled };
    else if (path.endsWith("/assistant/status/")) body = { provider: "openlims", suggestions: ["Show instrument import #7"] };
    else if (path.endsWith("/assistant/chat/")) body = { answer: "Import completed; every row is accounted for.", instrument_import_job: job, context: { instrument_import_job_id: 7 } };
    else if (path.endsWith("/assistant/instrument-imports/7/")) body = job;
    else if (path.endsWith("/assistant/instrument-imports/7/source/")) {
      if (!sourceAllowed) return route.fulfill({ status: 404, json: { detail: "Import unavailable." } });
      return route.fulfill({ contentType: "application/octet-stream", headers: { "Content-Disposition": 'attachment; filename="instrument.csv"' }, body: "sample_id,value\nS-100,10\n" });
    }
    await route.fulfill({ json: body });
  });
  return requests;
}

for (const surface of ["page", "widget"]) {
  for (const allowed of [true, false]) {
    test(`authenticated source download ${allowed ? "succeeds" : "reports revoked access"} in ${surface}`, async ({ page, context }) => {
      const requests = await mock(page, context, ["tech"], allowed);
      await page.goto(surface === "page" ? "/assistant" : "/samples");
      if (surface === "widget") await page.getByRole("button", { name: "Open OpenLIMS Assistant", exact: true }).click();
      await page.getByRole("button", { name: "Show instrument import #7", exact: true }).first().click();
      const receipt = page.getByLabel("Instrument import receipt");
      if (allowed) {
        const download = page.waitForEvent("download");
        await receipt.getByRole("button", { name: "Download source file", exact: true }).click();
        const file = await download;
        expect(file.suggestedFilename()).toBe("instrument.csv");
        expect(readFileSync(await file.path(), "utf8")).toBe("sample_id,value\nS-100,10\n");
      } else {
        await receipt.getByRole("button", { name: "Download source file", exact: true }).click();
        await expect(receipt.getByRole("alert")).toContainText("Could not download the source file.");
      }
      expect(requests.filter(row => row.path.endsWith("/source/")).every(row => row.method === "GET")).toBe(true);
      expect(requests.filter(row => row.path.includes("/actions/"))).toEqual([]);
    });
  }
}

for (const roles of [["admin", "viewer"], ["tech", "viewer"], ["viewer"]]) {
  test(`imports explain access correctly for ${roles.join("+")}`, async ({ page, context }) => {
    await mock(page, context, roles, true, false);
    await page.goto("/imports");
    await expect(page.getByTestId("current-user-name")).toHaveText("operator");
    const banner = page.getByText("Read-only access: contact an admin or tech to make changes.", { exact: true });
    if (roles.length > 1) {
      await expect(page.locator('input[type="file"]').first()).toBeEnabled();
      await expect(banner).toHaveCount(0);
    } else {
      await expect(banner).toBeVisible();
      await expect(page.locator('input[type="file"]').first()).toBeDisabled();
    }
  });
}
