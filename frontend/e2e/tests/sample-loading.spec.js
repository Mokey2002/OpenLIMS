const { test, expect } = require("@playwright/test");

test("sample search debounces, cancels stale results and reuses reference data", async ({ page }) => {
  const requests = [];
  let releaseOld;
  const oldResponse = new Promise(resolve => { releaseOld = resolve; });
  const user = { id: 1, username: "viewer", roles: ["viewer"] };
  await page.route("**/api/**", async route => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace("/api/v1/", "/api/");
    requests.push({ path, query: url.search });
    let body = [];
    if (path === "/api/session/") body = { user, feature_flags: {} };
    if (path === "/api/me/") body = user;
    if (path === "/api/ui-settings/") body = { ui_language: "en", assistant_helper_enabled: false };
    if (path === "/api/samples/") {
      const search = url.searchParams.get("search");
      if (search === "OLD") await oldResponse;
      body = { count: 20, next: "?page=2", previous: null, results: [{ id: 1, sample_id: search || "INITIAL", status: "RECEIVED" }] };
    }
    await route.fulfill({ json: body }).catch(() => {});
  });
  await page.goto("/samples");
  await expect(page.getByRole("link", { name: "INITIAL", exact: true })).toBeVisible();
  const references = () => requests.filter(r => ["/api/me/", "/api/projects/", "/api/containers/", "/api/sample-forms/"].includes(r.path)).length;
  const initialReferences = references();
  const samples = () => requests.filter(r => r.path === "/api/samples/");
  const initialSamples = samples().length;
  const search = page.getByPlaceholder("Search by sample ID");
  await search.pressSequentially("ABC", { delay: 30 });
  await expect(page.getByRole("link", { name: "ABC", exact: true })).toBeVisible();
  expect(samples().slice(initialSamples).map(r => new URLSearchParams(r.query).get("search"))).toEqual(["ABC"]);
  await search.fill("OLD");
  await expect.poll(() => samples().some(r => r.query.includes("OLD"))).toBe(true);
  await search.fill("NEW");
  await expect(page.getByRole("link", { name: "NEW", exact: true })).toBeVisible();
  releaseOld();
  await expect(page.getByRole("link", { name: "OLD", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect.poll(() => samples().at(-1).query).toContain("page=2");
  const beforeFilter = samples().length;
  await page.locator("select").filter({ has: page.locator('option', { hasText: "All statuses" }) }).selectOption("QC");
  await expect.poll(() => samples().length).toBe(beforeFilter + 1);
  expect(samples().at(-1).query).toContain("page=1");
  expect(samples().at(-1).query).toContain("status=QC");
  expect(references()).toBe(initialReferences);
});
