const { test, expect } = require("@playwright/test");

for (const surface of ["page", "widget"]) {
  for (const recovery of ["none", "invalid_file", "lost_preview"]) {
    test(`instrument upload, ${recovery} recovery and receipt in ${surface}`, async ({ page, context }) => {
      const user = { id: 1, username: "tech", roles: ["tech"] };
      const mapping = { source_column: "concentration", target_key: "concentration", value_type: "NUMBER", min_value: 0, max_value: 100 };
      const uploads = [], confirmations = [], chat = [], revalidations = [], resumes = [], confirmationPaths = [];
      let queuedReads = 0, prepared = false, kept = false, resumed = false;
      const action = { id: "upload-action", type: "QUEUE_IMPORT", confirmation_token: "import-token", status: "PROPOSED", summary: "Import validated rows from SEQ-1", result: {},
        preview: { title: "Validated instrument import", operation: "Import measurement rows", instrument_import: true, import_job_id: 7,
          project: { label: "ALPHA" }, records_affected: 2, proposed_values: { "Rows received": 4, "Rows rejected": 1 }, records: [] } };
      const job = { id: 7, instrument: "SEQ-1", project: "ALPHA", run_id: "RUN-7", filename: "sequencer.csv", status: "PENDING", state: "awaiting_confirmation",
        mappings: [mapping], unmapped_columns: [], row_report: [{ row: 1, sample_id: "S-1", status: "ready", reason: "" },
          { row: 2, sample_id: "S-1", status: "duplicate", reason: "Exact repeated row" },
          { row: 3, sample_id: "S-2", status: "rejected", reason: "Invalid numeric value" },
          { row: 4, sample_id: "S-3", status: "ready", reason: "" }], report_total: 4,
        counts: { rows_received: 4, rows_to_import: 2, rows_rejected: 1, duplicates_skipped: 1 },
        planned_counts: { rows_received: 4 }, download_url: "/api/assistant/instrument-imports/7/report/", action };
      job.can_revalidate = true;
      const reply = () => ({ answer: "Review the instrument mapping and all row counts, then confirm.", ...(action.status === "PROPOSED" ? { pending_action: action } : {}),
        instrument_import_job: job, context: { instrument_import_job_id: 7 } });
      await context.addCookies([{ name: "csrftoken", value: "test-token", url: "http://127.0.0.1:5173" }]);
      await page.route("**/api/**", async route => {
        const path = new URL(route.request().url()).pathname;
        let body = [];
        if (path.endsWith("/session/")) body = { user, feature_flags: {} };
        else if (path.endsWith("/me/")) body = user;
        else if (path.endsWith("/ui-settings/")) body = { ui_language: "en" };
        else if (path.endsWith("/assistant/status/")) body = { provider: "openlims", suggestions: ["Import instrument data"], instrument_import_uploads: true };
        else if (path.endsWith("/instrument-profiles/")) body = [{ id: 3, code: "SEQ-1", name: "Sequencer", delimiter: ",", sample_id_column: "sample_id", column_mappings: [mapping] }];
        else if (path.endsWith("/projects/")) body = [{ id: 5, code: "ALPHA", name: "Alpha project" }];
        else if (path.endsWith("/assistant/chat/")) {
          chat.push(route.request().postDataJSON()); body = { answer: "Attach the instrument export below.", instrument_import_form: { project_id: 5 }, context: {} };
        } else if (path.endsWith("/assistant/instrument-imports/")) {
          const payload = route.request().postData(); uploads.push(payload);
          expect(route.request().headers()["content-type"]).toContain("multipart/form-data");
          expect(payload).toContain('filename="sequencer.csv"'); expect(payload).toContain("RUN-7");
          kept = payload.includes('name="skip_duplicates"\r\n\r\nfalse');
          if (kept) { job.counts.rows_to_import = 3; job.counts.duplicates_skipped = 0; }
          if (recovery === "invalid_file" && uploads.length === 1) return route.fulfill({ status: 400, json: {
            detail: "No rows are importable. Correct the file and validate again.", validation: { counts: { rows_received: 1, rows_rejected: 1 }, row_report: [{ row: 1, reason: "Invalid NUMBER" }] } } });
          prepared = true;
          if (recovery === "lost_preview" && uploads.length === 1) return route.abort("failed");
          body = reply();
        } else if (path.endsWith("/assistant/instrument-imports/7/revalidate/")) {
          revalidations.push(route.request().postDataJSON()); action.id = "upload-action-2"; action.confirmation_token = "import-token-2"; body = reply();
        } else if (path.endsWith("/assistant/instrument-imports/7/resume/")) {
          resumes.push(route.request().postDataJSON()); resumed = true; job.error = ""; body = reply();
        } else if (/\/import-token(?:-2)?\/confirm\/$/.test(path)) {
          confirmationPaths.push(path);
          confirmations.push(route.request().postDataJSON()); action.status = "QUEUED";
          action.result = { operation: "IMPORT_INSTRUMENT_DATA", import_job_id: 7 }; job.state = "queued_or_running";
          job.can_revalidate = false; job.can_resume = recovery === "lost_preview";
          if (recovery === "lost_preview") job.error = "Worker delivery could not be verified. Use Resume queued import to try again.";
          body = action;
        } else if (path.endsWith("/assistant/instrument-imports/7/")) {
          if (action.status === "QUEUED" && (recovery !== "lost_preview" || resumed) && ++queuedReads >= 2) {
            job.status = action.status = "COMPLETED"; job.state = "completed";
            job.counts = { ...job.counts, rows_imported: kept ? 3 : 2, rows_accounted: 4, results_created: kept ? 3 : 2 };
            action.result = { ...action.result, ...job.counts }; job.can_resume = false;
          }
          body = job;
        } else if (path.endsWith("/assistant/instrument-imports/7/report/")) {
          return route.fulfill({ contentType: "text/csv", headers: { "Content-Disposition": 'attachment; filename="instrument-import-7.csv"' }, body: "row,status\n1,imported\n2,duplicate\n3,rejected\n4,imported\n" });
        }
        await route.fulfill({ json: body });
      });
      await page.goto(surface === "page" ? "/assistant" : "/samples");
      if (surface === "widget") await page.getByRole("button", { name: "Open OpenLIMS Assistant", exact: true }).click();
      await page.getByRole("button", { name: "Import instrument data", exact: true }).first().click();
      const form = page.getByRole("form", { name: "Instrument upload in chat" });
      await form.getByLabel("Import instrument", { exact: true }).selectOption("3");
      await expect(form.getByRole("table", { name: "Instrument column mapping" })).toBeVisible();
      await expect(form.getByLabel("Import project", { exact: true })).toHaveValue("5");
      await form.getByLabel("Instrument run ID", { exact: true }).fill("RUN-7");
      if (surface === "widget") await form.getByLabel("Skip exact repeated rows within this file").uncheck();
      await form.getByLabel("Instrument data file", { exact: true }).setInputFiles({ name: "sequencer.csv", mimeType: "text/csv", buffer: Buffer.from("sample_id,concentration\nS-1,5\nS-1,5\nS-2,bad\nS-3,0\n") });
      await form.getByRole("button", { name: "Validate file and preview import", exact: true }).click();
      if (recovery !== "none") {
        await expect(form.getByRole("alert")).toContainText(recovery === "lost_preview" ? "same run ID" : "No rows are importable");
        await form.getByRole("button", { name: "Validate file and preview import", exact: true }).click();
      }
      const confirm = page.getByRole("button", { name: surface === "page" ? "Confirm action" : "Confirm", exact: true });
      await expect(confirm).toBeVisible(); expect(prepared).toBe(true); expect(confirmations).toHaveLength(0);
      expect(chat).toHaveLength(1); expect(chat[0]).not.toHaveProperty("uploaded_file");
      if (recovery === "invalid_file") {
        await page.getByLabel("Instrument import receipt").getByRole("button", { name: "Revalidate and preview", exact: true }).click();
        await expect.poll(() => revalidations.length).toBe(1);
        await expect(confirm).toBeEnabled(); expect(revalidations).toEqual([{}]);
      }
      await confirm.click();
      const receipt = page.getByLabel("Instrument import receipt");
      if (recovery === "lost_preview") {
        await receipt.getByRole("button", { name: "Resume queued import", exact: true }).click();
        await expect.poll(() => resumes.length).toBe(1);
        expect(resumes).toEqual([{}]);
      }
      await expect(receipt.getByText("Import #7: completed", { exact: true })).toBeVisible();
      await expect(receipt.getByRole("row", { name: `Rows imported ${surface === "widget" ? 3 : 2}`, exact: true })).toBeVisible();
      await expect(receipt.getByRole("row", { name: "Rows accounted for 4", exact: true })).toBeVisible();
      await expect(confirm).toHaveCount(0); expect(confirmations).toEqual([{ confirm: true }]);
      if (recovery === "invalid_file") expect(confirmationPaths[0]).toContain("import-token-2");
      const download = page.waitForEvent("download");
      await receipt.getByRole("button", { name: "Download row report", exact: true }).click();
      expect((await download).suggestedFilename()).toBe("instrument-import-7.csv");
    });
  }
}
