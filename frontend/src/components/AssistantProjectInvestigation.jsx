import { useId, useState } from "react";
import { Alert, Button, Form, Table } from "react-bootstrap";
import { Link } from "react-router-dom";
import { useAssistantPanel, useAssistantProposal } from "../hooks/useAssistantPanel";

const GROUPS = { key: "Result key", instrument: "Linked instrument", operator: "Result entered by", workflow: "Work type" };
const COUNTS = { results: "Recorded results", assessed_checks: "Assessed automated checks", failed_checks: "Failed checks", rejected_reviews: "Rejected result reviews", pending_reviews: "Pending/reopened result reviews", flagged_results: "Distinct flagged results", rejected_work_gates: "Rejected work-item gates", rerun_work_gates: "Work-item gates requiring rerun" };

export default function AssistantProjectInvestigation({ initial, revision, onContext, onPrepared, onBusy, onRun, disabled }) {
  const { project_id: projectId, ...initialScope } = initial.spec;
  const [scope, setScope] = useState(initialScope), [draft, setDraft] = useState(initialScope);
  const id = useId();
  const read = useAssistantPanel(`/api/assistant/project-investigations/${projectId}/?${new URLSearchParams(scope)}`, "project_investigation", initial, revision, onContext);
  const post = useAssistantProposal(onPrepared, onBusy), report = read.panel;
  const blocked = disabled || read.loading || post.busy;
  async function exportReport(output_format) {
    if (!await post.submit(`/api/assistant/project-investigations/${projectId}/export/`, { ...scope, output_format })) read.refresh();
  }
  return <section className="border rounded p-2 my-3" aria-label="Project QC investigation">
    <strong>Project QC investigation{report ? `: ${report.project}` : ""}</strong>
    {read.loading && <div role="status">Reading current QC evidence…</div>}
    {read.error && <Alert variant="warning">{read.error}</Alert>}{post.error && <Alert variant="warning">{post.error}</Alert>}
    <Form className="my-2" onSubmit={event => { event.preventDefault(); setScope(draft); read.refresh(); }}>
      <fieldset disabled={blocked}>
        <Form.Label htmlFor={`${id}-window`}>Investigation window</Form.Label><Form.Select id={`${id}-window`} value={draft.period || "rolling"} onChange={event => {
          const { days: previousDays, period: previousPeriod, ...other } = draft;
          setDraft(event.target.value === "rolling" ? { ...other, days: previousDays || 90 } : { ...other, period: event.target.value });
          void previousPeriod;
        }}><option value="rolling">Rolling days</option>{['today', 'yesterday', 'this_week', 'last_week', 'this_month', 'last_month', 'last_7_days'].map(period => <option key={period} value={period}>{period.replaceAll("_", " ")}</option>)}</Form.Select>
        {!draft.period && <><Form.Label htmlFor={`${id}-days`}>Number of days</Form.Label><Form.Control id={`${id}-days`} type="number" min={1} max={365} required value={draft.days} onChange={event => setDraft({ ...draft, days: Number(event.target.value) })} /></>}
        <Form.Label htmlFor={`${id}-group`}>Group evidence by</Form.Label><Form.Select id={`${id}-group`} value={draft.group_by} onChange={event => setDraft({ ...draft, group_by: event.target.value })}>{Object.entries(GROUPS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</Form.Select>
        <Form.Label htmlFor={`${id}-key`}>Exact result key (optional)</Form.Label><Form.Control id={`${id}-key`} maxLength={64} value={draft.key} onChange={event => setDraft({ ...draft, key: event.target.value })} />
        <Button size="sm" type="submit" className="mt-2">Apply investigation filters</Button>
      </fieldset>
    </Form>
    {report && <>
      <p className="small">{report.window.start} to {report.window.end_exclusive}, end exclusive ({report.window.timezone}). Read at {report.as_of}.</p>
      <Table size="sm" bordered><tbody>{Object.entries(COUNTS).map(([key, label]) => <tr key={key}><th>{label}</th><td>{report.summary[key] ?? 0}</td></tr>)}
        <tr><th>Failed / assessed check rate</th><td>{report.summary.failure_rate == null ? "No assessed checks" : `${report.summary.failure_rate}%`}</td></tr></tbody></Table>
      <p>Showing {report.groups.length} of {report.group_count} groups. Rates use assessed checks; unevaluated checks are excluded.</p>
      <Table size="sm" responsive><thead><tr><th>{report.group_label}</th><th>Results</th><th>Assessed</th><th>Failed</th><th>Rejected</th><th>Distinct flagged</th><th>Check failure %</th></tr></thead>
        <tbody>{report.groups.map(row => <tr key={row.label}><td>{row.label}</td><td>{row.results}</td><td>{row.assessed_checks}</td><td>{row.failed_checks}</td><td>{row.rejected_reviews}</td><td>{row.flagged_results}</td><td>{row.failure_rate == null ? "Not assessed" : row.failure_rate}</td></tr>)}</tbody></Table>
      <details><summary>Flagged result evidence ({report.failure_count})</summary><p>Showing {report.failures.length} of {report.failure_count} records; CSV contains all bounded failure evidence.</p>
        {report.failures.map(row => <div className="border-top py-1" key={row.id}><Link to={row.url}>R-{row.id} · {row.sample} · {row.key}</Link>
          <div>{String(row.value ?? "")} {row.unit} {row.value_warning} · check: {String(row.qc_passed)} · review: {row.qc_status}</div>
          <div>Recorded check reason: {row.qc_failure_reason || "Not recorded"}. Review note: {row.review_note || "Not recorded"}.</div>
          <div className="small">{row.instrument ? `${row.instrument}, run ${row.run_id}` : "No linked instrument"} · {row.operator || "No recorded entrant"}</div>
        </div>)}
      </details>
      <details><summary>Separate work-item QC gate evidence ({report.work_gate_count})</summary>
        {report.work_gates.map(row => <div className="border-top py-1" key={row.id}><Link to={row.url}>Work #{row.id} · {row.sample} · {row.work}</Link><div>{row.qc_status} · {row.reason} · {row.reviewed_by} · {row.reviewed_at}</div></div>)}
      </details>
      <div className="d-flex flex-wrap gap-1 my-2">
        <Button size="sm" disabled={blocked} onClick={() => exportReport("PDF")}>Preview PDF report</Button>
        <Button size="sm" variant="outline-primary" disabled={blocked} onClick={() => exportReport("CSV")}>Preview CSV report</Button>
        <Button size="sm" variant="outline-secondary" disabled={blocked} onClick={() => onRun(`Graph failures by ${report.group_by}`)}>Graph these groups</Button>
      </div>
      <Alert variant="secondary" className="small"><ul className="mb-0">{report.notes.map(note => <li key={note}>{note}</li>)}</ul></Alert>
    </>}
    <Button size="sm" variant="outline-secondary" disabled={post.busy || read.loading} onClick={read.refresh}>Refresh investigation</Button>
  </section>;
}
