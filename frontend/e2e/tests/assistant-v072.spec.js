const { test, expect } = require("@playwright/test");

test.setTimeout(90_000);
const titles = { batch: "Manage batch work", resources: "Reserve instruments and reagents", repair: "Repair rejected import rows", notebook: "Draft a notebook from a run", handover: "Complete a shift handover" };
const commands = { batch: "Manage batch work", resources: "Reserve resources", repair: "Repair rejected import rows", notebook: "Create a notebook draft from this run", handover: "Prepare a shift handover" };

async function setup(page, context, surface, kind, failure = "") {
  const state = { previews: [], confirmations: [], actions: new Map(), revoked: false, lost: failure === "lost" };
  const defaults = kind === "repair" ? { parent_id: 40 } : { project: "ALPHA" };
  const operationContext = { lab_operation: { kind, defaults } };
  function job() {
    const completed = state.confirmations.length > 0;
    return { id: 41, state: completed ? "completed" : "awaiting_confirmation", status: completed ? "COMPLETED" : "PENDING",
      instrument: "SEQ-1", project: "ALPHA", run_id: "repair-RUN-1", filename: "corrected.csv",
      repair: { parent_id: 40, parent_run_id: "RUN-1", source_rows: [2] }, counts: { rows_received: 1, rows_to_import: 1, rows_imported: completed ? 1 : 0, rows_accounted: 1, results_created: completed ? 1 : 0 },
      mappings: [], row_report: [], report_total: 1, action: state.actions.get("action-1"), download_url: "/api/assistant/instrument-imports/41/report/" };
  }
  await context.addCookies([{ name: "csrftoken", value: "test-token", url: "http://127.0.0.1:5173" }]);
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let body = [];
    const user = { id: 1, username: "operator", roles: ["tech"] };
    if (path.endsWith("/session/")) body = { user, feature_flags: {} };
    else if (path.endsWith("/me/")) body = user;
    else if (path.endsWith("/ui-settings/")) body = { ui_language: "en" };
    else if (path.endsWith("/assistant/status/")) body = { provider: "openlims", suggestions: [commands[kind]] };
    else if (path.endsWith("/assistant/chat/")) body = { answer: "Review this inline form.", lab_operation_form: { kind, title: titles[kind], help: "Preview the exact changes before confirmation.", defaults }, context: operationContext };
    else if (path.endsWith("/lab-operations/options/")) {
      if (state.revoked) return route.fulfill({ status: 403, json: { detail: "Project access was revoked." } });
      body = { can_write: true, projects: [{ code: "ALPHA", name: "Alpha" }], people: ["maria"], batches: ["B-100"],
        instruments: [{ code: "SEQ-1", name: "Sequencer" }], lots: [{ code: "LOT-1", available: "20", unit: "ml" }],
        notebooks: [{ id: 3, name: "Lab notes" }], templates: [], sources: [{ kind: "import", id: 12, label: "RUN-1" }], bookings: [{ id: 9, label: "SEQ-1 booking" }], imports: [{ id: 40, label: "Original import" }] };
    } else if (path.endsWith("/import-repairs/40/")) body = { project: "ALPHA", run_id: "RUN-1", total: 1, next_offset: null, columns: ["sample_id", "value"], rows: [{ row: 2, reason: "Invalid number", values: { sample_id: "S-101", value: "bad" } }] };
    else if (path.endsWith("/lab-operations/preview/")) {
      const payload = route.request().postDataJSON(); state.previews.push(payload);
      if (state.lost) { state.lost = false; return route.abort("failed"); }
      const id = `action-${state.actions.size + 1}`;
      const action = { id, confirmation_token: id, type: kind === "repair" ? "QUEUE_IMPORT" : "LAB_OPERATION", status: "PROPOSED", summary: titles[kind], result: {},
        preview: { operation: kind === "repair" ? "QUEUE_IMPORT" : kind.toUpperCase(), title: "Exact changes", project: { label: "ALPHA" }, records_affected: 1,
          records: [{ id: 21, label: "S-101", current: { status: "PENDING" }, proposed: { assignment: "maria" } }], excluded: [],
          ...(kind === "repair" ? { instrument_import: true, import_job_id: 41 } : {}) } };
      state.actions.set(id, action);
      body = { answer: "Review the exact changes and confirm.", pending_action: action, context: operationContext };
    } else if (path.includes("/assistant/actions/")) {
      const id = path.split("/assistant/actions/")[1].split("/")[0], action = state.actions.get(id);
      if (path.endsWith("/confirm/")) {
        state.confirmations.push(route.request().postDataJSON());
        action.status = "COMPLETED";
        action.result = { operation: kind.toUpperCase(), succeeded_count: 1, failed_count: 0, message: "Confirmed native records were updated.", details: [{ id: 9, label: "S-101", outcome: "updated" }],
          ...(kind === "notebook" ? { url: "/notebook/experiments/9" } : {}) };
      }
      body = action;
    } else if (path.endsWith("/instrument-imports/41/")) body = job();
    await route.fulfill({ json: body });
  });
  await page.goto(surface === "page" ? "/assistant" : "/samples");
  if (surface === "widget") await page.getByRole("button", { name: "Open OpenLIMS Assistant", exact: true }).click();
  await page.getByRole("button", { name: commands[kind], exact: true }).first().click();
  const panel = page.locator(`div[aria-label="${titles[kind]}"]`);
  await expect(panel.getByRole("button", { name: "Refresh choices", exact: true })).toBeEnabled();
  return { state, panel, confirm: async () => {
    await page.getByRole("button", { name: surface === "page" ? "Confirm action" : "Confirm", exact: true }).click();
    await expect(page.getByRole("button", { name: surface === "page" ? "Confirm action" : "Confirm", exact: true })).toHaveCount(0);
  } };
}

for (const surface of ["page", "widget"]) {
  for (const kind of ["batch", "resources", "repair", "notebook", "handover"]) {
    test(`${kind} previews and confirms inside ${surface}`, async ({ page, context }) => {
      const { state, panel, confirm } = await setup(page, context, surface, kind);
      if (kind === "batch") {
        await panel.getByLabel("Batch code (optional)").fill("B-100");
        await panel.getByLabel("Assign to username (optional)").fill("maria");
        await panel.getByLabel("Deadline change").selectOption("set");
        await panel.getByLabel("Deadline", { exact: true }).fill("2026-12-04T12:30");
      } else if (kind === "resources") {
        await panel.getByLabel("Instrument code").fill("SEQ-1");
        await panel.getByLabel("Start time").fill("2026-12-04T10:00");
        await panel.getByLabel("End time").fill("2026-12-04T12:00");
        await panel.getByRole("button", { name: "Add reagent reservation" }).click();
        await panel.getByLabel("Lot code 1").fill("LOT-1");
        await panel.getByLabel("Quantity 1").fill("2");
        await panel.getByLabel("Unit 1").fill("ml");
        await panel.getByLabel("Booking note (optional)").fill("Actual run preparation");
      } else if (kind === "repair") {
        await panel.getByLabel("Repair data row 2").check();
        await panel.getByLabel("Row 2 value").fill("12");
      } else if (kind === "notebook") {
        await panel.getByLabel("Run type").selectOption("import");
        await panel.getByLabel("Run or import ID").fill("12");
        await panel.getByLabel("Notebook ID", { exact: true }).fill("3");
        await panel.getByLabel("Draft title").fill("Sequencing run notes");
        await panel.getByLabel("Actual method notes (optional)").fill("Used the recorded extraction procedure.");
      } else await panel.getByLabel("Recipient username").fill("maria");
      await panel.getByRole("button", { name: kind === "repair" ? "Validate corrections and preview import" : "Preview changes", exact: true }).click();
      await expect(page.getByText("Exact changes", { exact: true })).toBeVisible();
      expect(state.confirmations).toEqual([]);
      const payload = state.previews[0]; expect(payload.kind).toBe(kind);
      if (kind === "batch") expect(payload.fields).toMatchObject({ project: "ALPHA", batch: "B-100", assign_to: "maria", due_at: "2026-12-04T12:30:00.000Z" });
      if (kind === "resources") expect(payload.fields).toMatchObject({ stocks: [{ lot: "LOT-1", quantity: "2", unit: "ml" }], note: "Actual run preparation" });
      if (kind === "repair") expect(payload.fields).toEqual({ parent_id: 40, skip_duplicates: true, corrections: [{ row: 2, values: { value: "12" } }] });
      if (kind === "notebook") expect(payload.fields).toMatchObject({ source_kind: "import", source_id: 12, notebook_id: 3, method_notes: "Used the recorded extraction procedure." });
      if (kind === "handover") expect(payload.fields).toMatchObject({ source: "me", recipient: "maria", send_notice: true });
      await confirm();
      if (kind === "repair") await expect(page.getByText("Import #41: completed", { exact: true })).toBeVisible();
      else await expect(page.getByText("Succeeded: 1", { exact: true })).toBeVisible();
      if (kind === "notebook") await expect(page.getByRole("link", { name: "Open created record" })).toHaveAttribute("href", "/notebook/experiments/9");
      if (kind === "resources") {
        await panel.getByLabel("Resource operation").selectOption("cancel");
        await panel.getByLabel("Booking ID").fill("9");
        await panel.getByRole("button", { name: "Preview changes", exact: true }).click();
        await expect.poll(() => state.previews.length).toBe(2);
        expect(state.previews[1].fields).toEqual({ project: "ALPHA", mode: "cancel", booking_id: 9 });
        await confirm();
      }
      expect(state.confirmations.every(item => item.confirm === true)).toBe(true);
      expect(new URL(page.url()).pathname).toBe(surface === "page" ? "/assistant" : "/samples");
    });
  }

  test(`repair edits survive a lost preview response in ${surface}`, async ({ page, context }) => {
    const { state, panel } = await setup(page, context, surface, "repair", "lost");
    await panel.getByLabel("Repair data row 2").check();
    await panel.getByLabel("Row 2 value").fill("13");
    await panel.getByRole("button", { name: "Validate corrections and preview import" }).click();
    await expect(panel.getByText("The preview response was interrupted. Refresh the records and request a new preview.")).toBeVisible();
    await expect(panel.getByLabel("Row 2 value")).toHaveValue("13");
    await expect(panel.getByLabel("Repair data row 2")).toBeChecked();
    await panel.getByRole("button", { name: "Validate corrections and preview import" }).click();
    await expect(page.getByText("Exact changes", { exact: true })).toBeVisible();
    expect(state.previews[0]).toEqual(state.previews[1]);
    expect(state.confirmations).toEqual([]);
  });

  test(`revoked choices disable new previews in ${surface}`, async ({ page, context }) => {
    const { state, panel } = await setup(page, context, surface, "batch");
    await expect(panel.getByRole("button", { name: "Preview changes", exact: true })).toBeEnabled();
    state.revoked = true;
    await panel.getByRole("button", { name: "Refresh choices", exact: true }).click();
    await expect(panel.getByText("Project access was revoked.", { exact: true })).toBeVisible();
    await expect(panel.getByRole("button", { name: "Preview changes", exact: true })).toBeDisabled();
    expect(state.previews).toEqual([]);
  });
}
