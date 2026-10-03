const { test, expect } = require("@playwright/test");
const defaults = { RECEIVED: ["IN_PROGRESS", "CANCELLED"], IN_PROGRESS: ["QC", "CANCELLED"], QC: ["REPORTED", "CANCELLED"], REPORTED: ["ARCHIVED"], CANCELLED: ["ARCHIVED"], ARCHIVED: [] };

async function setup(page, { admin = true, conflict = false, language = "en" } = {}) {
  let policy = { revision: 1, transitions: structuredClone(defaults), supported_transitions: defaults };
  const writes = [];
  const user = { id: 1, username: "operator", roles: [admin ? "admin" : "tech"] };
  await page.context().addCookies([{ name: "csrftoken", value: "csrf-test", url: "http://127.0.0.1:5173" }]);
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1/", "/api/");
    let body = [];
    if (path === "/api/session/") body = { user, feature_flags: { notebook: true } };
    if (path === "/api/me/") body = user;
    if (path === "/api/ui-settings/") body = { ui_language: language, assistant_helper_enabled: false };
    if (path === "/api/system-settings/") body = { id: 1, lab_name: "Our lab", allowed_fasta_extensions: [".fasta"], notebook_enabled: true };
    if (path === "/api/sample-status-policy/") {
      if (route.request().method() === "PATCH") {
        writes.push(route.request().postDataJSON());
        if (conflict) return route.fulfill({ status: 409, json: { detail: "Changed" } });
        policy = { ...policy, transitions: writes.at(-1).transitions, revision: policy.revision + 1 };
      }
      body = policy;
    }
    await route.fulfill({ json: body });
  });
  await page.goto("/settings");
  return writes;
}

test("administrator configures and restores a status policy with an audit reason", async ({ page }) => {
  const writes = await setup(page);
  await expect(page.getByRole("link", { name: "Sample fields and forms" })).toHaveAttribute("href", "#sample-form-builder");
  await expect(page.getByRole("link", { name: "Account roles and invitations" })).toHaveAttribute("href", "/users");
  await page.getByLabel("RECEIVED → CANCELLED", { exact: true }).uncheck();
  await expect(page.getByRole("button", { name: "Save status policy" })).toBeDisabled();
  await page.getByLabel("Reason for policy change").fill("Lab requires receipt processing first");
  await page.getByRole("button", { name: "Save status policy" }).click();
  await expect(page.getByText("Status policy saved and audited.")).toBeVisible();
  expect(writes[0].expected_revision).toBe(1);
  expect(writes[0].transitions.RECEIVED).toEqual(["IN_PROGRESS"]);
  await page.reload();
  await expect(page.getByLabel("RECEIVED → CANCELLED", { exact: true })).not.toBeChecked();
  await page.getByRole("button", { name: "Use default transitions" }).click();
  await expect(page.getByLabel("RECEIVED → CANCELLED", { exact: true })).toBeChecked();
  expect(writes).toHaveLength(1);
  await page.getByLabel("Reason for policy change").fill("Restore the default lab lifecycle");
  await page.getByRole("button", { name: "Save status policy" }).click();
  await expect(page.getByText("Status policy saved and audited.")).toBeVisible();
  expect(writes[1].expected_revision).toBe(2);
  expect(writes[1].transitions).toEqual(defaults);
});

test("invalid dead end cannot be saved and QC bypass is not offered", async ({ page }) => {
  await setup(page);
  await page.getByLabel("RECEIVED → CANCELLED", { exact: true }).uncheck();
  await page.getByLabel("RECEIVED → IN_PROGRESS", { exact: true }).uncheck();
  await page.getByLabel("Reason for policy change").fill("Testing a deliberately invalid policy");
  await expect(page.getByText("Keep at least one destination for every non-final status.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save status policy" })).toBeDisabled();
  await expect(page.getByLabel("RECEIVED → REPORTED", { exact: true })).toHaveCount(0);
});

test("stale save preserves edits and reload requires confirmation", async ({ page }) => {
  await setup(page, { conflict: true });
  await page.getByLabel("RECEIVED → CANCELLED", { exact: true }).uncheck();
  await page.getByLabel("Reason for policy change").fill("Preserve this reason after conflict");
  await page.getByRole("button", { name: "Save status policy" }).click();
  await expect(page.getByText(/Not saved. The policy may have changed/)).toBeVisible();
  await expect(page.getByLabel("Reason for policy change")).toHaveValue("Preserve this reason after conflict");
  page.once("dialog", dialog => dialog.dismiss());
  await page.getByRole("button", { name: "Reload policy" }).click();
  await expect(page.getByLabel("RECEIVED → CANCELLED", { exact: true })).not.toBeChecked();
  page.once("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "Reload policy" }).click();
  await expect(page.getByLabel("RECEIVED → CANCELLED", { exact: true })).toBeChecked();
});

test("non-admin sees read-only configuration", async ({ page }) => {
  await setup(page, { admin: false });
  await expect(page.getByLabel("RECEIVED → CANCELLED", { exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Save status policy" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Account roles and invitations" })).toHaveCount(0);
});

test("configuration guide is available in Spanish", async ({ page }) => {
  await setup(page, { language: "es" });
  await expect(page.getByRole("heading", { name: "Configura tu laboratorio sin código" })).toBeVisible();
  await expect(page.getByLabel("Motivo del cambio de política")).toBeVisible();
});
