const { test, expect } = require("@playwright/test");
const { performance } = require("node:perf_hooks");

// Uses real APIs and a dedicated test account. No mocked response timings.
test("My Work and destination content timing", async ({ page }, testInfo) => {
  const required = ["OPENLIMS_PERF_USER", "OPENLIMS_PERF_PASSWORD", "OPENLIMS_PERF_PROJECT", "OPENLIMS_PERF_SAMPLE"];
  for (const key of required) if (!process.env[key]) throw new Error(`Set ${key} for the isolated test deployment.`);
  const rounds = Number(process.env.OPENLIMS_PERF_ROUNDS || 5);
  if (!Number.isInteger(rounds) || rounds < 5 || rounds > 100) throw new Error("Use 5–100 rounds.");
  const readyLimit = Number(process.env.OPENLIMS_PERF_READY_MS || 30000);
  if (!Number.isFinite(readyLimit) || readyLimit <= 0) throw new Error("Invalid readiness timeout.");
  await page.goto("/login");
  await page.getByLabel("Username", { exact: true }).fill(process.env.OPENLIMS_PERF_USER);
  await page.getByLabel("Password", { exact: true }).fill(process.env.OPENLIMS_PERF_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByTestId("my-work-page")).toBeVisible({ timeout: readyLimit });
  let documents = 0;
  page.on("request", request => { if (request.isNavigationRequest() && request.frame() === page.mainFrame()) documents++; });
  const samples = { projects: [], sample_list: [], my_work: [] };
  const measure = async (name, action, ready) => {
    const start = performance.now();
    await action();
    await expect(ready).toBeVisible({ timeout: readyLimit });
    samples[name].push(performance.now() - start);
  };
  let reports;
  try {
    for (let i = 0; i < rounds; i++) {
      for (const [name, menu, link, value] of [
        ["projects", "Plan", "Projects", process.env.OPENLIMS_PERF_PROJECT],
        ["sample_list", "Receive", "Samples", process.env.OPENLIMS_PERF_SAMPLE],
      ]) {
        await page.getByRole("button", { name: menu, exact: true }).click();
        await measure(name, () => page.getByRole("link", { name: link, exact: true }).click(), page.getByText(value, { exact: true }).first());
        await measure("my_work", () => page.getByRole("link", { name: "My Work", exact: true }).click(), page.getByTestId("my-work-page"));
      }
    }
    expect(documents, "Navigation must not require a full document refresh").toBe(0);
  } finally {
    reports = Object.fromEntries(Object.entries(samples).map(([name, values]) => {
      const sorted = [...values].sort((a, b) => a - b);
      return [name, { count: values.length, first_ms: values[0], p50_ms: sorted[Math.ceil(sorted.length * .5) - 1], p95_ms: sorted[Math.ceil(sorted.length * .95) - 1], timings_ms: values }];
    }));
    await testInfo.attach("navigation-timings", { body: JSON.stringify({ reports, document_reloads: documents }, null, 2), contentType: "application/json" });
  }
  if (process.env.OPENLIMS_PERF_P95_MS) {
    const budget = Number(process.env.OPENLIMS_PERF_P95_MS);
    for (const [name, report] of Object.entries(reports)) expect(report.p95_ms, name).toBeLessThanOrEqual(budget);
  }
});
