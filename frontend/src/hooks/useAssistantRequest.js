import { useCallback, useEffect, useRef, useState } from "react";
import { apiPost } from "../api";
import { requestChat } from "../assistantTransport";

export default function useAssistantRequest() {
  const active = useRef(null);
  const [state, setState] = useState({ progress: "", partial: "", status: "idle", lastMessage: "" });
  const stop = useCallback(() => {
    const request = active.current;
    if (!request) return;
    active.current = null;
    request.controller.abort();
    if (request.streaming) apiPost(`/api/assistant/chat/requests/${request.id}/cancel/`, {}).catch(() => {});
    setState(old => ({ ...old, status: "stopped", progress: "Request stopped. An active server call may take a moment to finish.", partial: "" }));
  }, []);
  useEffect(() => () => {
    const request = active.current;
    if (request) {
      request.controller.abort();
      if (request.streaming) apiPost(`/api/assistant/chat/requests/${request.id}/cancel/`, {}).catch(() => {});
    }
  }, []);
  async function run(payload, { streaming = false } = {}) {
    const request = { id: crypto.randomUUID(), controller: new AbortController(), streaming };
    active.current = request;
    setState({ progress: "Starting request…", partial: "", status: "running", lastMessage: payload.message });
    try {
      const data = await requestChat({ ...payload, request_id: request.id }, {
        streaming, signal: request.controller.signal,
        onEvent(kind, data) {
          if (active.current !== request) return;
          if (kind === "progress") setState(old => ({ ...old, progress: data.message }));
          if (kind === "delta") setState(old => ({ ...old, partial: (old.partial + data.text).slice(0, 48000) }));
        },
      });
      if (active.current !== request) throw new DOMException("Request stopped.", "AbortError");
      setState(old => ({ ...old, status: "complete", progress: "", partial: "" }));
      return data;
    } catch (error) {
      if (active.current === request) setState(old => ({ ...old, status: error.name === "AbortError" ? "stopped" : "error", partial: "" }));
      throw error;
    } finally {
      if (active.current === request) active.current = null;
    }
  }
  function reset() {
    if (!active.current) setState({ progress: "", partial: "", status: "idle", lastMessage: "" });
  }
  return { ...state, run, stop, reset };
}
