import { useEffect, useMemo, useState } from "react";
import { Alert, Badge, Button, Card, Col, Form, Row, Spinner, Table } from "react-bootstrap";
import { apiGet, apiGetAll, apiPost, apiPostForm } from "../api";
import { isAdmin, isTech } from "../authz";

function badge(status) {
  return { SUBMITTED: "info", TRIAGE: "warning", APPROVED: "success", IN_PROGRESS: "primary", COMPLETED: "dark", REJECTED: "danger", CANCELLED: "secondary" }[status] || "secondary";
}

function PipelineDag({ pipeline }) {
  if (!pipeline) return <div className="empty-state">No pipeline assigned.</div>;
  return <div className="d-flex flex-wrap gap-3 align-items-stretch">{pipeline.steps.map((step) => <Card className="soft-card" style={{ minWidth: 180 }} key={step.id}><Card.Body><Badge bg="dark">Step {step.position}</Badge><div className="fw-semibold mt-2">{step.display_name}</div><div className="feed-meta">After: {step.dependency_positions?.length ? step.dependency_positions.join(", ") : "start"}</div>{step.requires_qc && <Badge bg="warning" text="dark" className="mt-2">QC gate</Badge>}{step.optional && <Badge bg="secondary" className="mt-2 ms-1">Optional</Badge>}</Card.Body></Card>)}</div>;
}

export default function WorkflowRequests() {
  const [me, setMe] = useState(null);
  const [requestTypes, setRequestTypes] = useState([]);
  const [requests, setRequests] = useState([]);
  const [projects, setProjects] = useState([]);
  const [samples, setSamples] = useState([]);
  const [pipelines, setPipelines] = useState([]);
  const [inventoryItems, setInventoryItems] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [form, setForm] = useState({ request_type: "", project: "", title: "", priority: "NORMAL", form_data: "{}", sample_ids: [] });
  const [messageText, setMessageText] = useState("");
  const [reportFile, setReportFile] = useState(null);
  const [attachments, setAttachments] = useState([]);
  const [attachmentFile, setAttachmentFile] = useState(null);
  const [typeForm, setTypeForm] = useState({ code: "SEQUENCING", name: "Sequencing request", description: "", form_schema: '{\n  "type": "object",\n  "required": ["read_length"],\n  "properties": {\n    "read_length": { "type": "integer" }\n  }\n}', default_pipeline: "", project: "", sla_hours: 120 });
  const [resourceForm, setResourceForm] = useState({ request_type: "", inventory_item: "", quantity: "1", unit: "reaction" });

  async function load(selectId = null) {
    setError("");
    try {
      const [meData, typeRows, requestRows, projectRows, sampleRows, pipelineRows, itemRows] = await Promise.all([
        apiGet("/api/me/"), apiGetAll("/api/assay-request-types/"), apiGetAll("/api/workflow-requests/"),
        apiGetAll("/api/projects/"), apiGetAll("/api/samples/"), apiGetAll("/api/pipeline-templates/"), apiGetAll("/api/inventory-items/"),
      ]);
      setMe(meData); setRequestTypes(typeRows); setRequests(requestRows); setProjects(projectRows); setSamples(sampleRows); setPipelines(pipelineRows); setInventoryItems(itemRows);
      const target = requestRows.find((row) => String(row.id) === String(selectId || selected?.id)) || requestRows[0] || null;
      setSelected(target);
      setAttachments(
        target
          ? await apiGetAll(`/api/shared-attachments/?target_type=workflow_request&target_public_id=${target.public_id}`)
          : []
      );
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function submitRequest(event) {
    event.preventDefault();
    try {
      const created = await apiPost("/api/workflow-requests/", {
        ...form,
        request_type: Number(form.request_type), project: Number(form.project),
        sample_ids: form.sample_ids.map(Number), form_data: JSON.parse(form.form_data || "{}"),
      });
      setMessage(`Request ${created.request_number} submitted.`);
      setForm({ request_type: "", project: "", title: "", priority: "NORMAL", form_data: "{}", sample_ids: [] });
      await load(created.id);
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    }
  }

  async function requestAction(name, body = {}) {
    try {
      await apiPost(`/api/workflow-requests/${selected.id}/${name}/`, body);
      setMessage(`Request ${name} completed.`);
      await load(selected.id);
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    }
  }

  async function postMessage(event) {
    event.preventDefault();
    await apiPost("/api/workflow-request-messages/", { request: selected.id, body: messageText, internal_only: false });
    setMessageText("");
    await load(selected.id);
  }

  async function uploadReport(event) {
    event.preventDefault();
    if (!reportFile) return;
    const payload = new FormData();
    payload.append("request", selected.id);
    payload.append("title", reportFile.name);
    payload.append("file", reportFile);
    await apiPostForm("/api/workflow-request-reports/", payload);
    setReportFile(null);
    await load(selected.id);
  }

  async function uploadAttachment(event) {
    event.preventDefault();
    if (!attachmentFile) return;
    const payload = new FormData();
    payload.append("target_type", "workflow_request");
    payload.append("target_public_id", selected.public_id);
    payload.append("display_name", attachmentFile.name);
    payload.append("file", attachmentFile);
    await apiPostForm("/api/shared-attachments/", payload);
    setAttachmentFile(null);
    await load(selected.id);
  }

  async function createType(event) {
    event.preventDefault();
    const created = await apiPost("/api/assay-request-types/", { ...typeForm, code: typeForm.code.toUpperCase(), form_schema: JSON.parse(typeForm.form_schema), default_pipeline: typeForm.default_pipeline ? Number(typeForm.default_pipeline) : null, project: typeForm.project ? Number(typeForm.project) : null, sla_hours: Number(typeForm.sla_hours) });
    setMessage(`Request type ${created.code} created.`);
    await load();
  }

  async function addRequirement(event) {
    event.preventDefault();
    await apiPost("/api/request-resource-requirements/", { request_type: Number(resourceForm.request_type), kind: "MATERIAL", inventory_item: Number(resourceForm.inventory_item), quantity: resourceForm.quantity, unit: resourceForm.unit, required: true });
    setMessage("Material requirement added.");
    await load(selected?.id);
  }

  const projectSamples = samples.filter((sample) => String(sample.project) === String(form.project));
  const selectedPipeline = pipelines.find((pipeline) => pipeline.id === selected?.assigned_pipeline);
  const canOperate = isAdmin(me) || isTech(me);
  const selectedType = useMemo(() => requestTypes.find((type) => String(type.id) === String(form.request_type)), [requestTypes, form.request_type]);

  if (loading) return <div className="d-flex gap-2 align-items-center"><Spinner size="sm" /><span>Loading workflow requests...</span></div>;

  return <div className="w-100">
    <div className="page-header"><div><h1 className="page-title">Workflow Requests</h1><p className="page-subtitle">Submit internal assays, triage and approve work, reserve materials, group runs, and follow execution through QC and approved reports.</p></div><Button size="sm" variant="outline-dark" onClick={() => load(selected?.id)}>Refresh</Button></div>
    {error && <Alert variant="danger">{error}</Alert>}{message && <Alert variant="success" dismissible onClose={() => setMessage("")}>{message}</Alert>}

    <Card className="app-card mb-4"><Card.Body><h5 className="section-title">Submit an internal request</h5><Form onSubmit={submitRequest}><Row className="g-3"><Col md={3}><Form.Label>Assay / request type</Form.Label><Form.Select required value={form.request_type} onChange={(event) => { const type = requestTypes.find((row) => String(row.id) === event.target.value); setForm({ ...form, request_type: event.target.value, project: type?.project ? String(type.project) : form.project, priority: type?.default_priority || "NORMAL", form_data: "{}" }); }}><option value="">Choose request type</option>{requestTypes.filter((type) => type.active).map((type) => <option key={type.id} value={type.id}>{type.code} — {type.name}</option>)}</Form.Select></Col><Col md={3}><Form.Label>Project</Form.Label><Form.Select required value={form.project} onChange={(event) => setForm({ ...form, project: event.target.value, sample_ids: [] })}><option value="">Choose project</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.code} — {project.name}</option>)}</Form.Select></Col><Col md={4}><Form.Label>Title</Form.Label><Form.Control required value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></Col><Col md={2}><Form.Label>Priority</Form.Label><Form.Select value={form.priority} onChange={(event) => setForm({ ...form, priority: event.target.value })}><option>LOW</option><option>NORMAL</option><option>HIGH</option><option>URGENT</option></Form.Select></Col><Col md={6}><Form.Label>Custom submission data (JSON)</Form.Label><Form.Control as="textarea" rows={5} value={form.form_data} onChange={(event) => setForm({ ...form, form_data: event.target.value })} /><div className="feed-meta">Required schema: {selectedType ? JSON.stringify(selectedType.form_schema) : "choose a request type"}</div></Col><Col md={6}><Form.Label>Selected samples</Form.Label><div className="border rounded p-2" style={{ maxHeight: 145, overflowY: "auto" }}>{projectSamples.length === 0 ? <div className="feed-meta">Choose a project with samples.</div> : projectSamples.map((sample) => <Form.Check key={sample.id} label={`${sample.sample_id} · ${sample.sample_type}`} checked={form.sample_ids.includes(String(sample.id))} onChange={(event) => setForm({ ...form, sample_ids: event.target.checked ? [...form.sample_ids, String(sample.id)] : form.sample_ids.filter((id) => id !== String(sample.id)) })} />)}</div></Col><Col xs={12}><Button type="submit" variant="dark" disabled={!form.request_type || !form.project || form.sample_ids.length === 0}>Submit request</Button></Col></Row></Form></Card.Body></Card>

    {isAdmin(me) && <Card className="app-card mb-4"><Card.Body><h5 className="section-title">Director configuration</h5><Row className="g-4"><Col lg={7}><Form onSubmit={createType}><Row className="g-2"><Col md={3}><Form.Control required placeholder="Code" value={typeForm.code} onChange={(event) => setTypeForm({ ...typeForm, code: event.target.value })} /></Col><Col md={5}><Form.Control required placeholder="Name" value={typeForm.name} onChange={(event) => setTypeForm({ ...typeForm, name: event.target.value })} /></Col><Col md={4}><Form.Select value={typeForm.default_pipeline} onChange={(event) => setTypeForm({ ...typeForm, default_pipeline: event.target.value })}><option value="">Default pipeline</option>{pipelines.map((pipeline) => <option key={pipeline.id} value={pipeline.id}>{pipeline.code}</option>)}</Form.Select></Col><Col md={4}><Form.Select value={typeForm.project} onChange={(event) => setTypeForm({ ...typeForm, project: event.target.value })}><option value="">All projects</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.code}</option>)}</Form.Select></Col><Col md={2}><Form.Control type="number" min="1" value={typeForm.sla_hours} onChange={(event) => setTypeForm({ ...typeForm, sla_hours: event.target.value })} /></Col><Col md={6}><Form.Control value={typeForm.description} onChange={(event) => setTypeForm({ ...typeForm, description: event.target.value })} placeholder="Description" /></Col><Col xs={12}><Form.Control as="textarea" rows={5} value={typeForm.form_schema} onChange={(event) => setTypeForm({ ...typeForm, form_schema: event.target.value })} /></Col><Col xs={12}><Button type="submit">Create request type</Button></Col></Row></Form></Col><Col lg={5}><Form onSubmit={addRequirement}><Form.Select className="mb-2" required value={resourceForm.request_type} onChange={(event) => setResourceForm({ ...resourceForm, request_type: event.target.value })}><option value="">Request type</option>{requestTypes.map((type) => <option key={type.id} value={type.id}>{type.code}</option>)}</Form.Select><Form.Select className="mb-2" required value={resourceForm.inventory_item} onChange={(event) => { const item = inventoryItems.find((row) => String(row.id) === event.target.value); setResourceForm({ ...resourceForm, inventory_item: event.target.value, unit: item?.default_unit || "unit" }); }}><option value="">Required material</option>{inventoryItems.map((item) => <option key={item.id} value={item.id}>{item.code} — {item.name}</option>)}</Form.Select><Row className="g-2 mb-2"><Col><Form.Control type="number" min="0" step="any" value={resourceForm.quantity} onChange={(event) => setResourceForm({ ...resourceForm, quantity: event.target.value })} /></Col><Col><Form.Control value={resourceForm.unit} onChange={(event) => setResourceForm({ ...resourceForm, unit: event.target.value })} /></Col></Row><Button type="submit" variant="outline-dark">Add material requirement</Button></Form></Col></Row></Card.Body></Card>}

    <Row className="g-4"><Col lg={4}><Card className="app-card"><Card.Body><h5 className="section-title">Requests</h5><div className="d-grid gap-2">{requests.map((request) => <Button key={request.id} variant={selected?.id === request.id ? "dark" : "outline-secondary"} className="text-start" onClick={() => setSelected(request)}><div>{request.request_number} · {request.title}</div><small>{request.project_code} · {request.priority} · {request.status}</small></Button>)}</div></Card.Body></Card></Col><Col lg={8}>{selected ? <div className="d-grid gap-4">
      <Card className="app-card"><Card.Body><div className="toolbar-row"><div><h4 className="mb-1">{selected.request_number} — {selected.title}</h4><div className="feed-meta">Requested by {selected.requester_username} · due {selected.due_at ? new Date(selected.due_at).toLocaleString() : "not set"}</div></div><div className="inline-actions"><Badge bg={badge(selected.status)}>{selected.status}</Badge><Badge bg="secondary">{selected.priority}</Badge></div></div><div className="inline-actions mt-3">{canOperate && selected.status === "SUBMITTED" && <Button size="sm" variant="outline-warning" onClick={() => requestAction("triage", {})}>Start triage</Button>}{isAdmin(me) && ["SUBMITTED", "TRIAGE"].includes(selected.status) && <><Button size="sm" variant="success" onClick={() => requestAction("approve", { pipeline: selected.assigned_pipeline, reason: "Request and capacity approved" })}>Approve and reserve</Button><Button size="sm" variant="outline-danger" onClick={() => requestAction("reject", { reason: "Request rejected by director" })}>Reject</Button></>}{canOperate && ["APPROVED", "IN_PROGRESS"].includes(selected.status) && <Button size="sm" variant="outline-primary" onClick={() => requestAction("refresh_status")}>Refresh execution status</Button>}{selected.requester_username === me?.username && ["DRAFT", "SUBMITTED", "TRIAGE"].includes(selected.status) && <Button size="sm" variant="outline-secondary" onClick={() => requestAction("cancel", { reason: "Cancelled by requester" })}>Cancel request</Button>}</div></Card.Body></Card>
      <Card className="app-card"><Card.Body><h5 className="section-title">Assigned dependency graph</h5><PipelineDag pipeline={selectedPipeline} /></Card.Body></Card>
      <Card className="app-card"><Card.Body><h5 className="section-title">Samples, reservations, execution, results, and QC</h5>{selected.items.map((item) => <Card className="soft-card mb-3" key={item.public_id}><Card.Body><div className="toolbar-row"><strong>{item.sample_code || item.registry_id}</strong><Badge bg="secondary">{item.status}</Badge></div>{item.reservations.map((reservation) => <div className="feed-meta" key={reservation.public_id}>Reserved {reservation.quantity} {reservation.unit} from {reservation.lot_code} · {reservation.status}</div>)}{item.execution?.steps.map((step) => <div className="feed-item mt-2" key={step.position}><strong>{step.position}. {step.name}</strong> · {step.status}<div className="feed-meta">Work: {step.work_item_status || "not activated"} · QC: {step.qc_status || "—"}</div>{step.results.map((result) => <Badge bg="light" text="dark" className="me-1" key={result.key}>{result.key}: {String(result.value)} {result.unit}</Badge>)}</div>)}</Card.Body></Card>)}</Card.Body></Card>
      <Card className="app-card"><Card.Body><h5 className="section-title">Requester-visible messages</h5><Form onSubmit={postMessage} className="mb-3"><Row className="g-2"><Col><Form.Control required value={messageText} onChange={(event) => setMessageText(event.target.value)} placeholder="Message the requester or laboratory" /></Col><Col xs="auto"><Button type="submit">Send</Button></Col></Row></Form>{selected.messages.map((row) => <div className="feed-item mb-2" key={row.public_id}><strong>{row.author_username}</strong><div>{row.body}</div><div className="feed-meta">{new Date(row.created_at).toLocaleString()}</div></div>)}</Card.Body></Card>
      <Card className="app-card"><Card.Body><h5 className="section-title">Request attachments</h5><Form onSubmit={uploadAttachment} className="mb-3"><Row className="g-2"><Col><Form.Control type="file" onChange={(event) => setAttachmentFile(event.target.files?.[0] || null)} /></Col><Col xs="auto"><Button type="submit" disabled={!attachmentFile}>Upload attachment</Button></Col></Row></Form>{attachments.length === 0 ? <div className="empty-state">No request attachments.</div> : attachments.map((attachment) => <div className="feed-item mb-2" key={attachment.public_id}><a href={attachment.file}>{attachment.display_name || attachment.filename}</a><div className="feed-meta">{attachment.uploaded_by_username} · SHA-256 {attachment.sha256.slice(0, 12)}…</div></div>)}</Card.Body></Card>
      <Card className="app-card"><Card.Body><h5 className="section-title">Approved reports</h5>{canOperate && <Form onSubmit={uploadReport} className="mb-3"><Row className="g-2"><Col><Form.Control type="file" onChange={(event) => setReportFile(event.target.files?.[0] || null)} /></Col><Col xs="auto"><Button type="submit" disabled={!reportFile}>Upload report</Button></Col></Row></Form>}<Table responsive className="app-table"><thead><tr><th>Report</th><th>Checksum</th><th>Status</th><th></th></tr></thead><tbody>{selected.reports.map((report) => <tr key={report.public_id}><td><a href={report.file}>{report.title}</a></td><td><code>{report.checksum_sha256.slice(0, 12)}…</code></td><td>{report.approved ? "Approved" : "Pending approval"}</td><td>{isAdmin(me) && !report.approved && <Button size="sm" onClick={async () => { await apiPost(`/api/workflow-request-reports/${report.id}/approve/`, {}); await load(selected.id); }}>Approve report</Button>}</td></tr>)}</tbody></Table></Card.Body></Card>
    </div> : <Card className="app-card"><Card.Body><div className="empty-state">Choose a request.</div></Card.Body></Card>}</Col></Row>
  </div>;
}
