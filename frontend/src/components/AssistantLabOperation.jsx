import { useEffect, useId, useState } from "react";
import { Alert, Button, Form, Table } from "react-bootstrap";
import { apiGetResponse } from "../api";
import { useAssistantProposal } from "../hooks/useAssistantPanel";

function localTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
function timestamp(value) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) throw new Error("Choose an exact date and time.");
  return date.toISOString();
}
async function read(url, signal) {
  const response = await apiGetResponse(url, { signal });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data));
  return data;
}

export default function AssistantLabOperation({ initial, revision, onPrepared, onBusy, disabled }) {
  const kind = initial.kind, prefix = useId();
  const [values, setValues] = useState(() => {
    const result = { project: "", batch: "", scope: "unassigned", assign_to: "", deadline_mode: "keep", due_at: "",
      mode: "book", instrument: "", starts_at: "", ends_at: "", stocks: [], source_kind: "pipeline", source_id: "",
      notebook_id: "", template_id: "", title: "", method_notes: "", parent_id: "", source: "me", recipient: "",
      send_notice: true, message: kind === "handover" ? "Please review the current work and its recorded blockers before proceeding." : "", booking_id: "", ...initial.defaults };
    for (const key of ["due_at", "starts_at", "ends_at"]) result[key] = localTime(result[key]);
    return result;
  });
  const [refresh, setRefresh] = useState(0), [offset, setOffset] = useState(0), [localError, setLocalError] = useState("");
  const [optionsState, setOptions] = useState({}), [rowState, setRows] = useState({}), [selection, setSelection] = useState({});
  const requestKey = JSON.stringify([kind, values.project, revision, refresh]);
  const rowsKey = JSON.stringify([values.parent_id, offset, refresh]);
  const options = optionsState.key === requestKey ? optionsState.data : null;
  const repair = rowState.key === rowsKey ? rowState.data : null;
  const selected = selection.key === rowsKey ? selection.rows : [];
  const edits = selection.key === rowsKey ? selection.edits : {};
  const { busy, error, submit } = useAssistantProposal(onPrepared, onBusy);
  const blocked = disabled || busy;
  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ kind, ...(values.project ? { project: values.project } : {}) });
    const timer = setTimeout(() => read(`/api/assistant/lab-operations/options/?${params}`, controller.signal)
      .then(data => setOptions({ key: requestKey, data })).catch(error => {
        if (error.name !== "AbortError") setOptions({ key: requestKey, error: error.message });
      }), 150);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [kind, values.project, requestKey]);
  useEffect(() => {
    if (kind !== "repair" || !/^\d+$/.test(String(values.parent_id))) return;
    const controller = new AbortController();
    read(`/api/assistant/import-repairs/${values.parent_id}/?offset=${offset}`, controller.signal)
      .then(data => setRows({ key: rowsKey, data })).catch(error => {
        if (error.name !== "AbortError") setRows({ key: rowsKey, error: error.message });
      });
    return () => controller.abort();
  }, [kind, values.parent_id, offset, rowsKey]);
  function set(name, value) {
    setLocalError("");
    setValues(previous => ({ ...previous, [name]: value,
      ...(name === "source_kind" ? { source_id: "" } : {}),
      ...(name === "notebook_id" ? { template_id: "" } : {}),
      ...(name === "project" && kind === "notebook" ? { source_id: "", notebook_id: "", template_id: "" } : {}) }));
    if (name === "parent_id") setOffset(0);
  }
  const projects = (options?.projects || []).map(row => ({ value: row.code, label: row.name }));
  const people = ["me", ...(options?.people || [])];
  function field(name, label, { type = "text", required = false, choices, suggestions = [], as, rows } = {}) {
    const id = `${prefix}-${name}`;
    return <Form.Group controlId={id} className="mb-2" key={name}>
      <Form.Label>{label}</Form.Label>
      {choices ? <Form.Select value={values[name]} disabled={blocked} onChange={event => set(name, event.target.value)}>
        {choices.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
      </Form.Select> : <Form.Control type={type} as={as} rows={rows} value={values[name]} disabled={blocked} required={required}
        list={suggestions.length ? `${id}-options` : undefined} onChange={event => set(name, event.target.value)} />}
      {suggestions.length > 0 && <datalist id={`${id}-options`}>{suggestions.map(item => {
        const value = typeof item === "object" ? item.value : item;
        return <option key={value} value={value}>{typeof item === "object" ? item.label : ""}</option>;
      })}</datalist>}
    </Form.Group>;
  }
  function fields() {
    if (kind === "batch") return { project: values.project, batch: values.batch, scope: values.scope, assign_to: values.assign_to,
      deadline_mode: values.deadline_mode, due_at: values.deadline_mode === "set" ? timestamp(values.due_at) : null };
    if (kind === "handover") return { project: values.project, batch: values.batch, source: values.source, recipient: values.recipient,
      send_notice: values.send_notice, message: values.message };
    if (kind === "resources") return values.mode === "cancel" ? { project: values.project, mode: "cancel", booking_id: Number(values.booking_id) }
      : { project: values.project, instrument: values.instrument, starts_at: timestamp(values.starts_at), ends_at: timestamp(values.ends_at),
        stocks: values.stocks, note: values.message };
    if (kind === "notebook") return { project: values.project, source_kind: values.source_kind, source_id: Number(values.source_id),
      notebook_id: Number(values.notebook_id), template_id: values.template_id ? Number(values.template_id) : null,
      title: values.title, method_notes: values.method_notes };
    if (!repair || !selected.length) throw new Error("Select at least one rejected data row to revalidate.");
    return { parent_id: Number(values.parent_id), skip_duplicates: values.skip_duplicates !== false,
      corrections: selected.map(number => {
        const original = repair.rows.find(row => row.row === number).values;
        const changed = Object.fromEntries(Object.entries(edits[number] || {}).filter(([key, value]) => original[key] !== value));
        if (!Object.keys(changed).length) changed[repair.columns[0]] = original[repair.columns[0]];
        return { row: number, values: changed };
      }) };
  }
  const optionError = optionsState.key === requestKey && optionsState.error;
  const rowError = rowState.key === rowsKey && rowState.error;
  return <div className="border rounded p-2 my-2 small" aria-label={initial.title}>
    <strong>{initial.title}</strong><p className="mb-2">{initial.help}</p>
    {(error || localError || optionError || rowError) && <Alert variant="warning">{error || localError || optionError || rowError}</Alert>}
    {!options && !optionError && <p role="status">Loading current choices…</p>}
    <Form onSubmit={event => { event.preventDefault(); setLocalError(""); try { void submit("/api/assistant/lab-operations/preview/", { kind, fields: fields() }); } catch (error) { setLocalError(error.message); } }}>
      {kind !== "repair" && field("project", "Project code", { required: true, suggestions: projects })}
      {["batch", "handover"].includes(kind) && field("batch", "Batch code (optional)", { suggestions: options?.batches || [] })}
      {kind === "batch" && <>
        {field("scope", "Select work", { choices: [["unassigned", "Unassigned work"], ["mine", "My unfinished work"], ["team", "Team unfinished work"]] })}
        {field("assign_to", "Assign to username (optional)", { suggestions: people })}
        {field("deadline_mode", "Deadline change", { choices: [["keep", "Keep existing deadlines"], ["set", "Set deadline"], ["clear", "Clear deadline"]] })}
        {values.deadline_mode === "set" && field("due_at", "Deadline", { type: "datetime-local", required: true })}
      </>}
      {kind === "handover" && <>
        {field("source", "Source username", { required: true, suggestions: people })}
        {field("recipient", "Recipient username", { required: true, suggestions: people })}
        <Form.Check id={`${prefix}-notice`} label="Create an internal notification for the recipient" checked={values.send_notice} disabled={blocked} onChange={event => set("send_notice", event.target.checked)} />
        {values.send_notice && field("message", "Internal message", { as: "textarea", rows: 3 })}
      </>}
      {kind === "resources" && <>
        {field("mode", "Resource operation", { choices: [["book", "Book instrument and reserve stock"], ["cancel", "Cancel my booking and release active stock reservations"]] })}
        {values.mode === "cancel" ? field("booking_id", "Booking ID", { type: "number", required: true, suggestions: (options?.bookings || []).map(row => ({ value: row.id, label: row.label })) }) : <>
          {field("instrument", "Instrument code", { required: true, suggestions: (options?.instruments || []).map(row => ({ value: row.code, label: row.name })) })}
          {field("starts_at", "Start time", { type: "datetime-local", required: true })}
          {field("ends_at", "End time", { type: "datetime-local", required: true })}
          {values.stocks.map((stock, index) => <div className="border rounded p-2 mb-2" key={index}>
            {[['lot', 'Lot code'], ['quantity', 'Quantity'], ['unit', 'Unit']].map(([name, label]) => <Form.Group key={name} controlId={`${prefix}-stock-${index}-${name}`} className="mb-1">
              <Form.Label>{label} {index + 1}</Form.Label><Form.Control value={stock[name]} required disabled={blocked} type={name === "quantity" ? "number" : "text"}
                {...(name === "quantity" ? { min: "0.0001", step: "0.0001" } : {})}
                onChange={event => set("stocks", values.stocks.map((row, rowIndex) => rowIndex === index ? { ...row, [name]: event.target.value } : row))} />
            </Form.Group>)}
            <Button size="sm" variant="outline-secondary" disabled={blocked} onClick={() => set("stocks", values.stocks.filter((_, rowIndex) => rowIndex !== index))}>Remove reagent {index + 1}</Button>
          </div>)}
          <Button size="sm" variant="outline-secondary" className="mb-2" disabled={blocked || values.stocks.length >= 10} onClick={() => set("stocks", [...values.stocks, { lot: "", quantity: "", unit: "" }])}>Add reagent reservation</Button>
          <details className="mb-2"><summary>Current stock choices</summary>{(options?.lots || []).map(lot => <div key={lot.code}>{lot.code}: {lot.available} {lot.unit} unreserved</div>)}</details>
          {field("message", "Booking note (optional)", { as: "textarea", rows: 2 })}
        </>}
      </>}
      {kind === "notebook" && <>
        {field("source_kind", "Run type", { choices: [["pipeline", "Pipeline run"], ["import", "Completed instrument import"]] })}
        {field("source_id", "Run or import ID", { type: "number", required: true, suggestions: (options?.sources || []).filter(row => row.kind === values.source_kind).map(row => ({ value: row.id, label: row.label })) })}
        {field("notebook_id", "Notebook ID", { type: "number", required: true, suggestions: (options?.notebooks || []).map(row => ({ value: row.id, label: row.name })) })}
        {field("template_id", "Template ID (optional)", { type: "number", suggestions: (options?.templates || []).filter(row => String(row.notebook_id) === String(values.notebook_id)).map(row => ({ value: row.id, label: row.name })) })}
        {field("title", "Draft title", { required: true })}
        {field("method_notes", "Actual method notes (optional)", { as: "textarea", rows: 3 })}
      </>}
      {kind === "repair" && <>
        {field("parent_id", "Original import ID", { type: "number", required: true, suggestions: (options?.imports || []).map(row => ({ value: row.id, label: row.label })) })}
        {repair && <>
          <p>{repair.project} · run {repair.run_id}. Showing {repair.rows.length} of {repair.total} originally rejected rows. Row numbers count data records after the instrument header.</p>
          {repair.mapping_changed && <Alert variant="warning">The instrument mapping changed. Review the current columns and the corrected import preview.</Alert>}
          <Table size="sm" responsive bordered><thead><tr><th>Select</th><th>Error</th>{repair.columns.map(column => <th key={column}>{column}</th>)}</tr></thead><tbody>
            {repair.rows.map(row => <tr key={row.row}><td><Form.Check id={`${prefix}-repair-${row.row}`} label={`Repair data row ${row.row}`} checked={selected.includes(row.row)} disabled={blocked || row.repair_status === "COMPLETED"}
              onChange={event => setSelection({ key: rowsKey, edits, rows: event.target.checked ? [...selected, row.row] : selected.filter(number => number !== row.row) })} />
              {row.repair_job_id && <span>Repair #{row.repair_job_id}: {row.repair_status}</span>}</td><td>{row.reason}</td>
              {repair.columns.map(column => <td key={column}><Form.Control aria-label={`Row ${row.row} ${column}`} value={edits[row.row]?.[column] ?? row.values[column] ?? ""} disabled={blocked || !selected.includes(row.row)}
                onChange={event => setSelection({ key: rowsKey, rows: selected, edits: { ...edits, [row.row]: { ...edits[row.row], [column]: event.target.value } } })} /></td>)}</tr>)}
          </tbody></Table>
          {repair.next_offset !== null && <Button size="sm" className="mb-2" variant="outline-secondary" disabled={blocked || selected.length > 0} onClick={() => setOffset(repair.next_offset)}>Next rejected rows</Button>}
          {offset > 0 && <Button size="sm" className="mb-2 ms-1" variant="outline-secondary" disabled={blocked || selected.length > 0} onClick={() => setOffset(value => Math.max(0, value - 20))}>Previous rejected rows</Button>}
          <Form.Check id={`${prefix}-duplicates`} label="Skip exact repeated rows in this corrected import" checked={values.skip_duplicates !== false} disabled={blocked} onChange={event => set("skip_duplicates", event.target.checked)} />
          <p>Validation stores a corrected child file and an import preview. Measurements are imported only after you confirm.</p>
        </>}
      </>}
      {(kind === "batch" && values.deadline_mode === "set" || kind === "resources" && values.mode === "book") && <p>Times use your browser zone ({Intl.DateTimeFormat().resolvedOptions().timeZone}); the preview records their explicit UTC offset.</p>}
      {initial.plan?.excluded?.length > 0 && <Alert variant="warning"><ul>{initial.plan.excluded.map(row => <li key={row.id}>{row.label}: {row.reason}</li>)}</ul></Alert>}
      <Button size="sm" type="submit" disabled={blocked || !options || !options.can_write || kind === "repair" && (!repair || !selected.length)}>
        {busy ? "Preparing preview…" : kind === "repair" ? "Validate corrections and preview import" : "Preview changes"}
      </Button>{" "}<Button size="sm" variant="outline-secondary" disabled={blocked || kind === "repair" && selected.length > 0} onClick={() => setRefresh(value => value + 1)}>Refresh choices</Button>
    </Form>
  </div>;
}
