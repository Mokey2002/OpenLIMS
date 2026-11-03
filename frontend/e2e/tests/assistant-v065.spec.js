const { test, expect } = require("@playwright/test");
const SAMPLE_IDS = ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"];
const PROJECT_ID = "55555555-5555-4555-8555-555555555555";

async function setup(page, context) {
  const requests = [];
  const user = { id: 1, username: "tech", roles: ["tech"] };
  await context.addCookies([{ name: "csrftoken", value: "test-token", url: "http://127.0.0.1:5173" }]);
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let body = [];
    if (path.endsWith("/session/")) body = { user, feature_flags: {} };
    else if (path.endsWith("/me/")) body = user;
    else if (path.endsWith("/ui-settings/")) body = { ui_language: "en" };
    else if (path.endsWith("/assistant/status/")) body = { provider: "openlims", suggestions: [], page_context: true };
    else if (/\/samples\/[12]\/$/.test(path)) {
      const id = Number(path.split("/").at(-2));
      body = { id, public_id: SAMPLE_IDS[id - 1], sample_id: `DNA-${id}`, sample_type: "DNA", status: "RECEIVED", linked_project_summaries: [], form_values: {} };
    } else if (path.endsWith("/samples/99/")) return route.fulfill({ status: 404, json: { detail: "Not found" } });
    else if (path.endsWith("/projects/5/")) body = { id: 5, public_id: PROJECT_ID, code: "ALPHA", name: "Alpha project", members: [], member_usernames: [] };
    else if (path.endsWith("/allowed-transitions/")) body = { allowed_transitions: [] };
    else if (path.endsWith("/assistant/chat/")) {
      const payload = route.request().postDataJSON(); requests.push(payload);
      body = { answer: `Verified answer for ${payload.page_context?.record_id || "conversation"}`, context: { sample_id: 1 },
        links: [{ label: "Open DNA-2", url: "/samples/2" }, { label: "Open unavailable sample", url: "/samples/99" }] };
    }
    await route.fulfill({ json: body });
  });
  return requests;
}

test("widget uses loaded page IDs, supports opt-out, and changes reference on SPA navigation", async ({ page, context }) => {
  const requests = await setup(page, context);
  await page.goto("/samples/1");
  await expect(page.getByRole("heading", { name: "DNA-1", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Open OpenLIMS Assistant", exact: true }).click();
  const bar = page.getByLabel("Current page context");
  await expect(bar.getByLabel("Use this sample: DNA-1", { exact: true })).toBeChecked();
  await bar.getByRole("button", { name: "Why is this blocked?", exact: true }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].page_context).toEqual({ kind: "sample", record_id: SAMPLE_IDS[0] });
  await bar.getByLabel("Use this sample: DNA-1", { exact: true }).uncheck();
  await page.getByPlaceholder("Ask OpenLIMS...").fill("What is DNA?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1].page_context).toBeUndefined();
  await bar.getByLabel("Use this sample: DNA-1", { exact: true }).check();
  await page.getByRole("link", { name: "Open DNA-2", exact: true }).last().click();
  await expect(page.getByRole("heading", { name: "DNA-2", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Open OpenLIMS Assistant", exact: true }).click();
  await expect(bar.getByLabel("Use this sample: DNA-2", { exact: true })).toBeChecked();
  await bar.getByRole("button", { name: "Show results for this sample", exact: true }).click();
  await expect.poll(() => requests.length).toBe(3);
  expect(requests[2].page_context.record_id).toBe(SAMPLE_IDS[1]);
  await page.getByRole("link", { name: "Open unavailable sample", exact: true }).last().click();
  await page.getByRole("button", { name: "Open OpenLIMS Assistant", exact: true }).click();
  await expect(bar).toHaveCount(0);
});

test("a project can be carried explicitly into the full assistant and cleared", async ({ page, context }) => {
  const requests = await setup(page, context);
  await page.goto("/projects/5");
  await expect(page.getByRole("heading", { name: "Alpha project", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Open OpenLIMS Assistant", exact: true }).click();
  const bar = page.getByLabel("Current page context");
  await expect(bar.getByLabel("Use this project: ALPHA", { exact: true })).toBeChecked();
  await bar.getByRole("link", { name: "Open assistant with this record" }).click();
  await expect(page).toHaveURL(/\/assistant$/);
  await expect(bar.getByText("Selected project: ALPHA", { exact: true })).toBeVisible();
  await bar.getByRole("button", { name: "Show samples in this project", exact: true }).click();
  await expect.poll(() => requests.length).toBe(1);
  expect(requests[0].page_context).toEqual({ kind: "project", record_id: PROJECT_ID });
  await bar.getByRole("button", { name: "Clear page selection", exact: true }).click();
  await expect(bar).toHaveCount(0);
  await page.getByPlaceholder("Compare samples or projects, graph results, find outliers...").fill("What is DNA?");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1].page_context).toBeUndefined();
});
