import { useEffect, useRef, useState } from "react";
import { apiGetResponse, apiPostResponse } from "../api";

export function useAssistantPanel(url, field, initial, revision, onContext) {
  const [panel, setPanel] = useState(initial), [error, setError] = useState(""), [tick, setTick] = useState(0), [loaded, setLoaded] = useState(null);
  const context = useRef(onContext), key = `${url}:${revision}:${tick}`;
  useEffect(() => { context.current = onContext; }, [onContext]);
  useEffect(() => {
    const controller = new AbortController();
    apiGetResponse(url, { signal: controller.signal }).then(async response => {
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Check the selected filters: ${JSON.stringify(data)}`);
      return data;
    }).then(data => {
      if (controller.signal.aborted) return;
      if (!data[field]) throw new Error(data.answer || "The requested records are unavailable.");
      setPanel(data[field]); setError(""); setLoaded(key); context.current?.(data.context || {});
    }).catch(error => {
      if (!controller.signal.aborted && error.name !== "AbortError") {
        setPanel(null); setLoaded(key); setError(error.status === 0 || error instanceof TypeError || error instanceof SyntaxError ? "Records are unavailable. Check your connection and current access, then refresh." : error.message);
      }
    });
    return () => controller.abort();
  }, [url, field, key]);
  return { panel, error, loading: loaded !== key, refresh: () => setTick(value => value + 1) };
}

export function useAssistantProposal(onPrepared, onBusy) {
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const controller = useRef(null);
  useEffect(() => () => { controller.current?.abort(); onBusy?.(false); }, [onBusy]);
  async function submit(url, payload) {
    const abort = new AbortController(); controller.current = abort;
    setBusy(true); setError(""); onBusy?.(true);
    try {
      const response = await apiPostResponse(url, payload, { signal: abort.signal });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || `Check the entered fields: ${JSON.stringify(data)}`);
      onPrepared(data); return true;
    } catch (error) {
      if (error.name !== "AbortError") setError(error.status === 0 || error instanceof TypeError ? "The preview response was interrupted. Refresh the records and request a new preview." : error.message);
      return false;
    } finally { setBusy(false); onBusy?.(false); }
  }
  return { busy, error, submit };
}
