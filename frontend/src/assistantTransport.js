import { apiPost, apiPostResponse } from "./api";

export async function streamChat(payload, { signal, onEvent }) {
  const response = await apiPostResponse("/api/assistant/chat/stream/", payload, { signal });
  if (!response.ok) throw new Error(`Assistant request failed: ${response.status}`);
  if (!response.headers.get("Content-Type")?.includes("text/event-stream")) throw new Error("The assistant stream was unavailable.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      buffer = buffer.replaceAll("\r\n", "\n");
      if (buffer.length > 2_000_000) throw new Error("Assistant response exceeded its size limit.");
      let boundary;
      while ((boundary = buffer.indexOf("\n\n")) >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const kind = frame.split("\n").find(line => line.startsWith("event:"))?.slice(6).trim();
        const raw = frame.split("\n").filter(line => line.startsWith("data:")).map(line => line.slice(5).trim()).join("\n");
        if (!kind || !raw) continue;
        const data = JSON.parse(raw);
        onEvent?.(kind, data);
        if (kind === "complete") return data;
        if (kind === "cancelled") throw new DOMException("Request stopped.", "AbortError");
        if (kind === "error") throw new Error(data.message || "Assistant request failed.");
      }
      if (done) throw new Error("Assistant connection ended before the answer completed. Please retry.");
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}

export function requestChat(payload, options) {
  return options.streaming ? streamChat(payload, options) : apiPost("/api/assistant/chat/", payload, { signal: options.signal });
}

export function assistantMessage(data) {
  return {
    role: "assistant", content: data.answer_overview?.text || data.project_workflows?.summary || data.answer || "No answer returned.",
    draft: data.draft || null, interpretation: data.interpretation || null,
    citations: data.citations || [], readPlan: data.read_plan || null, overview: data.answer_overview || null,
    projectWorkflows: data.project_workflows || null, queryExplanation: data.query_explanation || null,
    links: data.links || [], suggestions: data.suggestions || [], chart: data.chart || null,
    comparison: data.comparison || null, investigation: data.investigation || null,
    clarification: data.clarification || null, pendingAction: data.pending_action || null,
    instrumentImportForm: data.instrument_import_form || null, instrumentImportJob: data.instrument_import_job || null,
    workflowPlan: data.workflow_plan || null,
    dailyWork: data.daily_work || null, projectInvestigation: data.project_investigation || null,
    labOperationForm: data.lab_operation_form || null,
    actionError: data.action_error || "", llmError: data.llm_error || "", mode: data.mode || "openlims",
    modelInfo: data.model_info || { provider: "openlims", display_name: "OpenLIMS Rules" },
    interactionId: data.interaction_id || "", saveToken: data.save_turn_token || null,
  };
}
