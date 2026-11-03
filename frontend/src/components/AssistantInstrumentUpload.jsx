import { useEffect, useId, useRef, useState } from "react";
import { Alert, Button, Form, Table } from "react-bootstrap";
import { apiGetAll, apiPostFormResponse } from "../api";

export function InstrumentMappingTable({ mappings = [] }) {
  return <Table size="sm" bordered responsive aria-label="Instrument column mapping" className="mt-2">
    <thead><tr><th>File column</th><th>Result key</th><th>Type</th><th>Limits / allowed values</th></tr></thead>
    <tbody>{mappings.map(mapping => <tr key={mapping.source_column}><td>{mapping.source_column}</td><td>{mapping.target_key}</td><td>{mapping.value_type}</td>
      <td>{mapping.allowed_values?.length ? JSON.stringify(mapping.allowed_values) : `${mapping.min_value ?? "—"} to ${mapping.max_value ?? "—"}`}</td></tr>)}</tbody>
  </Table>;
}

export default function AssistantInstrumentUpload({ config, onPrepared, onBusy, disabled }) {
  const skipId = useId();
  const [instruments, setInstruments] = useState([]), [projects, setProjects] = useState([]);
  const [instrument, setInstrument] = useState(""), [project, setProject] = useState(String(config.project_id || ""));
  const [runId, setRunId] = useState(""), [file, setFile] = useState(null), [skip, setSkip] = useState(true);
  const [error, setError] = useState(""), [validation, setValidation] = useState(null), [busy, setBusy] = useState(false);
  const controller = useRef(null);
  useEffect(() => {
    let active = true;
    Promise.all([apiGetAll("/api/instrument-profiles/"), apiGetAll("/api/projects/")]).then(([profiles, records]) => {
      if (active) { setInstruments(profiles); setProjects(records); }
    }, () => { if (active) setError("Could not load instruments and projects. Reopen the upload to retry."); });
    return () => { active = false; controller.current?.abort(); onBusy(false); };
  }, [onBusy]);
  const selected = instruments.find(item => String(item.id) === instrument);
  async function prepare(event) {
    event.preventDefault();
    if (busy || disabled || !file) return;
    const abort = new AbortController(); controller.current = abort;
    const form = new FormData();
    form.append("instrument", instrument); form.append("project", project); form.append("run_id", runId.trim());
    form.append("uploaded_file", file); form.append("skip_duplicates", String(skip));
    setBusy(true); onBusy(true); setError(""); setValidation(null);
    try {
      const response = await apiPostFormResponse("/api/assistant/instrument-imports/", form, { signal: abort.signal });
      const data = await response.json();
      if (!response.ok) {
        setValidation(data.validation || null);
        throw new Error(typeof data.detail === "string" ? data.detail : "Check the instrument, project, run ID and file, then validate again.");
      }
      onPrepared(data);
    } catch (error) {
      if (error.name !== "AbortError") setError(error instanceof TypeError || error instanceof SyntaxError
        ? "The upload response was interrupted. Retry with the same run ID to recover the existing preview."
        : error.message || "The upload did not complete. Retry with the same run ID to recover its existing preview.");
    } finally {
      setBusy(false); onBusy(false);
    }
  }
  return <Form onSubmit={prepare} className="border rounded p-2 my-2" aria-label="Instrument upload in chat">
    <strong>Import an instrument file</strong>
    <p className="small text-muted mb-2">Choose the instrument whose configured mapping matches this CSV/TSV export. No measurements are imported until you confirm the validated preview.</p>
    {error && <Alert variant="warning">{error}</Alert>}
    {validation && <div className="small mb-2">Rows received: {validation.counts.rows_received}. Rejected: {validation.counts.rows_rejected}.
      <ul>{validation.row_report.map(row => <li key={row.row}>Data row {row.row}: {row.reason}</li>)}</ul></div>}
    <Form.Group className="mb-2"><Form.Label>Instrument and mapping</Form.Label>
      <Form.Select aria-label="Import instrument" value={instrument} onChange={event => setInstrument(event.target.value)} required disabled={busy || disabled}>
        <option value="">Choose instrument</option>{instruments.map(item => <option key={item.id} value={item.id}>{item.code} — {item.name}</option>)}
      </Form.Select></Form.Group>
    {selected && <><div className="small">Sample ID column: <strong>{selected.sample_id_column}</strong>. Delimiter: {selected.delimiter === "\t" ? "tab" : selected.delimiter}</div>
      <InstrumentMappingTable mappings={selected.column_mappings} />
      {!selected.column_mappings?.length && <Alert variant="warning">This instrument needs a column mapping configured by an administrator.</Alert>}</>}
    <Form.Group className="mb-2"><Form.Label>Project</Form.Label><Form.Select aria-label="Import project" value={project} onChange={event => setProject(event.target.value)} required disabled={busy || disabled}>
      <option value="">Choose project</option>{projects.map(item => <option key={item.id} value={item.id}>{item.code} — {item.name}</option>)}
    </Form.Select></Form.Group>
    <Form.Group className="mb-2"><Form.Label>Instrument run ID</Form.Label><Form.Control aria-label="Instrument run ID" value={runId} onChange={event => setRunId(event.target.value)} required maxLength={128} disabled={busy || disabled} /></Form.Group>
    <Form.Group className="mb-2"><Form.Label>CSV/TSV file (UTF-8, up to 10 MB and 10,000 rows)</Form.Label><Form.Control aria-label="Instrument data file" type="file" accept=".csv,.tsv,.txt" onChange={event => setFile(event.target.files?.[0] || null)} required disabled={busy || disabled} /></Form.Group>
    <Form.Check id={skipId} className="my-2" label="Skip exact repeated rows within this file" checked={skip} onChange={event => setSkip(event.target.checked)} disabled={busy || disabled} />
    <p className="small text-muted">Clear this option when exact repeated rows represent intentional replicate measurements. Use the same run ID to recover an interrupted upload; use a new run ID for a separate instrument run.</p>
    <Button type="submit" size="sm" disabled={busy || disabled || !file || !selected?.column_mappings?.length}>{busy ? "Validating file..." : "Validate file and preview import"}</Button>
    {busy && <Button type="button" size="sm" variant="outline-secondary" className="ms-2" onClick={() => controller.current?.abort()}>Stop upload</Button>}
  </Form>;
}
