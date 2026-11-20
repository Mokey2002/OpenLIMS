const { test, expect } = require("@playwright/test");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");

const version = readFileSync(resolve(__dirname, "../../../VERSION"), "utf8").trim();
const requestId = "b71512c7-06b9-42fb-a10f-331abc441234";
const reportId = "b71512c7-06b9-42fb-a10f-331abc445678";
const barcode = "OLR-abcdef12345678901234567890123456";
const project = { id: 3, name: "Client project", code: "CLIENT", members: [1, 2] };
const summary = {
  public_id: requestId, request_number: "SUB-2026-00001", title: "Check incoming tubes",
  project_name: project.name, test_name: "Material check", submitted_at: "2026-11-18T12:00:00Z",
};

function reply(route, json, status = 200) {
  return route.fulfill({ json, status });
}

async function mockPortalSignIn(page, user, handleRequest) {
  let signedIn = false;
  await page.route("**/api/v1/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname.slice("/api/v1".length);
    if (path === "/ui-settings/") return reply(route, { ui_language: "en" });
    if (path === "/auth/csrf/") return route.fulfill({
      json: { detail: "CSRF cookie set." }, headers: { "Set-Cookie": "csrftoken=portal-test; Path=/" },
    });
    if (path === "/auth/login/") {
      const { username, password } = request.postDataJSON();
      if (username !== user.username || password !== "test-password") {
        return reply(route, { detail: "Invalid sign-in." }, 401);
      }
      signedIn = true;
      return reply(route, { user });
    }
    if (path === "/auth/refresh/") return reply(route, { detail: "No session" }, 401);
    if (path === "/session/") return signedIn ? reply(route, { user, feature_flags: {} }) : reply(route, {}, 401);
    return handleRequest(route, path);
  });
}

test("a client signs in from the shared page and follows a test request through release", async ({ page }) => {
  const user = { id: 1, username: "client", roles: ["requester"] };
  let submitted;
  let released = false;
  const labRequests = [];
  await mockPortalSignIn(page, user, (route, path) => {
    if (path === "/requester-requests/catalog/") return reply(route, {
      projects: [project],
      tests: [{
        id: 5, project_id: project.id, code: "CHECK", name: "Material check",
        form_schema: { required: ["reads", "summary"], properties: {
          reads: { type: "integer", title: "Reading count" },
          summary: { type: "boolean", title: "Include summary" },
        } },
      }],
    });
    if (path === "/requester-requests/") {
      if (route.request().method() === "POST") {
        submitted = route.request().postDataJSON();
        return reply(route, { public_id: requestId, request_number: summary.request_number }, 201);
      }
      return reply(route, { results: submitted ? [{ ...summary, status: "COMPLETED" }] : [], next: null, previous: null });
    }
    if (path === `/requester-requests/${requestId}/`) return reply(route, {
      ...summary, status: released ? "COMPLETED" : "SUBMITTED",
      samples: [{ reference: "Tube A", barcode, received_at: released ? summary.submitted_at : null }],
      reports: released ? [{ public_id: reportId, title: "Lab report", approved_at: summary.submitted_at }] : [],
    });
    if (path.endsWith("/labels/") || path.endsWith(`/reports/${reportId}/download/`)) {
      const filename = path.endsWith("/labels/") ? "submission-labels.pdf" : "lab-report.pdf";
      return route.fulfill({
        body: "%PDF fixture", headers: { "Content-Type": "application/pdf", "Content-Disposition": `attachment; filename="${filename}"` },
      });
    }
    labRequests.push(path);
    return reply(route, [], 403);
  });

  await page.goto("/login");
  const lab = page.getByRole("form", { name: "Lab sign-in" });
  const requester = page.getByRole("form", { name: "Requester sign-in" });
  await expect(lab).toBeVisible();
  await expect(page.getByRole("heading", { name: "Demo Accounts" })).toBeVisible();
  await expect(page.getByRole("contentinfo")).toHaveText(`OpenLIMS ${version}`);
  await requester.getByLabel("Username").fill("client");
  await expect(lab.getByLabel("Username")).toHaveValue("");
  await requester.getByLabel("Password").fill("incorrect");
  await requester.getByRole("button", { name: "Continue to requester portal" }).click();
  await expect(requester.getByRole("alert")).toContainText("Invalid sign-in.");
  await expect(lab.getByRole("alert")).toHaveCount(0);
  await requester.getByLabel("Password").fill("test-password");
  await requester.getByRole("button", { name: "Continue to requester portal" }).click();
  await expect(page.getByRole("heading", { name: "Requester portal" })).toBeVisible();

  await page.goto("/");
  await expect(page).toHaveURL(/\/requester$/);
  await expect(page.getByRole("link", { name: "Lab workspace" })).toHaveCount(0);
  await expect(page.getByRole("contentinfo")).toHaveText(`OpenLIMS ${version}`);
  await page.getByLabel("Test", { exact: true }).selectOption("5");
  await page.getByLabel("Request title").fill(summary.title);
  await page.getByLabel("Sample references").fill("Tube A");
  await page.getByLabel("Reading count").fill("0");
  await page.getByLabel("Include summary").selectOption({ label: "No" });
  await page.getByRole("button", { name: "Submit test request" }).click();
  await expect(page.getByRole("heading", { name: summary.title })).toBeVisible();
  expect(submitted).toMatchObject({
    project: project.id, request_type: 5, title: summary.title,
    sample_references: ["Tube A"], form_data: { reads: 0, summary: false },
    submission_id: expect.stringMatching(/^[a-f0-9-]{36}$/),
  });
  await expect(page.getByText("Awaiting receipt")).toBeVisible();
  await expect(page.getByText("Reports appear here after the lab releases them.")).toBeVisible();
  const [label] = await Promise.all([
    page.waitForEvent("download"), page.getByRole("button", { name: "Download labels (PDF)" }).click(),
  ]);
  expect(label.suggestedFilename()).toBe("submission-labels.pdf");

  released = true;
  await page.getByRole("button", { name: "Refresh status" }).click();
  await expect(page.getByText("Completed", { exact: true })).toBeVisible();
  const [report] = await Promise.all([
    page.waitForEvent("download"), page.getByRole("button", { name: "Download report Lab report" }).click(),
  ]);
  expect(report.suggestedFilename()).toBe("lab-report.pdf");
  await page.getByRole("link", { name: "Back to my test requests" }).click();
  await expect(page.getByRole("link", { name: summary.title })).toBeVisible();
  expect(labRequests).toEqual([]);
});

test("requester sign-in returns internal users to the request in their bookmark", async ({ page }) => {
  const user = { id: 2, username: "receiver", roles: ["tech"] };
  await mockPortalSignIn(page, user, (route, path) => {
    if (path === `/requester-requests/${requestId}/`) {
      return reply(route, { ...summary, status: "SUBMITTED", samples: [], reports: [] });
    }
    return reply(route, {}, 404);
  });

  const bookmark = `/requester/${requestId}`;
  await page.goto(bookmark);
  await expect(page).toHaveURL(`/login?return_to=${encodeURIComponent(bookmark)}`);
  const form = page.getByRole("form", { name: "Requester sign-in" });
  await expect(page.getByRole("heading", { name: "Demo Accounts" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "All sign-in options" })).toHaveAttribute("href", "/login");
  await form.getByLabel("Username").fill(user.username);
  await form.getByLabel("Password").fill("test-password");
  await form.getByRole("button", { name: "Continue to requester portal" }).click();
  await expect(page).toHaveURL(bookmark);
  await expect(page.getByRole("heading", { name: summary.title })).toBeVisible();
});

test("the shared login offers the demo requester account", async ({ page }) => {
  await page.route("**/api/v1/ui-settings/", route => reply(route, { ui_language: "en" }));

  await page.goto("/login");
  await page.getByRole("link", { name: "Open requester demo" }).click();
  const form = page.getByRole("form", { name: "Requester sign-in" });
  await expect(form.getByLabel("Username")).toHaveValue("demo-requester");
  await expect(form.getByLabel("Password")).toHaveValue("");
  await expect(form.getByRole("button", { name: "Continue to requester portal" })).toBeDisabled();
});

test("staff opens a submission barcode against its receiving project", async ({ page, context, baseURL }) => {
  const user = { id: 2, username: "receiver", roles: ["tech"] };
  const item = {
    public_id: reportId, submission_reference: "Tube A", submission_barcode: barcode, submission_received_at: null,
  };
  const workflow = {
    ...summary, id: 7, status: "SUBMITTED", items: [item], project: project.id, messages: [], reports: [],
  };
  const sample = { id: 12, sample_id: barcode, sample_type: "GENERAL", project_code: project.code, can_modify: true };
  const submission = { reference: "Tube A", project: project.id, project_name: project.name,
    request_number: summary.request_number, request_public_id: requestId };
  let registration;
  await context.addCookies([{ name: "csrftoken", value: "portal-test", url: baseURL }]);
  await page.route("**/api/v1/**", async route => {
    const path = new URL(route.request().url()).pathname.slice("/api/v1".length);
    const responses = {
      "/ui-settings/": { ui_language: "en", assistant_helper_enabled: false },
      "/session/": { user, feature_flags: {} },
      "/me/": user,
      "/workflow-requests/": [{ ...workflow, id: 6, public_id: reportId, title: "Another request", items: [] }, workflow],
      "/projects/": [project],
      "/samples/accession-lookup/": { kind: "new", barcode, submission },
      "/samples/12/receive/": { kind: "existing", sample, barcode, submission, receipt: { received_at: summary.submitted_at, received_by: user.username } },
    };
    if (path === "/samples/accession-register/") {
      registration = route.request().postDataJSON();
      return reply(route, { kind: "existing", barcode, sample, submission }, 201);
    }
    return reply(route, responses[path] ?? []);
  });

  await page.goto(`/workflow-requests?request=${requestId}`);
  await expect(page.getByRole("heading", { name: new RegExp(summary.title) })).toBeVisible();
  await page.getByRole("link", { name: "Receive sample", exact: true }).click();
  await expect(page.getByLabel("Tube barcode")).toHaveValue(barcode);
  await page.getByRole("button", { name: "Look up barcode" }).click();
  await expect(page.getByLabel("Receiving project")).toBeDisabled();
  await expect(page.getByLabel("Receiving project")).toHaveValue(String(project.id));
  await page.getByRole("button", { name: "Register sample" }).click();
  await expect.poll(() => registration).toMatchObject({ barcode, project: project.id, sample_type: "GENERAL" });
  await page.getByLabel("Receipt note / reason").fill("Tube received intact");
  await page.getByRole("button", { name: "Record receipt" }).click();
  await expect(page.getByText("Received by")).toBeVisible();
  await page.getByRole("link", { name: summary.request_number }).click();
  await expect(page).toHaveURL(`/workflow-requests?request=${requestId}`);
});
