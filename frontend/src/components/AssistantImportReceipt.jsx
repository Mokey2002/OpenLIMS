import { useEffect, useRef, useState } from "react";
import { Alert, Button, Table } from "react-bootstrap";
import { apiDownload, apiGet, apiPostResponse } from "../api";
import { InstrumentMappingTable } from "./AssistantInstrumentUpload";

export default function AssistantImportReceipt({ jobId, initialJob = null, actionStatus, onActionUpdate, onPrepared, onBusy, disabled }) {
  const [job, setJob] = useState(initialJob), [error, setError] = useState(""), [tick, setTick] = useState(0), [busy, setBusy] = useState(false);
  const update = useRef(onActionUpdate), lastStatus = useRef(actionStatus);
  const control = useRef(null);
  useEffect(() => { update.current = onActionUpdate; }, [onActionUpdate]);
  useEffect(() => {
    let active = true, timer, checks = 0;
    const abort = new AbortController();
    async function refresh() {
      try {
        const data = await apiGet(`/api/assistant/instrument-imports/${jobId}/`, { signal: abort.signal });
        if (!active) return;
        setJob(data); setError("");
        if (data.action && data.action.status !== lastStatus.current) {
          lastStatus.current = data.action.status; update.current?.(data.action);
        }
        if (data.state === "queued_or_running" && ++checks < 90) timer = setTimeout(refresh, 2000);
      } catch (error) {
        if (active && error.name !== "AbortError") { setJob(null); setError("Import status is unavailable. Check your connection and access, then refresh."); }
      }
    }
    refresh();
    return () => { active = false; clearTimeout(timer); abort.abort(); };
  }, [jobId, actionStatus, tick]);
  useEffect(() => () => { control.current?.abort(); onBusy?.(false); }, [onBusy]);
  async function command(operation) {
    const abort = new AbortController(); control.current = abort;
    setBusy(true); onBusy?.(true); setError("");
    try {
      const response = await apiPostResponse(`/api/assistant/instrument-imports/${jobId}/${operation}/`, {}, { signal: abort.signal });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Could not prepare the import. Refresh its current status.");
      onPrepared?.(data); setTick(value => value + 1);
    } catch (error) { if (error.name !== "AbortError") setError(error.message); }
    finally { setBusy(false); onBusy?.(false); }
  }
  const counts = job?.counts || {};
  return <div className="border rounded p-2 my-2 small" aria-label="Instrument import receipt">
    {error && <Alert variant="warning">{error}</Alert>}
    {job && <>
      <strong>Import #{job.id}: {job.state.replaceAll("_", " ")}</strong>
      <div>{job.instrument} · {job.project} · run {job.run_id} · {job.filename}</div>
      {job.repair && <p>Corrected copy of import #{job.repair.parent_id}, original run {job.repair.parent_run_id}; original data rows {job.repair.source_rows.join(", ")}. The original file and imported measurements are unchanged.</p>}
      {job.error && <Alert variant="warning" className="mt-2">{job.error}</Alert>}
      <Table size="sm" bordered className="my-2"><tbody>
        <tr><th>Rows received</th><td>{counts.rows_received ?? job.planned_counts?.rows_received}</td></tr>
        <tr><th>{job.status === "COMPLETED" ? "Rows imported" : "Validated rows to import"}</th><td>{job.status === "COMPLETED" ? counts.rows_imported : counts.rows_to_import}</td></tr>
        {job.status === "FAILED" && <tr><th>Rows imported</th><td>{counts.rows_imported || 0}</td></tr>}
        <tr><th>Rows rejected by validation</th><td>{counts.rows_rejected || 0}</td></tr>
        <tr><th>Exact repeated rows skipped</th><td>{counts.duplicates_skipped || 0}</td></tr>
        {counts.rows_not_imported > 0 && <tr><th>Validated rows not imported</th><td>{counts.rows_not_imported}</td></tr>}
        {job.status === "COMPLETED" && <><tr><th>Results created</th><td>{counts.results_created}</td></tr><tr><th>Rows accounted for</th><td>{counts.rows_accounted}</td></tr></>}
      </tbody></Table>
      <details><summary>Instrument mapping and row report</summary>
        {job.sample_id_column && <p>Sample ID column: {job.sample_id_column}. Delimiter: {job.delimiter === "\t" ? "tab" : job.delimiter}</p>}
        <InstrumentMappingTable mappings={job.mappings} />
        {job.unmapped_columns?.length > 0 && <p>Ignored columns: {job.unmapped_columns.join(", ")}</p>}
        <p>Showing up to 50 of {job.report_total} data rows. Download the report for the complete accounting.</p>
        <Table size="sm" responsive><thead><tr><th>Data row</th><th>Sample</th><th>Status</th><th>Note</th></tr></thead>
          <tbody>{job.row_report.map(row => <tr key={row.row}><td>{row.row}</td><td>{row.sample_id}</td><td>{row.status}</td><td>{row.reason}</td></tr>)}</tbody></Table>
      </details>
      <Button size="sm" variant="outline-secondary" className="me-1" disabled={busy} onClick={async () => { try { await apiDownload(job.download_url, `instrument-import-${jobId}.csv`); } catch { setError("Could not download the report. Check your connection and access."); } }}>Download row report</Button>
      {job.can_repair && onPrepared && <Button size="sm" variant="outline-primary" className="me-1" disabled={busy || disabled} onClick={() => onPrepared({
        answer: "Select rejected rows and enter their actual corrections. Validation prepares a child import; measurements require confirmation.",
        lab_operation_form: { kind: "repair", title: "Repair rejected import rows", help: "Choose the rejected rows to correct. Imported rows cannot be retried here.", defaults: { parent_id: jobId } },
        context: { lab_operation: { kind: "repair", defaults: { parent_id: jobId } } }
      })}>Repair rejected rows</Button>}
      {job.can_revalidate && onPrepared && <Button size="sm" variant="outline-primary" className="me-1" disabled={busy || disabled} onClick={() => command("revalidate")}>Revalidate and preview</Button>}
      {job.can_resume && <Button size="sm" variant="outline-primary" className="me-1" disabled={busy || disabled} onClick={() => command("resume")}>{job.status === "COMPLETED" ? "Finalize import receipt" : "Resume queued import"}</Button>}
    </>}
    <Button size="sm" variant="outline-secondary" disabled={busy} onClick={() => setTick(value => value + 1)}>Refresh import status</Button>
  </div>;
}
