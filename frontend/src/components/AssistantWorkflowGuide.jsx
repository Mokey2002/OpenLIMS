import { useEffect, useId, useRef, useState } from "react";
import { Alert, Badge, Button, Form, Table } from "react-bootstrap";
import { apiGet, apiPostResponse } from "../api";
import SampleFormFields from "./SampleFormFields";

function StepEditor({ step, sampleCode, planDigest, propose, onRun, disabled }) {
  const [mode, setMode] = useState("");
  const [person, setPerson] = useState(""), [key, setKey] = useState(""), [value, setValue] = useState(""), [kind, setKind] = useState("NUMBER");
  const [values, setValues] = useState(() => structuredClone(step.form_values || {}));
  const [reason, setReason] = useState(""), [decision, setDecision] = useState("");
  const prefix = useId();
  const definitions = step.required_fields || [];
  const definition = definitions.find(field => field.key === key);
  const valueType = definition?.value_type || kind;
  function record(event) {
    event.preventDefault();
    const parsed = valueType === "NUMBER" ? Number(value) : valueType === "BOOLEAN" ? value === "true" : value;
    onRun(`Add result ${key} = ${JSON.stringify(parsed)} to work item #${step.work_item_id} for sample ${sampleCode}`);
  }
  const fields = { operation: mode === "form" ? "WORKFLOW_FORM" : "WORKFLOW_REVIEW", step_id: step.id, plan_digest: planDigest, reason };
  return <div className="mt-2">
    <div className="d-flex flex-wrap gap-1">
      {step.can_assign && <Button size="sm" variant="outline-primary" disabled={disabled} onClick={() => setMode("assign")}>Assign work</Button>}
      {step.can_record && <Button size="sm" variant="outline-primary" disabled={disabled} onClick={() => setMode("result")}>Record result</Button>}
      {step.can_record && step.form_schema?.fields?.length > 0 && <Button size="sm" variant="outline-primary" disabled={disabled} onClick={() => setMode("form")}>Record step form</Button>}
      {step.can_complete && <Button size="sm" variant="outline-primary" disabled={disabled} onClick={() => propose({ operation: "WORKFLOW_COMPLETE", step_id: step.id, plan_digest: planDigest })}>Preview work completion</Button>}
      {step.can_review && <Button size="sm" variant="outline-primary" disabled={disabled} onClick={() => setMode("review")}>Review workflow QC</Button>}
    </div>
    {mode === "assign" && step.can_assign && <Form className="mt-2" onSubmit={event => { event.preventDefault(); onRun(`Assign work item #${step.work_item_id} for sample ${sampleCode} to ${person.trim()}`); }}>
      <Form.Label htmlFor={`${prefix}-owner`}>Exact assignee username</Form.Label><Form.Control id={`${prefix}-owner`} required value={person} onChange={event => setPerson(event.target.value)} disabled={disabled} />
      <Button size="sm" type="submit" className="mt-2" disabled={disabled}>Preview assignment</Button>
    </Form>}
    {mode === "result" && step.can_record && <Form className="mt-2" onSubmit={record}>
      <Form.Label htmlFor={`${prefix}-key`}>Result key</Form.Label>
      {definitions.length ? <Form.Select id={`${prefix}-key`} value={key} onChange={event => { setKey(event.target.value); setValue(""); }} required disabled={disabled}>
        <option value="">Choose configured result key</option>{definitions.map(field => <option key={field.key} value={field.key} disabled={step.results.some(result => result.key === field.key)}>{field.key} ({field.value_type})</option>)}
      </Form.Select> : <><Form.Control id={`${prefix}-key`} value={key} onChange={event => setKey(event.target.value)} required maxLength={64} disabled={disabled} />
        <Form.Label htmlFor={`${prefix}-type`}>Result type</Form.Label><Form.Select id={`${prefix}-type`} value={kind} onChange={event => { setKind(event.target.value); setValue(""); }} disabled={disabled}>
          <option>NUMBER</option><option>STRING</option><option>BOOLEAN</option></Form.Select></>}
      <Form.Label htmlFor={`${prefix}-value`}>Actual measured value</Form.Label>
      {valueType === "BOOLEAN" ? <Form.Select id={`${prefix}-value`} required value={value} onChange={event => setValue(event.target.value)} disabled={disabled}>
        <option value="">Choose recorded value</option><option value="true">true</option><option value="false">false</option>
      </Form.Select> : <Form.Control id={`${prefix}-value`} type={valueType === "NUMBER" ? "number" : "text"} step="any" required maxLength={255} value={value} onChange={event => setValue(event.target.value)} disabled={disabled} />}
      <p className="small text-muted">Enter a measurement you actually recorded. Existing results are corrected through the result review interface.</p>
      <Button size="sm" type="submit" disabled={disabled}>Preview result</Button>
    </Form>}
    {(mode === "form" && step.can_record || mode === "review" && step.can_review) && <Form className="mt-2" onSubmit={event => { event.preventDefault(); propose({ ...fields, ...(mode === "form" ? { values } : { decision }) }); }}>
      <fieldset disabled={disabled}>
        {mode === "form" ? <SampleFormFields fields={step.form_schema.fields} values={values} onChange={setValues} /> : <>
          {step.approval_blocker && <Alert variant="warning">{step.approval_blocker}</Alert>}
          <Form.Label htmlFor={`${prefix}-decision`}>Human QC decision</Form.Label><Form.Select id={`${prefix}-decision`} required value={decision} onChange={event => setDecision(event.target.value)}>
            <option value="">Choose a decision</option><option value="APPROVED" disabled={!step.can_approve}>Approve</option><option value="REJECTED">Reject</option><option value="RERUN_REQUIRED">Rerun required</option>
          </Form.Select><p className="small">This reviews the workflow work-item gate. Individual result QC reviews remain separate.</p>
        </>}
        <Form.Label htmlFor={`${prefix}-reason`}>{mode === "form" ? "Reason (10 characters minimum)" : "QC review reason"}</Form.Label>
        <Form.Control id={`${prefix}-reason`} value={reason} onChange={event => setReason(event.target.value)} required minLength={mode === "form" ? 10 : 1} maxLength={2000} />
        <Button size="sm" type="submit" className="mt-2">{mode === "form" ? "Preview step form" : "Preview QC decision"}</Button>
      </fieldset>
    </Form>}
    {mode && <Button size="sm" variant="link" disabled={disabled} onClick={() => setMode("")}>Close editor</Button>}
  </div>;
}

export default function AssistantWorkflowGuide({ initialPlan, revision, onPrepared, onRun, onBusy, disabled }) {
  const [plan, setPlan] = useState(initialPlan), [error, setError] = useState(""), [tick, setTick] = useState(0), [busy, setBusy] = useState(false), [template, setTemplate] = useState("");
  const control = useRef(null), prefix = useId();
  const [loadError, setLoadError] = useState("");
  const sampleId = initialPlan.sample_id;
  const queryKey = `${sampleId}:${revision}:${tick}`;
  const [loadedKey, setLoadedKey] = useState(null);
  const refreshing = loadedKey !== queryKey;
  useEffect(() => {
    const abort = new AbortController();
    apiGet(`/api/assistant/workflows/${sampleId}/`, { signal: abort.signal }).then(data => {
      if (!abort.signal.aborted) { setPlan(data); setLoadError(""); setLoadedKey(queryKey); }
    }, error => {
      if (!abort.signal.aborted && error.name !== "AbortError") { setPlan(null); setLoadedKey(queryKey); setLoadError("Workflow status is unavailable. Check your connection and access, then refresh."); }
    });
    return () => abort.abort();
  }, [sampleId, queryKey]);
  useEffect(() => () => { control.current?.abort(); onBusy?.(false); }, [onBusy]);
  async function propose(data) {
    const abort = new AbortController(); control.current = abort;
    setBusy(true); onBusy?.(true); setError("");
    try {
      const response = await apiPostResponse(`/api/assistant/workflows/${sampleId}/actions/`, data, { signal: abort.signal });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || `Check the entered workflow fields: ${JSON.stringify(result)}`);
      onPrepared(result);
    } catch (error) { if (error.name !== "AbortError") { setError(error.message || "The preview response was interrupted. Refresh the workflow before retrying."); setTick(value => value + 1); } }
    finally { setBusy(false); onBusy?.(false); }
  }
  return <section className="border rounded p-2 my-3" aria-label="Guided sequencing preparation">
    <strong>Sequencing preparation checklist</strong>
    {refreshing && <div role="status" className="small">Refreshing current requirements and QC…</div>}
    {loadError && <Alert variant="warning">{loadError}</Alert>}
    {error && <Alert variant="warning">{error}</Alert>}
    {plan && <>
      <p className="mb-1">{plan.sample_code} · {plan.sample_status}{plan.run ? ` · ${plan.run.code} · run #${plan.run.id}` : ""}</p>
      <Alert variant={plan.readiness === "available" ? "success" : "info"}>{plan.summary}</Alert>
      {Object.keys(plan.intake_errors || {}).length > 0 && <Alert variant="warning">Intake fields need attention: {JSON.stringify(plan.intake_errors)}</Alert>}
      {plan.read_only && <p className="small">Sample edits require write access. QC controls appear only for authorized reviewers.</p>}
      {plan.last_run && <p>Previous run #{plan.last_run.id}: {plan.last_run.code} — {plan.last_run.status}. Starting a template creates a separate run.</p>}
      {plan.templates.length > 0 && <Form onSubmit={event => { event.preventDefault(); propose({ operation: "WORKFLOW_START", template_id: Number(template), plan_digest: plan.plan_digest }); }}>
        <Form.Label htmlFor={`${prefix}-template`}>Configured pipeline template</Form.Label>
        <Form.Select id={`${prefix}-template`} required value={template} onChange={event => setTemplate(event.target.value)} disabled={busy || disabled || refreshing}>
          <option value="">Choose the appropriate configured template</option>{plan.templates.map(item => <option key={item.id} value={item.id}>{item.code} — {item.name}</option>)}
        </Form.Select><Button size="sm" type="submit" className="my-2" disabled={busy || disabled || refreshing || !template}>Preview pipeline start</Button>
        {plan.templates_truncated && <p>Showing the first 50 active templates. Use the pipeline configuration page for the full list.</p>}
      </Form>}
      {plan.steps.map(step => <div key={step.id} className="border-top py-2" aria-label={`Workflow step ${step.position}`}>
        <strong>{step.position}. {step.name}</strong>{" "}<Badge bg="secondary">{step.status}</Badge>
        <div className="small">{step.work_item_id ? `Work #${step.work_item_id} · ${step.work_status} · ${step.assigned_to || "Unassigned"}` : "Work has not been activated"}{step.requires_qc ? ` · QC ${step.qc_status || "not available"}` : ""}</div>
        <p className="mb-1">{step.reason}</p>
        <details><summary>Requirements and recorded evidence</summary>
          <p>Required fields: {step.required_fields?.map(field => `${field.key} (${field.value_type})`).join(", ") || "None configured"}. Missing: {step.missing_fields.join(", ") || "None"}.</p>
          {step.form_schema?.fields?.length > 0 && <SampleFormFields fields={step.form_schema.fields} values={step.form_values} readOnly />}
          <Table size="sm" responsive><thead><tr><th>Key</th><th>Value</th><th>Result QC</th><th>Automated QC</th></tr></thead>
            <tbody>{step.results.map(result => <tr key={result.id}><td>{result.key}</td><td>{String(result.value ?? "")} {result.unit}</td><td>{result.qc_status}</td><td>{result.qc_passed == null ? "Not evaluated" : result.qc_passed ? "Passed" : "Failed"}</td></tr>)}</tbody></Table>
          {step.results_truncated && <p>Showing the first 100 results. Open the work item to inspect all evidence.</p>}
        </details>
        <StepEditor key={`${step.id}:${plan.plan_digest}`} step={step} sampleCode={plan.sample_code} planDigest={plan.plan_digest} propose={propose} onRun={onRun} disabled={busy || disabled || refreshing} />
      </div>)}
      {plan.notes.map(note => <p key={note} className="small text-muted mb-1">{note}</p>)}
    </>}
    <Button size="sm" variant="outline-secondary" disabled={busy || refreshing} onClick={() => setTick(value => value + 1)}>Refresh preparation checklist</Button>
  </section>;
}
