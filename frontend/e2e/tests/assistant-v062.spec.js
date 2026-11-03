const { test, expect } = require("@playwright/test");

async function mockChat(page, context) {
  const user = { id: 1, username: "technician", roles: ["tech"] };
  const conversations = [], cancelled = [];
  await context.addCookies([{ name: "csrftoken", value: "test-token", url: "http://127.0.0.1:5173" }]);
  await page.addInitScript(() => {
    const original = window.fetch.bind(window);
    window.chatRequests = [];
    window.fetch = async (url, options = {}) => {
      if (!String(url).includes("/assistant/chat/stream/")) return original(url, options);
      const payload = JSON.parse(options.body);
      window.chatRequests.push(payload);
      const attempt = window.chatRequests.length;
      let timer;
      const stream = new ReadableStream({ start(controller) {
        const send = (kind, data) => controller.enqueue(new TextEncoder().encode(`event: ${kind}\ndata: ${JSON.stringify(data)}\n\n`));
        send("progress", { message: "Reading matching QC records" });
        send("delta", { text: "Preparing a supported explanation" });
        const complete = () => {
          send("complete", {
            answer: "Detailed evidence: R-1 concentration 45.", answer_overview: { text: "Two matching QC results. Open the evidence to review them." },
            context: { read_plan_memory: "new-server-context" }, save_turn_token: "server-issued-turn",
            citations: [{ kind: "result", label: "R-1 concentration", url: "/samples/1#result-1" }],
            read_plan: { steps: [{ operation: "project_results", status: "completed", answer: "R-1 concentration 45; review pending." }] },
          });
          controller.close();
        };
        // Hold the first stream until progress has been observed, or until
        // Stop aborts it. A 500 ms mock raced the assertions on busy runners.
        if (attempt === 1) window.finishAssistantStream = complete;
        else timer = setTimeout(complete, 500);
        options.signal?.addEventListener("abort", () => { clearTimeout(timer); controller.error(new DOMException("Stopped", "AbortError")); });
      }, cancel() { clearTimeout(timer); } });
      return new Response(stream, { headers: { "Content-Type": "text/event-stream" } });
    };
  });
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let body = [];
    if (path.endsWith("/session/")) body = { user, feature_flags: {} };
    else if (path.endsWith("/me/")) body = user;
    else if (path.endsWith("/ui-settings/")) body = { ui_language: "en" };
    else if (path.endsWith("/assistant/status/")) body = { provider: "openlims", suggestions: [], chat_streaming: true, saved_conversations: true };
    else if (path.endsWith("/cancel/")) { cancelled.push(path); body = { status: "stop_requested" }; }
    else if (path.endsWith("/assistant/conversations/")) {
      if (route.request().method() === "POST") {
        const request = route.request().postDataJSON();
        expect(request.turn_tokens).toContain("server-issued-turn");
        conversations.push({ id: "saved-chat", name: request.name });
        body = conversations[0];
      } else body = conversations;
    } else if (path.endsWith("/assistant/conversations/saved-chat/")) {
      if (route.request().method() === "DELETE") { conversations.length = 0; return route.fulfill({ status: 204 }); }
      if (route.request().method() === "PATCH") conversations[0].name = route.request().postDataJSON().name;
      body = { id: "saved-chat", name: conversations[0].name, context: { read_plan_memory: "restored-current-context" },
        history: [{ role: "user", content: "Earlier question" }, { role: "assistant", reply: { answer_overview: { text: "Fresh answer after checking access." } } }] };
    }
    await route.fulfill({ json: body });
  });
  return { conversations, cancelled };
}

for (const surface of ["page", "widget"]) {
  test(`streaming, evidence and saved chat lifecycle work in ${surface}`, async ({ page, context }) => {
    const state = await mockChat(page, context);
    await page.goto(surface === "page" ? "/assistant" : "/samples");
    if (surface === "widget") await page.getByRole("button", { name: "Open OpenLIMS Assistant", exact: true }).click();
    const input = page.getByPlaceholder(surface === "page" ? "Compare samples or projects, graph results, find outliers..." : "Ask OpenLIMS...");
    await input.fill("Show QC failures for project ALPHA");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect(page.getByText("Reading matching QC records", { exact: true })).toBeVisible();
    await expect(page.getByText("Preparing a supported explanation", { exact: true })).toBeVisible();
    await page.evaluate(() => window.finishAssistantStream());
    await expect(page.getByText("Two matching QC results. Open the evidence to review them.", { exact: true })).toBeVisible();
    await page.getByLabel("Answer sources and scope").locator("summary").click();
    await expect(page.getByText("R-1 concentration 45; review pending.", { exact: true })).toBeVisible();
    const saved = page.getByLabel("Saved assistant conversations");
    await saved.locator("summary").click();
    await saved.getByLabel("Conversation name").fill("QC review");
    await saved.getByRole("button", { name: "Save as new chat", exact: true }).click();
    await expect.poll(() => state.conversations.length).toBe(1);
    await expect(saved.getByRole("button", { name: "New unsaved chat", exact: true })).toBeEnabled();
    await saved.getByRole("button", { name: "New unsaved chat", exact: true }).click();
    await saved.getByRole("button", { name: "Open saved chat", exact: true }).click();
    await expect(page.getByText("Fresh answer after checking access.", { exact: true })).toBeVisible();
    await input.fill("Only yesterday");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect.poll(() => page.evaluate(() => window.chatRequests.length)).toBe(2);
    const requests = await page.evaluate(() => window.chatRequests);
    expect(requests[1].context.read_plan_memory).toBe("restored-current-context");
    expect(requests[1].conversation_id).toBe("saved-chat");
    await expect(input).toBeEnabled();
    await saved.getByLabel("Conversation name").fill("Renamed QC review");
    await saved.getByRole("button", { name: "Rename chat", exact: true }).click();
    await expect.poll(() => state.conversations[0].name).toBe("Renamed QC review");
    await expect(saved.getByRole("button", { name: "Delete chat", exact: true })).toBeEnabled();
    await saved.getByRole("button", { name: "Delete chat", exact: true }).click();
    await saved.getByRole("button", { name: "Confirm delete chat", exact: true }).click();
    await expect.poll(() => state.conversations.length).toBe(0);
  });

  test(`Stop cancels the request and Retry uses a new request ID in ${surface}`, async ({ page, context }) => {
    const state = await mockChat(page, context);
    await page.goto(surface === "page" ? "/assistant" : "/samples");
    if (surface === "widget") await page.getByRole("button", { name: "Open OpenLIMS Assistant", exact: true }).click();
    await page.getByPlaceholder(surface === "page" ? "Compare samples or projects, graph results, find outliers..." : "Ask OpenLIMS...").fill("Show results for project ALPHA");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect(page.getByText("Reading matching QC records", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Stop", exact: true }).click();
    await expect.poll(() => state.cancelled.length).toBe(1);
    await page.getByRole("button", { name: "Retry last question", exact: true }).click();
    await expect(page.getByText("Two matching QC results. Open the evidence to review them.", { exact: true })).toBeVisible();
    const requests = await page.evaluate(() => window.chatRequests);
    expect(requests).toHaveLength(2);
    expect(requests[0].request_id).not.toBe(requests[1].request_id);
    expect(state.cancelled[0]).toContain(requests[0].request_id);
  });
}
