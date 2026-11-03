const { test, expect } = require("@playwright/test");

for (const surface of ["page", "widget"]) {
  for (const outcome of ["completed", "failed", "lost_response"]) {
    test(`registration task preview and ${outcome} receipt in ${surface}`, async ({ page, context }) => {
      const requests = [], confirmations = [], lookups = [];
      const user = { id: 1, username: "tech", roles: ["tech"] };
      const action = { id: "task-1", type: "CREATE_SAMPLES", status: "PROPOSED", confirmation_token: "task-token",
        summary: "Register 2 DNA samples in ALPHA and assign them to maria", result: {},
        preview: { operation: "Register and assign samples", records_affected: 2, project: { label: "ALPHA" },
          proposed_values: { sample_type: "DNA", assigned_to: "maria" },
          samples: ["ALPHA-S-0001", "ALPHA-S-0002"].map(sample_id => ({ sample_id, current: { record: "Does not exist" }, proposed: { assigned_to: "maria" } })) } };
      await context.addCookies([{ name: "csrftoken", value: "test-token", url: "http://127.0.0.1:5173" }]);
      await page.route("**/api/**", async route => {
        const path = new URL(route.request().url()).pathname;
        let body = [];
        if (path.endsWith("/session/")) body = { user, feature_flags: {} };
        else if (path.endsWith("/me/")) body = user;
        else if (path.endsWith("/ui-settings/")) body = { ui_language: "en" };
        else if (path.endsWith("/assistant/status/")) body = { provider: "openlims", suggestions: ["Register samples and assign them"] };
        else if (path.endsWith("/assistant/chat/")) {
          const payload = route.request().postDataJSON(); requests.push(payload);
          if (requests.length === 1) body = { answer: "How many samples?", clarification: { required: true }, context: { registration_task: "signed-draft-1" } };
          else if (requests.length === 2) body = { answer: "Which project?", clarification: { required: true }, context: { registration_task: "signed-draft-2" } };
          else if (requests.length === 3) body = { answer: "Review the sample IDs and assignee, then confirm.", pending_action: action, context: { project_id: 1 } };
          else body = { answer: "Continuing with the created samples.", context: payload.context };
        } else if (path.endsWith("/task-token/confirm/")) {
          confirmations.push(route.request().postDataJSON());
          if (outcome === "failed") {
            action.status = "FAILED"; action.error_message = "The intake form changed. Request a fresh preview.";
            return route.fulfill({ status: 400, json: action });
          }
          action.status = "COMPLETED";
          action.result = { operation: "REGISTER_AND_ASSIGN_SAMPLES", succeeded_count: 2, failed_count: 0,
            message: "Registered 2 DNA samples in ALPHA and assigned them to maria.", context: { sample_ids: [41, 42], project_id: 1 } };
          if (outcome === "lost_response") return route.abort("failed");
          body = action;
        } else if (path.endsWith("/task-token/")) { lookups.push(path); body = action; }
        await route.fulfill({ json: body });
      });
      await page.goto(surface === "page" ? "/assistant" : "/samples");
      if (surface === "widget") await page.getByRole("button", { name: "Open OpenLIMS Assistant", exact: true }).click();
      await page.getByRole("button", { name: "Register samples and assign them", exact: true }).first().click();
      const input = page.getByPlaceholder(surface === "page" ? "Compare samples or projects, graph results, find outliers..." : "Ask OpenLIMS...");
      await expect(page.getByText("How many samples?", { exact: true })).toBeVisible();
      await input.fill("2"); await page.getByRole("button", { name: "Send", exact: true }).click();
      await expect(page.getByText("Which project?", { exact: true })).toBeVisible();
      expect(requests[1].context.registration_task).toBe("signed-draft-1");
      await input.fill("ALPHA"); await page.getByRole("button", { name: "Send", exact: true }).click();
      const confirm = page.getByRole("button", { name: surface === "page" ? "Confirm action" : "Confirm", exact: true });
      await expect(confirm).toBeVisible();
      await expect(page.getByRole("cell", { name: "ALPHA-S-0001", exact: true })).toBeVisible();
      expect(confirmations).toHaveLength(0);
      expect(requests[2].context.registration_task).toBe("signed-draft-2");
      await confirm.click();
      await expect(page.getByText(outcome === "failed" ? "FAILED" : "COMPLETED", { exact: true })).toBeVisible();
      await expect(confirm).toHaveCount(0);
      expect(confirmations).toEqual([{ confirm: true }]);
      if (outcome === "failed") {
        await expect(page.getByText(action.error_message, { exact: true })).toBeVisible();
        expect(lookups).toHaveLength(1);
      } else {
        await expect(page.getByText(action.result.message, { exact: true })).toBeVisible();
        await input.fill("Show my work"); await page.getByRole("button", { name: "Send", exact: true }).click();
        await expect.poll(() => requests.length).toBe(4);
        expect(requests[3].context.sample_ids).toEqual([41, 42]);
        if (outcome === "lost_response") expect(lookups).toHaveLength(1);
      }
    });
  }
}
