import assert from "node:assert/strict";
import { test } from "node:test";
import { build } from "esbuild";

const bundle = await build({ entryPoints: [new URL("../src/assistantTransport.js", import.meta.url).pathname], bundle: true, write: false, format: "esm", platform: "node" });
const { streamChat, assistantMessage } = await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].text).toString("base64")}`);
globalThis.document = { cookie: "csrftoken=test-token" };
const encoder = new TextEncoder();

function response(chunks) {
  return new Response(new ReadableStream({ start(controller) { for (const chunk of chunks) controller.enqueue(encoder.encode(chunk)); controller.close(); } }),
    { headers: { "Content-Type": "text/event-stream" } });
}

test("SSE frames survive chunk boundaries, multiline transport and UTF-8", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => response(['event: progress\r\ndata: {"message":"Read', 'ing records"}\r\n\r\nevent: delta\ndata: {"text":"Español"}\n\n',
    'event: complete\ndata: {"answer":"Done", "context":{}}\n\n']);
  try {
    const events = [];
    const result = await streamChat({ message: "Question" }, { onEvent: (kind, data) => events.push([kind, data]) });
    assert.equal(result.answer, "Done");
    assert.deepEqual(events.map(([kind]) => kind), ["progress", "delta", "complete"]);
    assert.equal(events[1][1].text, "Español");
  } finally { globalThis.fetch = original; }
});

test("truncated, failed and cancelled streams are never accepted as complete answers", async () => {
  const original = globalThis.fetch;
  try {
    for (const frame of ['event: delta\ndata: {"text":"Incomplete"}\n\n', 'event: error\ndata: {"message":"Failed"}\n\n']) {
      globalThis.fetch = async () => response([frame]);
      await assert.rejects(streamChat({}, {}));
    }
    globalThis.fetch = async () => response(['event: cancelled\ndata: {}\n\n']);
    await assert.rejects(streamChat({}, {}), { name: "AbortError" });
  } finally { globalThis.fetch = original; }
});

test("the concise overview is displayed while evidence and save references remain available", () => {
  const mapped = assistantMessage({ answer: "Long evidence", answer_overview: { text: "Short supported answer" }, read_plan: { steps: [] }, save_turn_token: "server-issued" });
  assert.equal(mapped.content, "Short supported answer");
  assert.deepEqual(mapped.readPlan, { steps: [] });
  assert.equal(mapped.saveToken, "server-issued");
});
