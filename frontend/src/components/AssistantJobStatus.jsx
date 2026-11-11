import { useEffect, useRef, useState } from "react";
import { Alert, Badge, Button } from "react-bootstrap";
import { Link, useLocation } from "react-router-dom";
import { apiGet } from "../api";
import { useLanguage } from "../i18n";

export default function AssistantJobStatus({ action, actionId, initial, onActionUpdate, autoRefresh = true }) {
  const { t } = useLanguage();
  const location = useLocation();
  const id = actionId || action?.id;
  const [response, setResponse] = useState(null);
  const [error, setError] = useState(null);
  const [refresh, setRefresh] = useState(0);
  const callback = useRef(onActionUpdate);
  useEffect(() => { callback.current = onActionUpdate; }, [onActionUpdate]);
  const eligible = Boolean(id && (!action || ["QUEUED", "FAILED"].includes(action.status)));

  useEffect(() => {
    if (!eligible || (!autoRefresh && refresh === 0)) return;
    const controller = new AbortController();
    let timer, previous = "";
    async function load() {
      try {
        const data = await apiGet(`/api/assistant/jobs/${id}/`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        if (data.id !== id || !data.status) throw new Error("Invalid task receipt");
        setResponse(data); setError(null);
        const signature = JSON.stringify([data.status, data.health, data.result]);
        if (callback.current && signature !== previous) callback.current(data);
        previous = signature;
        if (autoRefresh && data.status === "QUEUED") timer = window.setTimeout(load, 10000);
      } catch {
        if (!controller.signal.aborted) setError({ id, text: "Could not refresh this task. Your access may have changed, or the service may be unavailable." });
      }
    }
    timer = window.setTimeout(load, 0);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [id, eligible, refresh, autoRefresh]);

  if (!eligible) return null;
  const current = response?.id === id ? response : action || initial;
  const health = current?.health;
  const failed = current?.status === "FAILED", completed = current?.status === "COMPLETED";
  return <Alert variant={failed ? "danger" : health?.stalled ? "warning" : completed ? "success" : "info"} className="mt-2" aria-label={t("Assistant task progress")}>
    <div className="d-flex gap-2 align-items-center mb-2"><strong>{t(failed ? "Assistant task failed" : completed ? "Assistant task completed" : health?.stalled ? "Assistant task needs attention" : "Assistant task progress")}</strong>
      {current?.status && <Badge bg={failed ? "danger" : completed ? "success" : "secondary"}>{t(current.status.toLowerCase().replace(/^./, letter => letter.toUpperCase()))}</Badge>}</div>
    {current?.summary && <p translate="no">{current.summary}</p>}
    {health && <>
      <div><strong>{t("Current step")}: </strong>{t(health.current_step)}</div>
      <div><strong>{t("Last completed step")}: </strong><span translate="no">{t(health.last_completed_step)}</span></div>
      {health.progress_current !== null && health.progress_current !== undefined && <div>{t("Rows processed")}: {health.progress_current} / {health.progress_total ?? "—"}</div>}
      {health.last_progress_at && <div className="feed-meta">{t("Last progress")}: {new Date(health.last_progress_at).toLocaleString()}</div>}
      {health.failure_reason && <p className="mt-2" translate="no">{health.failure_reason}</p>}
      {health.recovery_hint && <p className="mt-2">{t(health.recovery_hint)}</p>}
    </>}
    {error?.id === id && <p role="status">{t(error.text)}</p>}
    <div className="d-flex gap-2 flex-wrap mt-2"><Button size="sm" variant="outline-dark" onClick={() => setRefresh(value => value + 1)}>{t("Refresh task status")}</Button>
      {(health?.recovery || []).filter(item => typeof item.url === "string" && item.url.startsWith("/") && !item.url.startsWith("//") && item.url !== location.pathname + location.search).map(item =>
        <Link className="btn btn-sm btn-outline-dark" key={item.url} to={item.url} reloadDocument={item.url.includes("?job=")}>{t(item.label)}</Link>)}
    </div>
  </Alert>;
}
