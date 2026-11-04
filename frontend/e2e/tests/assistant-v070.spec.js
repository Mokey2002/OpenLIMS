const { test, expect } = require("@playwright/test");

// These flows include several separate confirmations and recovery/download
// requests. Keep individual assertions strict while allowing shared CI load.
test.setTimeout(90_000);

const user = { id: 1, username: "operator", roles: ["tech"] };
async function open(page, context, surface, handler) {
  await context.addCookies([{ name: "csrftoken", value: "test-token", url: "http://127.0.0.1:5173" }]);
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let body = [];
    if (path.endsWith("/session/")) body = { user, feature_flags: {} };
    else if (path.endsWith("/me/")) body = user;
    else if (path.endsWith("/ui-settings/")) body = { ui_language: "en" };
    else if (path.endsWith("/assistant/status/")) body = { provider: "openlims", suggestions: ["What should I work on today?", "Investigate project ALPHA QC failures"] };
    else {
      const result = await handler(route, path);
      if (result === null) return;
      body = result || [];
    }
    await route.fulfill({ json: body });
  });
  await page.goto(surface === "page" ? "/assistant" : "/samples");
  if (surface === "widget") await page.getByRole("button", { name: "Open OpenLIMS Assistant", exact: true }).click();
}

for (const surface of ["page", "widget"]) {
  for (const recovery of ["none", "stale_preview", "lost_confirmation"]) {
    test(`daily work filters, confirmed actions and ${recovery} recovery in ${surface}`, async ({ page, context }) => {
      const state = { status: "PENDING", assigned: "operator", revision: 1, revoked: false }, actions = new Map(), requests = [], confirmed = [];
      let stale = recovery === "stale_preview", lost = recovery === "lost_confirmation";
      const row = () => ({ id: 21, sample_id: 1, sample: "S-100", project: "ALPHA", work: "Extraction", status: state.status,
        qc_status: "PENDING_REVIEW", assigned_to: state.assigned, due: null, review: "No deadline", reason: "Available work; inspect the recorded requirements.",
        priority: 4, missing_fields: [], failed_results: 0, evidence: [], evidence_count: 0, can_assign: true,
        can_start: state.status === "PENDING", can_complete: true, can_schedule: true, can_review: false,
        digest: String(state.revision).padStart(64, "0") });
      const reply = scope => ({ answer: "Here are your assessed work priorities.", daily_work: { scope, as_of: "2026-11-04T12:00:00Z", timezone: "UTC",
        rows: state.status === "COMPLETED" ? [] : [row()], assessed: 1, total_candidates: 1, matched_assessed: state.status === "COMPLETED" ? 0 : 1,
        next_offset: null, day: { start: "2026-11-04T00:00:00+00:00", end_exclusive: "2026-11-05T00:00:00+00:00" }, notes: ["Live records; no prediction of scientific importance."] }, context: { daily_work: scope } });
      const initialScope = { scope: "mine", focus: "all", project: "", offset: 0 };
      await open(page, context, surface, async (route, path) => {
        if (path.endsWith("/assistant/chat/")) return reply(initialScope);
        if (path.endsWith("/assistant/daily-work/")) {
          const params = Object.fromEntries(new URL(route.request().url()).searchParams);
          if (state.revoked) return { answer: "Project unavailable. Use one exact accessible project code." };
          return reply({ ...initialScope, ...params, offset: Number(params.offset || 0) });
        }
        if (path.endsWith("/assistant/daily-work/actions/")) {
          const data = route.request().postDataJSON(); requests.push(data);
          expect(data.digest).toBe(row().digest);
          if (data.operation === "DAILY_START" && stale) {
            stale = false; state.revision++;
            await route.fulfill({ status: 400, json: { detail: "Work or evidence changed. Refresh your priorities and request a fresh preview." } }); return null;
          }
          const id = `daily-${actions.size + 1}`, action = { id, confirmation_token: id, type: "WORK_ITEM_OPERATION", status: "PROPOSED", result: {},
            summary: data.operation, preview: { operation: data.operation, records_affected: 1, proposed_values: data.operation === "DAILY_ASSIGN" ? { assigned_to: data.assignee } : { status: data.operation }, warnings: ["Nothing changes before confirmation."] } };
          actions.set(id, { action, data }); return { ...reply(data.scope), pending_action: action };
        }
        if (path.includes("/assistant/actions/")) {
          const id = path.split("/assistant/actions/")[1].split("/")[0], entry = actions.get(id);
          if (path.endsWith("/confirm/")) {
            confirmed.push(route.request().postDataJSON()); state.revision++;
            if (entry.data.operation === "DAILY_ASSIGN") state.assigned = entry.data.assignee;
            if (entry.data.operation === "DAILY_START") state.status = "IN_PROGRESS";
            if (entry.data.operation === "DAILY_COMPLETE") state.status = "COMPLETED";
            entry.action.status = "COMPLETED"; entry.action.result = { operation: entry.data.operation, succeeded_count: 1, failed_count: 0, message: "Work updated. Priorities will be refreshed from current records." };
            if (entry.data.operation === "DAILY_COMPLETE" && lost) { lost = false; await route.abort("failed"); return null; }
          }
          return entry.action;
        }
      });
      await page.getByRole("button", { name: "What should I work on today?", exact: true }).first().click();
      const panel = page.getByRole("region", { name: "Daily work assistant" }), work = panel.getByRole("article", { name: "Work item 21" });
      await expect(work).toBeVisible();
      await panel.getByLabel("Work scope", { exact: true }).selectOption("team");
      await panel.getByLabel("Exact project code (optional)").fill("ALPHA");
      await panel.getByRole("button", { name: "Apply work filters", exact: true }).click();
      await work.getByRole("button", { name: "Assign work", exact: true }).click();
      await work.getByLabel("Exact assignee username").fill("maria");
      await work.getByRole("button", { name: "Preview assignment", exact: true }).click();
      expect(state.assigned).toBe("operator");
      async function confirm() {
        await page.getByRole("button", { name: surface === "page" ? "Confirm action" : "Confirm", exact: true }).click();
        await expect(page.getByRole("button", { name: surface === "page" ? "Confirm action" : "Confirm", exact: true })).toHaveCount(0);
      }
      await confirm();
      await work.getByRole("button", { name: "Preview start", exact: true }).click();
      if (recovery === "stale_preview") {
        await expect(panel.getByText("Work or evidence changed. Refresh your priorities and request a fresh preview.", { exact: true })).toBeVisible();
        expect(state.status).toBe("PENDING");
        await work.getByRole("button", { name: "Preview start", exact: true }).click();
      }
      expect(state.status).toBe("PENDING"); await confirm();
      await work.getByRole("button", { name: "Update deadline", exact: true }).click();
      await work.getByLabel("Deadline in your browser timezone", { exact: false }).fill("2026-12-02T12:30");
      await work.getByRole("button", { name: "Preview deadline", exact: true }).click();
      const deadline = requests.find(data => data.operation === "DAILY_DUE");
      expect(deadline.due_at).toMatch(/Z$/); await confirm();
      await work.getByRole("button", { name: "Preview completion", exact: true }).click();
      expect(state.status).toBe("IN_PROGRESS"); await confirm();
      await expect(panel.getByText("No matching priorities in this assessment. This is not a team-wide all-clear.", { exact: true })).toBeVisible();
      expect(confirmed).toHaveLength(4);
      expect(requests.every(data => data.scope.scope === "team" && data.scope.project === "ALPHA")).toBe(true);
      state.revoked = true;
      await panel.getByRole("button", { name: "Refresh priorities", exact: true }).click();
      await expect(panel.getByText("Project unavailable. Use one exact accessible project code.", { exact: true })).toBeVisible();
      await expect(work).toHaveCount(0);
    });

    test(`project QC evidence, report export and ${recovery} recovery in ${surface}`, async ({ page, context }) => {
      const requests = [], confirmations = [], actions = new Map();
      let revoked = false, stale = recovery === "stale_preview", lost = recovery === "lost_confirmation";
      const scope = { days: 90, group_by: "key", key: "" };
      function reply(spec = scope) {
        const { output_format, ...clean } = spec;
        void output_format;
        spec = clean;
        return { answer: "ALPHA: one distinct result has a failed check/rejected review.", project_investigation: { project_id: 1, project: "ALPHA", as_of: "2026-11-04T12:00:00Z",
          spec: { project_id: 1, ...spec }, window: { start: "2026-10-01T00:00:00Z", end_exclusive: "2026-11-01T00:00:00Z", timezone: "UTC" },
          summary: { results: 3, assessed_checks: 2, failed_checks: 1, rejected_reviews: 1, pending_reviews: 1, flagged_results: 1, failure_rate: 50, rejected_work_gates: 0, rerun_work_gates: 0 },
          group_by: spec.group_by, group_label: spec.group_by === "instrument" ? "Linked instrument" : "Result key",
          groups: [{ label: spec.group_by === "instrument" ? "SEQ-1" : "concentration", results: 3, assessed_checks: 2, failed_checks: 1, rejected_reviews: 1, flagged_results: 1, failure_rate: 50 }], group_count: 1,
          failures: [{ id: 31, sample: "S-100", key: "concentration", value: 0, unit: "ng/uL", qc_passed: false, qc_status: "REJECTED", qc_failure_reason: "Recorded control failed", review_note: "Actual reviewer note", instrument: "SEQ-1", run_id: "RUN-1", operator: "maria", url: "/samples/1#result-31" }],
          failure_count: 1, work_gates: [], work_gate_count: 0, notes: ["Rates use assessed checks. Correlation does not establish cause."] }, context: { project_investigation: { project_id: 1, ...spec } } };
      }
      await open(page, context, surface, async (route, path) => {
        if (path.endsWith("/assistant/chat/")) return reply();
        if (path.endsWith("/assistant/project-investigations/1/")) {
          if (revoked) { await route.fulfill({ status: 400, json: { detail: "Project unavailable." } }); return null; }
          const spec = Object.fromEntries(new URL(route.request().url()).searchParams);
          return reply(spec);
        }
        if (path.endsWith("/assistant/project-investigations/1/export/")) {
          const spec = route.request().postDataJSON(); requests.push(spec);
          expect(spec.period).toBe("last_month"); expect(spec.days).toBeUndefined(); expect(spec.group_by).toBe("instrument");
          if (stale) { stale = false; await route.fulfill({ status: 400, json: { detail: "Evidence changed. Review the refreshed scope and request the export again." } }); return null; }
          const id = `report-${actions.size + 1}`, action = { id, confirmation_token: id, status: "PROPOSED", type: "COMPLIANCE_REPORT", result: {}, summary: `Export ALPHA as ${spec.output_format}`,
            preview: { operation: "GENERATE_PROJECT_QC_REPORT", records_affected: 1, project: { label: "ALPHA" }, proposed_values: { output: spec.output_format }, warnings: ["The exact project and window are frozen; evidence is reread at confirmation."] } };
          actions.set(id, action); return { ...reply(spec), pending_action: action };
        }
        if (path.includes("/assistant/actions/")) {
          const id = path.split("/assistant/actions/")[1].split("/")[0], action = actions.get(id);
          if (path.endsWith("/confirm/")) {
            confirmations.push(route.request().postDataJSON()); action.status = "COMPLETED";
            action.result = { operation: "GENERATE_COMPLIANCE_REPORT", succeeded_count: 1, failed_count: 0, download_url: "/api/assistant/artifacts/report-1/download/", checksum_sha256: "verified-checksum", row_count: 1 };
            if (lost) { lost = false; await route.abort("failed"); return null; }
          }
          return action;
        }
        if (path.endsWith("/artifacts/report-1/download/")) {
          await route.fulfill({ contentType: "text/csv", headers: { "content-disposition": 'attachment; filename="qc-evidence.csv"' }, body: "result_id,sample,key\n31,S-100,concentration\n" }); return null;
        }
      });
      await page.getByRole("button", { name: "Investigate project ALPHA QC failures", exact: true }).first().click();
      const panel = page.getByRole("region", { name: "Project QC investigation" });
      await panel.getByLabel("Investigation window").selectOption("last_month");
      await panel.getByLabel("Group evidence by").selectOption("instrument");
      await panel.getByRole("button", { name: "Apply investigation filters", exact: true }).click();
      await expect(panel.getByRole("cell", { name: "SEQ-1", exact: true })).toBeVisible();
      await panel.getByText("Flagged result evidence (1)", { exact: true }).click();
      await expect(panel.getByText("Recorded check reason: Recorded control failed. Review note: Actual reviewer note.", { exact: true })).toBeVisible();
      await panel.getByRole("button", { name: "Preview CSV report", exact: true }).click();
      if (recovery === "stale_preview") {
        await expect(panel.getByText("Evidence changed. Review the refreshed scope and request the export again.", { exact: true })).toBeVisible();
        await panel.getByRole("button", { name: "Preview CSV report", exact: true }).click();
      }
      expect(confirmations).toHaveLength(0);
      await page.getByRole("button", { name: surface === "page" ? "Confirm action" : "Confirm", exact: true }).click();
      await expect(page.getByText("verified-checksum", { exact: false })).toBeVisible();
      const downloadEvent = page.waitForEvent("download");
      await page.getByRole("button", { name: "Download generated file", exact: true }).click();
      const download = await downloadEvent;
      expect(await download.failure()).toBeNull();
      expect(confirmations).toEqual([{ confirm: true }]);
      revoked = true;
      await panel.getByRole("button", { name: "Refresh investigation", exact: true }).click();
      await expect(panel.getByText("Project unavailable.", { exact: true })).toBeVisible();
      await expect(panel.getByRole("cell", { name: "SEQ-1", exact: true })).toHaveCount(0);
    });
  }
}
