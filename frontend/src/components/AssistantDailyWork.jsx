import { useId, useState } from "react";
import { Alert, Badge, Button, Form, Table } from "react-bootstrap";
import { Link } from "react-router-dom";
import { useAssistantPanel, useAssistantProposal } from "../hooks/useAssistantPanel";

function WorkActions({ row, propose, disabled }) {
  const [mode, setMode] = useState(""), [person, setPerson] = useState(""), [due, setDue] = useState(""), [clearDue, setClearDue] = useState(false);
  const [decision, setDecision] = useState(""), [reason, setReason] = useState("");
  const id = useId();
  const base = { work_item_id: row.id, digest: row.digest };
  return <div className="mt-2">
    <div className="d-flex flex-wrap gap-1">
      {row.can_assign && <Button size="sm" variant="outline-primary" disabled={disabled} onClick={() => setMode("assign")}>Assign work</Button>}
      {row.can_start && <Button size="sm" variant="outline-primary" disabled={disabled} onClick={() => propose({ ...base, operation: "DAILY_START" })}>Preview start</Button>}
      {row.can_complete && <Button size="sm" variant="outline-primary" disabled={disabled} onClick={() => propose({ ...base, operation: "DAILY_COMPLETE" })}>Preview completion</Button>}
      {row.can_schedule && <Button size="sm" variant="outline-primary" disabled={disabled} onClick={() => setMode("due")}>Update deadline</Button>}
      {row.can_review && <Button size="sm" variant="outline-primary" disabled={disabled} onClick={() => setMode("review")}>Review workflow QC</Button>}
    </div>
    {mode && <Form className="mt-2" onSubmit={event => {
      event.preventDefault();
      propose({ ...base, ...(mode === "assign" ? { operation: "DAILY_ASSIGN", assignee: person.trim() } : mode === "due" ? {
        operation: "DAILY_DUE", due_at: clearDue ? null : new Date(due).toISOString()
      } : { operation: "WORKFLOW_REVIEW", decision, reason }) });
    }}><fieldset disabled={disabled}>
      {mode === "assign" && <><Form.Label htmlFor={`${id}-person`}>Exact assignee username</Form.Label><Form.Control id={`${id}-person`} required value={person} onChange={event => setPerson(event.target.value)} /></>}
      {mode === "due" && <>
        <Form.Label htmlFor={`${id}-due`}>Deadline in your browser timezone ({Intl.DateTimeFormat().resolvedOptions().timeZone})</Form.Label>
        <Form.Control id={`${id}-due`} type="datetime-local" required={!clearDue} disabled={clearDue} value={due} onChange={event => setDue(event.target.value)} />
        <Form.Check id={`${id}-clear`} label="Remove the recorded deadline" checked={clearDue} onChange={event => setClearDue(event.target.checked)} />
        <p className="small">The confirmation preview shows the exact timestamp and offset.</p>
      </>}
      {mode === "review" && <>
        {row.approval_blocker && <Alert variant="warning">{row.approval_blocker}</Alert>}
        <Form.Label htmlFor={`${id}-decision`}>Human QC decision</Form.Label><Form.Select id={`${id}-decision`} required value={decision} onChange={event => setDecision(event.target.value)}>
          <option value="">Choose a decision</option><option value="APPROVED" disabled={!row.can_approve}>Approve</option><option value="REJECTED">Reject</option><option value="RERUN_REQUIRED">Rerun required</option>
        </Form.Select><Form.Label htmlFor={`${id}-reason`}>QC review reason</Form.Label><Form.Control id={`${id}-reason`} required maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} />
      </>}
      <Button className="mt-2" size="sm" type="submit">{mode === "assign" ? "Preview assignment" : mode === "due" ? "Preview deadline" : "Preview QC decision"}</Button>
      <Button size="sm" variant="link" onClick={() => setMode("")}>Close editor</Button>
    </fieldset></Form>}
  </div>;
}

export default function AssistantDailyWork({ initial, revision, onContext, onPrepared, onBusy, disabled }) {
  const [scope, setScope] = useState(initial.scope), [draft, setDraft] = useState(initial.scope);
  const id = useId();
  const read = useAssistantPanel(`/api/assistant/daily-work/?${new URLSearchParams(scope)}`, "daily_work", initial, revision, onContext);
  const post = useAssistantProposal(onPrepared, onBusy);
  const model = read.panel, blocked = disabled || read.loading || post.busy;
  async function propose(data) {
    if (!await post.submit("/api/assistant/daily-work/actions/", { ...data, scope: { ...scope, offset: 0 } })) read.refresh();
  }
  return <section className="border rounded p-2 my-3" aria-label="Daily work assistant">
    <strong>Your daily work priorities</strong>
    {read.loading && <div role="status">Refreshing work requirements and QC…</div>}
    {read.error && <Alert variant="warning">{read.error}</Alert>}{post.error && <Alert variant="warning">{post.error}</Alert>}
    <Form className="my-2" onSubmit={event => { event.preventDefault(); setScope({ ...draft, offset: 0 }); read.refresh(); }}>
      <fieldset disabled={post.busy || read.loading || disabled}>
        <Form.Label htmlFor={`${id}-owner`}>Work scope</Form.Label><Form.Select id={`${id}-owner`} value={draft.scope} onChange={event => setDraft({ ...draft, scope: event.target.value })}>
          <option value="mine">Assigned to me</option><option value="unassigned">Unassigned accessible work</option><option value="team">Accessible team work</option>
        </Form.Select><Form.Label htmlFor={`${id}-focus`}>Priority filter</Form.Label><Form.Select id={`${id}-focus`} value={draft.focus} onChange={event => setDraft({ ...draft, focus: event.target.value })}>
          {[['all', 'All priorities'], ['actionable', 'Actionable for me'], ['overdue', 'Overdue'], ['today', 'Due today'], ['qc', 'QC attention'], ['blocked', 'Blocked']].map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </Form.Select><Form.Label htmlFor={`${id}-project`}>Exact project code (optional)</Form.Label><Form.Control id={`${id}-project`} value={draft.project} maxLength={64} onChange={event => setDraft({ ...draft, project: event.target.value })} />
        <Button size="sm" type="submit" className="mt-2">Apply work filters</Button>
      </fieldset>
    </Form>
    {model && <>
      <p className="small">Assessed {model.assessed} of {model.total_candidates} candidates; {model.matched_assessed} matches in the assessed set. Day: {model.day.start} to {model.day.end_exclusive}, end exclusive ({model.timezone}).</p>
      {model.truncated && <Alert variant="warning">Partial ranking: only the earliest-due {model.assessed} candidates were assessed. Narrow the project or filters.</Alert>}
      {!model.rows.length && <p>No matching priorities in this assessment. This is not a team-wide all-clear.</p>}
      {model.rows.map(row => <article className="border-top py-2" key={row.id} aria-label={`Work item ${row.id}`}>
        <strong>{row.sample} · {row.work}</strong>{" "}<Badge bg={row.overdue ? "warning" : "secondary"}>{row.review}</Badge>
        <div className="small">Work #{row.id} · {row.status} · {row.project || "Unassigned project"} · {row.assigned_to || "Unassigned"} · QC {row.qc_status}</div>
        <div className="small">Deadline: {row.due ? new Date(row.due).toLocaleString() : "None recorded"}</div><p className="mb-1">{row.reason}</p>
        <details><summary>Work evidence and requirements</summary><p>Missing fields: {row.missing_fields.join(", ") || "None"}. Failed/rejected result records: {row.failed_results}.</p>
          <Table size="sm" responsive><thead><tr><th>Key</th><th>Value</th><th>Check</th><th>Result review</th></tr></thead><tbody>{row.evidence.map(result => <tr key={result.id}>
            <td>{result.key}</td><td>{String(result.value ?? "")} {result.unit} {result.value_warning}</td><td>{result.qc_passed == null ? "Unevaluated" : result.qc_passed ? "Passed" : "Failed"}</td><td>{result.qc_status}</td>
          </tr>)}</tbody></Table><p>Showing {row.evidence.length} of {row.evidence_count} results. <Link to={`/samples/${row.sample_id}`}>Open the full sample record</Link>.</p>
        </details><WorkActions key={`${row.id}:${row.digest}`} row={row} propose={propose} disabled={blocked} />
      </article>)}
      {model.next_offset != null && <Button size="sm" disabled={blocked} onClick={() => setScope({ ...scope, offset: model.next_offset })}>Next work page</Button>}
      {model.notes.map(note => <p className="small text-muted mb-1" key={note}>{note}</p>)}
    </>}
    <Button size="sm" variant="outline-secondary" className="mt-2" disabled={post.busy || read.loading} onClick={() => { setScope({ ...scope, offset: 0 }); read.refresh(); }}>Refresh priorities</Button>
  </section>;
}
