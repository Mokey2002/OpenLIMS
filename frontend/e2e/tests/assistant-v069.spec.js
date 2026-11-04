const { test, expect } = require("@playwright/test");

for (const surface of ["page", "widget"]) {
  for (const recovery of ["none", "stale_preview", "lost_confirmation"]) {
    test(`guided preparation, human QC and ${recovery} recovery in ${surface}`, async ({ page, context }) => {
      const user = { id: 1, username: "operator", roles: ["tech", "qc_reviewer"] };
      const requests = [], proposals = [], confirmed = [];
      const actions = new Map();
      const state = { started: false, measured: false, form: false, completed: false, approved: false, assigned: false, denied: false, revision: 1 };
      let stale = recovery === "stale_preview", lost = recovery === "lost_confirmation";
      function plan() {
        const step = { id: 11, position: 1, name: "Extraction", status: state.approved ? "COMPLETED" : state.completed ? "AWAITING_QC" : "READY",
          work_item_id: 21, work_status: state.completed ? "COMPLETED" : "PENDING", assigned_to: state.assigned ? "maria" : null,
          requires_qc: true, qc_status: state.approved ? "APPROVED" : "PENDING_REVIEW", reason: state.approved ? "Recorded as completed." : state.completed ? "A human reviewer must decide the QC gate." : "Record the required measurements and form.",
          waiting_for: [], missing_fields: [...(state.measured || recovery === "lost_confirmation" ? [] : ["concentration"]), ...(state.form ? [] : ["form:checked"])],
          required_fields: recovery === "lost_confirmation" ? [] : [{ key: "concentration", value_type: "NUMBER", required: true }],
          form_schema: { fields: [{ key: "checked", en: "Inspection recorded", es: "Inspección registrada", type: "boolean", required: true }] },
          form_values: state.form ? { checked: false } : {}, results: state.measured ? [{ id: 31, key: "concentration", value: 5, value_type: "NUMBER", qc_status: "PENDING_REVIEW", qc_passed: null }] : [],
          can_assign: !state.completed, can_record: !state.completed, can_complete: (state.measured || recovery === "lost_confirmation") && state.form && !state.completed,
          can_review: state.completed && !state.approved, can_approve: true, approval_blocker: "", is_sequencing: false };
        const seq = { ...step, id: 12, position: 2, name: "Sequencing", status: state.approved ? "READY" : "BLOCKED", work_item_id: state.approved ? 22 : null,
          requires_qc: false, work_status: state.approved ? "PENDING" : null, reason: state.approved ? "Sequencing step available." : "Waiting for dependency step 1.",
          waiting_for: state.approved ? [] : [1], missing_fields: [], required_fields: [], form_schema: {}, form_values: {}, results: [],
          can_assign: false, can_record: false, can_complete: false, can_review: false, is_sequencing: true };
        return { sample_id: 1, sample_code: "S-100", sample_status: "RECEIVED", run: state.started ? { id: 5, code: "SEQ-PREP", status: "ACTIVE" } : null,
          last_run: null, plan_digest: String(state.revision).padStart(64, "0"), readiness: state.approved ? "available" : state.started ? "blocked" : "needs_workflow",
          summary: state.approved ? "The configured sequencing step is available. This does not start an instrument." : state.started ? "Sequencing is blocked by recorded prerequisites and QC." : "Choose the configured workflow template.",
          read_only: false, steps: state.started ? [step, seq] : [], templates: state.started ? [] : [{ id: 7, code: "SEQ-PREP", name: "Sequencing preparation" }],
          notes: ["Every change requires preview and confirmation. Individual result QC remains separate."] };
      }
      function pending(operation) {
        const id = `workflow-${actions.size + 1}`;
        const action = { id, type: "WORK_ITEM_OPERATION", confirmation_token: id, status: "PROPOSED", summary: `Review ${operation}`, result: {},
          preview: { operation, records_affected: 1, project: { label: "ALPHA" }, proposed_values: { operation }, warnings: ["Nothing changes before confirmation."] } };
        actions.set(id, { action, operation });
        return action;
      }
      const reply = action => ({ answer: "Review the proposed workflow change.", workflow_plan: plan(), pending_action: action,
        context: { workflow_guide: "signed-workflow-context", sample_id: 1, sample_code: "S-100" } });
      await context.addCookies([{ name: "csrftoken", value: "test-token", url: "http://127.0.0.1:5173" }]);
      await page.route("**/api/**", async route => {
        const request = route.request(), path = new URL(request.url()).pathname;
        let body = [];
        if (path.endsWith("/session/")) body = { user, feature_flags: {} };
        else if (path.endsWith("/me/")) body = user;
        else if (path.endsWith("/ui-settings/")) body = { ui_language: "en" };
        else if (path.endsWith("/assistant/status/")) body = { provider: "openlims", suggestions: ["Help me prepare a sample for sequencing"] };
        else if (path.endsWith("/assistant/chat/")) {
          const payload = request.postDataJSON(); requests.push(payload);
          if (payload.message === "Help me prepare a sample for sequencing") body = { answer: "Which sample should we prepare?", context: { workflow_guide: { awaiting_sample: true } } };
          else if (payload.message.startsWith("Assign work item")) body = reply(pending("GUIDED_ASSIGN"));
          else if (payload.message.startsWith("Add result")) body = reply(pending("GUIDED_RESULT"));
          else body = reply();
        } else if (path.endsWith("/assistant/workflows/1/")) {
          if (state.denied) return route.fulfill({ status: 404, json: { detail: "Not found." } });
          body = plan();
        } else if (path.endsWith("/assistant/workflows/1/actions/")) {
          const payload = request.postDataJSON(); proposals.push(payload);
          expect(payload.plan_digest).toBe(plan().plan_digest);
          if (payload.operation === "WORKFLOW_FORM" && stale) {
            stale = false; state.revision++;
            return route.fulfill({ status: 400, json: { detail: "The workflow changed. Refresh the checklist and request a fresh preview." } });
          }
          body = reply(pending(payload.operation));
        } else if (path.includes("/assistant/actions/")) {
          const id = path.split("/assistant/actions/")[1].split("/")[0], entry = actions.get(id);
          if (path.endsWith("/confirm/")) {
            confirmed.push(request.postDataJSON());
            const mapping = { WORKFLOW_START: "started", GUIDED_ASSIGN: "assigned", GUIDED_RESULT: "measured", WORKFLOW_FORM: "form", WORKFLOW_COMPLETE: "completed", WORKFLOW_REVIEW: "approved" };
            state[mapping[entry.operation]] = true; state.revision++;
            entry.action.status = "COMPLETED"; entry.action.result = { operation: entry.operation, succeeded_count: 1, failed_count: 0, message: `Completed ${entry.operation}.` };
            if (entry.operation === "WORKFLOW_COMPLETE" && lost) { lost = false; return route.abort("failed"); }
          }
          body = entry.action;
        }
        return route.fulfill({ json: body });
      });
      await page.goto(surface === "page" ? "/assistant" : "/samples");
      if (surface === "widget") await page.getByRole("button", { name: "Open OpenLIMS Assistant", exact: true }).click();
      await page.getByRole("button", { name: "Help me prepare a sample for sequencing", exact: true }).first().click();
      await expect(page.getByText("Which sample should we prepare?", { exact: true })).toBeVisible();
      const input = page.getByPlaceholder(surface === "page" ? "Compare samples or projects, graph results, find outliers..." : "Ask OpenLIMS...");
      await input.fill("S-100"); await page.getByRole("button", { name: "Send", exact: true }).click();
      const guide = page.getByRole("region", { name: "Guided sequencing preparation" });
      await expect(guide).toBeVisible();
      await guide.getByLabel("Configured pipeline template").selectOption("7");
      await guide.getByRole("button", { name: "Preview pipeline start", exact: true }).click();
      expect(state.started).toBe(false);
      async function confirm() {
        await page.getByRole("button", { name: surface === "page" ? "Confirm action" : "Confirm", exact: true }).click();
        await expect(page.getByRole("button", { name: surface === "page" ? "Confirm action" : "Confirm", exact: true })).toHaveCount(0);
      }
      await confirm();
      const first = guide.getByLabel("Workflow step 1", { exact: true });
      await first.getByRole("button", { name: "Assign work", exact: true }).click();
      await first.getByLabel("Exact assignee username").fill("maria");
      await first.getByRole("button", { name: "Preview assignment", exact: true }).click();
      expect(state.assigned).toBe(false); await confirm();
      await first.getByRole("button", { name: "Record result", exact: true }).click();
      if (recovery === "lost_confirmation") await first.getByLabel("Result key", { exact: true }).fill("concentration");
      else await first.getByLabel("Result key", { exact: true }).selectOption("concentration");
      await first.getByLabel("Actual measured value").fill("5");
      await first.getByRole("button", { name: "Preview result", exact: true }).click();
      expect(state.measured).toBe(false); await confirm();
      async function enterForm() {
        await first.getByRole("button", { name: "Record step form", exact: true }).click();
        await first.getByLabel("Inspection recorded", { exact: false }).selectOption("false");
        await first.getByLabel("Reason (10 characters minimum)", { exact: true }).fill("Recorded the actual inspection.");
        await first.getByRole("button", { name: "Preview step form", exact: true }).click();
      }
      await enterForm();
      if (recovery === "stale_preview") {
        await expect(guide.getByText("The workflow changed. Refresh the checklist and request a fresh preview.", { exact: true })).toBeVisible();
        expect(state.form).toBe(false);
        await enterForm();
      }
      expect(state.form).toBe(false); await confirm();
      await first.getByRole("button", { name: "Preview work completion", exact: true }).click();
      expect(state.completed).toBe(false); await confirm();
      await expect(first.getByText("AWAITING_QC", { exact: true })).toBeVisible();
      await first.getByRole("button", { name: "Review workflow QC", exact: true }).click();
      await first.getByLabel("Human QC decision").selectOption("APPROVED");
      await first.getByLabel("QC review reason", { exact: true }).fill("Independently reviewed the recorded measurements.");
      await first.getByRole("button", { name: "Preview QC decision", exact: true }).click();
      expect(state.approved).toBe(false); await confirm();
      await expect(guide.getByText("The configured sequencing step is available. This does not start an instrument.", { exact: true })).toBeVisible();
      expect(confirmed).toHaveLength(6);
      expect(proposals.find(item => item.operation === "WORKFLOW_FORM").values).toEqual({ checked: false });
      expect(requests.find(item => item.message.startsWith("Add result")).context.workflow_guide).toBe("signed-workflow-context");
      expect(proposals.find(item => item.operation === "WORKFLOW_REVIEW").reason).toContain("Independently");
      state.denied = true;
      await guide.getByRole("button", { name: "Refresh preparation checklist", exact: true }).click();
      await expect(guide.getByText("Workflow status is unavailable. Check your connection and access, then refresh.", { exact: true })).toBeVisible();
      await expect(guide.getByText("Extraction", { exact: true })).toHaveCount(0);
    });
  }
}
