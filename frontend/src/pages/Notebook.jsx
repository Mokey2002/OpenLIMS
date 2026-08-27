import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Badge, Button, Card, Col, Form, Row, Spinner, Table } from "react-bootstrap";
import { apiDownload, apiGet, apiGetAll, apiPost } from "../api";
import { isAdmin } from "../authz";

const defaultBlocks = [
  { block_type: "HEADING", data: { text: "Experiment objective" } },
  { block_type: "RICH_TEXT", data: { text: "Describe the objective and context." } },
  { block_type: "PROTOCOL_STEP", data: { text: "Record the first protocol step", completed: false } },
  { block_type: "STRUCTURED_RESULT", data: { name: "Result", value: "", unit: "" } },
];

const blockTypes = [
  "RICH_TEXT", "HEADING", "TABLE", "CHECKLIST", "PROTOCOL_STEP",
  "CALCULATION", "IMAGE", "ATTACHMENT", "STRUCTURED_RESULT", "SEQUENCE_VIEW",
];

function blockText(block) {
  return JSON.stringify(block.data || {}, null, 2);
}

function statusColor(status) {
  return { DRAFT: "secondary", IN_PROGRESS: "primary", COMPLETED: "warning", REVIEWED: "success", LOCKED: "dark" }[status] || "secondary";
}

export default function NotebookPage() {
  const [me, setMe] = useState(null);
  const [notebooks, setNotebooks] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [experiments, setExperiments] = useState([]);
  const [projects, setProjects] = useState([]);
  const [users, setUsers] = useState([]);
  const [selected, setSelected] = useState(null);
  const [blocks, setBlocks] = useState([]);
  const [links, setLinks] = useState([]);
  const [linkTargets, setLinkTargets] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [saveState, setSaveState] = useState("");
  const [notebookForm, setNotebookForm] = useState({ name: "", scope: "PROJECT", project: "" });
  const [templateForm, setTemplateForm] = useState({ notebook: "", name: "", description: "" });
  const [experimentForm, setExperimentForm] = useState({ template: "", title: "" });
  const [linkForm, setLinkForm] = useState({ entity_type: "registry_record", public_id: "", relation_type: "used" });
  const [comment, setComment] = useState("");
  const autosaveTimer = useRef(null);

  async function load(selectId = null) {
    setError("");
    try {
      const [meData, notebookRows, templateRows, experimentRows, projectRows, userRows, registryRows, sampleRows, lotRows, runRows, workRows, resultRows, sopRows, sequenceRows] = await Promise.all([
        apiGet("/api/me/"), apiGetAll("/api/notebooks/"), apiGetAll("/api/experiment-templates/"),
        apiGetAll("/api/experiments/"), apiGetAll("/api/projects/"), apiGetAll("/api/users/"),
        apiGetAll("/api/registry-records/"), apiGetAll("/api/samples/"), apiGetAll("/api/inventory-lots/"),
        apiGetAll("/api/pipeline-runs/"), apiGetAll("/api/work-items/"), apiGetAll("/api/results/"),
        apiGetAll("/api/sop-documents/"), apiGetAll("/api/sequences/"),
      ]);
      setMe(meData);
      setNotebooks(notebookRows);
      setTemplates(templateRows);
      setExperiments(experimentRows);
      setProjects(projectRows);
      setUsers(userRows);
      setLinkTargets({
        registry_record: registryRows, sample: sampleRows, inventory_lot: lotRows,
        pipeline_run: runRows, work_item: workRows, result: resultRows,
        sop_document: sopRows, sequence: sequenceRows,
      });
      const target = experimentRows.find((row) => String(row.id) === String(selectId || selected?.id)) || experimentRows[0] || null;
      setSelected(target);
      setBlocks((target?.current_revision_detail?.blocks || []).map((block) => ({ block_type: block.block_type, data: block.data })));
      setLinks((target?.current_revision_detail?.links || []).map((link) => ({ entity_type: link.entity_type, public_id: link.entity_public_id, relation_type: link.relation_type, label: link.label })));
      if (!templateForm.notebook && notebookRows[0]) setTemplateForm((current) => ({ ...current, notebook: String(notebookRows[0].id) }));
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    return () => clearTimeout(autosaveTimer.current);
    // The workspace loads once; subsequent refreshes are explicit or action-driven.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function selectExperiment(experiment) {
    clearTimeout(autosaveTimer.current);
    setSelected(experiment);
    setBlocks((experiment.current_revision_detail?.blocks || []).map((block) => ({ block_type: block.block_type, data: block.data })));
    setLinks((experiment.current_revision_detail?.links || []).map((link) => ({ entity_type: link.entity_type, public_id: link.entity_public_id, relation_type: link.relation_type, label: link.label })));
    setSaveState("");
  }

  function scheduleAutosave(nextBlocks, nextLinks) {
    if (!selected?.permissions?.write || !["DRAFT", "IN_PROGRESS"].includes(selected.status)) return;
    clearTimeout(autosaveTimer.current);
    setSaveState("Unsaved changes");
    autosaveTimer.current = setTimeout(async () => {
      try {
        setSaveState("Saving...");
        await apiPost(`/api/experiments/${selected.id}/autosave/`, { blocks: nextBlocks, links: nextLinks, reason: "Notebook autosave" });
        setSaveState("Saved");
      } catch (requestError) {
        setSaveState("Autosave failed");
        setError(requestError.message || String(requestError));
      }
    }, 900);
  }

  async function createNotebook(event) {
    event.preventDefault();
    const created = await apiPost("/api/notebooks/", { ...notebookForm, project: notebookForm.scope === "PROJECT" ? Number(notebookForm.project) : null });
    setNotebookForm({ name: "", scope: "PROJECT", project: "" });
    setMessage(`Notebook ${created.name} created.`);
    await load();
  }

  async function createTemplate(event) {
    event.preventDefault();
    const created = await apiPost("/api/experiment-templates/", { ...templateForm, notebook: Number(templateForm.notebook), blocks: defaultBlocks });
    setTemplateForm((current) => ({ ...current, name: "", description: "" }));
    setMessage(`Template ${created.name} created.`);
    await load();
  }

  async function createExperiment(event) {
    event.preventDefault();
    const template = templates.find((row) => String(row.id) === experimentForm.template);
    if (!template) return;
    const created = await apiPost(`/api/experiment-templates/${template.id}/instantiate/`, { title: experimentForm.title || template.name });
    setExperimentForm({ template: "", title: "" });
    setMessage("Experiment created from template.");
    await load(created.id);
  }

  function updateBlock(index, rawData) {
    try {
      const data = JSON.parse(rawData);
      const next = blocks.map((block, blockIndex) => blockIndex === index ? { ...block, data } : block);
      setBlocks(next);
      scheduleAutosave(next, links);
      setError("");
    } catch {
      setError("Block data must be valid JSON before it can be autosaved.");
    }
  }

  function addBlock(type) {
    const data = type === "TABLE" ? { rows: [["Column 1", "Column 2"], ["", ""]] } : type === "CHECKLIST" ? { items: [{ text: "New item", checked: false }] } : { text: "" };
    const next = [...blocks, { block_type: type, data }];
    setBlocks(next);
    scheduleAutosave(next, links);
  }

  function removeBlock(index) {
    const next = blocks.filter((_, blockIndex) => blockIndex !== index);
    setBlocks(next);
    scheduleAutosave(next, links);
  }

  function addLink(event) {
    event.preventDefault();
    const target = (linkTargets[linkForm.entity_type] || []).find((row) => String(row.public_id) === linkForm.public_id);
    if (!target) return;
    const label = target.registry_id || target.sample_id || target.lot_code || target.document_code || target.name || target.template_code || target.key;
    const next = [...links, { entity_type: linkForm.entity_type, public_id: target.public_id, relation_type: linkForm.relation_type, label }];
    setLinks(next);
    setLinkForm((current) => ({ ...current, public_id: "" }));
    scheduleAutosave(blocks, next);
  }

  async function action(path, body = {}) {
    clearTimeout(autosaveTimer.current);
    try {
      await apiPost(path, body);
      setMessage("Experiment updated.");
      await load(selected.id);
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    }
  }

  async function addComment(event) {
    event.preventDefault();
    if (!comment.trim()) return;
    await apiPost("/api/experiment-comments/", { experiment: selected.id, revision: selected.current_revision, body: comment, mentions: [] });
    setComment("");
    await load(selected.id);
  }

  const targetOptions = linkTargets[linkForm.entity_type] || [];
  const selectedNotebookTemplates = useMemo(() => templates.filter((template) => !templateForm.notebook || String(template.notebook) === String(templateForm.notebook)), [templates, templateForm.notebook]);

  if (loading) return <div className="d-flex gap-2 align-items-center"><Spinner size="sm" /><span>Loading Notebook...</span></div>;

  return (
    <div className="w-100">
      <div className="page-header"><div><h1 className="page-title">Laboratory Notebook</h1><p className="page-subtitle">Collaborative experiments with autosave, immutable revisions, exact material provenance, review, and lock controls.</p></div><Button size="sm" variant="outline-dark" onClick={() => load(selected?.id)}>Refresh</Button></div>
      {error && <Alert variant="danger">{error}</Alert>}
      {message && <Alert variant="success" dismissible onClose={() => setMessage("")}>{message}</Alert>}

      <Row className="g-4 mb-4">
        <Col lg={4}><Card className="app-card h-100"><Card.Body><h5 className="section-title">Create notebook</h5><Form onSubmit={createNotebook}><Form.Control className="mb-2" required placeholder="Notebook name" value={notebookForm.name} onChange={(event) => setNotebookForm({ ...notebookForm, name: event.target.value })} /><Form.Select className="mb-2" value={notebookForm.scope} onChange={(event) => setNotebookForm({ ...notebookForm, scope: event.target.value })}><option value="USER">User</option><option value="TEAM">Team</option><option value="PROJECT">Project</option></Form.Select>{notebookForm.scope === "PROJECT" && <Form.Select className="mb-2" required value={notebookForm.project} onChange={(event) => setNotebookForm({ ...notebookForm, project: event.target.value })}><option value="">Choose project</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.code} — {project.name}</option>)}</Form.Select>}<Button type="submit" variant="dark">Create notebook</Button></Form></Card.Body></Card></Col>
        <Col lg={4}><Card className="app-card h-100"><Card.Body><h5 className="section-title">Create template</h5><Form onSubmit={createTemplate}><Form.Select className="mb-2" required value={templateForm.notebook} onChange={(event) => setTemplateForm({ ...templateForm, notebook: event.target.value })}><option value="">Choose notebook</option>{notebooks.filter((row) => row.permissions.write).map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</Form.Select><Form.Control className="mb-2" required placeholder="Template name" value={templateForm.name} onChange={(event) => setTemplateForm({ ...templateForm, name: event.target.value })} /><Form.Control className="mb-2" placeholder="Description" value={templateForm.description} onChange={(event) => setTemplateForm({ ...templateForm, description: event.target.value })} /><Button type="submit" variant="dark">Create block template</Button></Form></Card.Body></Card></Col>
        <Col lg={4}><Card className="app-card h-100"><Card.Body><h5 className="section-title">Clone from template</h5><Form onSubmit={createExperiment}><Form.Select className="mb-2" required value={experimentForm.template} onChange={(event) => setExperimentForm({ ...experimentForm, template: event.target.value })}><option value="">Choose template</option>{selectedNotebookTemplates.filter((row) => row.active).map((row) => <option key={row.id} value={row.id}>{row.notebook_name} — {row.name}</option>)}</Form.Select><Form.Control className="mb-2" placeholder="Experiment title" value={experimentForm.title} onChange={(event) => setExperimentForm({ ...experimentForm, title: event.target.value })} /><Button type="submit" variant="dark">Create experiment</Button></Form></Card.Body></Card></Col>
      </Row>

      <Row className="g-4">
        <Col lg={4}><Card className="app-card"><Card.Body><h5 className="section-title">Experiments</h5>{experiments.length === 0 ? <div className="empty-state">No experiments yet.</div> : <div className="d-grid gap-2">{experiments.map((experiment) => <Button key={experiment.id} variant={selected?.id === experiment.id ? "dark" : "outline-secondary"} className="text-start" onClick={() => selectExperiment(experiment)}><div>{experiment.title}</div><small>{experiment.project_code || experiment.notebook_name} · r{experiment.current_revision_detail?.number || 0} · {experiment.status}</small></Button>)}</div>}</Card.Body></Card></Col>
        <Col lg={8}>{selected ? <div className="d-grid gap-4">
          <Card className="app-card"><Card.Body><div className="toolbar-row"><div><h4 className="mb-1">{selected.title}</h4><div className="feed-meta">{selected.notebook_name} · {selected.project_code || "Private/team"} · author {selected.created_by_username}</div></div><div className="inline-actions"><Badge bg={statusColor(selected.status)}>{selected.status}</Badge>{saveState && <Badge bg={saveState === "Saved" ? "success" : "secondary"}>{saveState}</Badge>}</div></div><div className="inline-actions mt-3">{selected.permissions.write && ["DRAFT", "IN_PROGRESS"].includes(selected.status) && <Button size="sm" variant="outline-dark" onClick={() => action(`/api/experiments/${selected.id}/transition/`, { status: "COMPLETED", reason: "Experiment execution completed" })}>Complete</Button>}{selected.permissions.review && selected.status === "COMPLETED" && <><Button size="sm" variant="success" onClick={() => action(`/api/experiments/${selected.id}/review/`, { decision: "APPROVED", comment: "Reviewed in Notebook", signed_name: me?.username })}>Approve</Button><Button size="sm" variant="outline-warning" onClick={() => action(`/api/experiments/${selected.id}/review/`, { decision: "CHANGES_REQUESTED", comment: "Changes requested" })}>Request changes</Button></>}{selected.permissions.lock && selected.status === "REVIEWED" && <Button size="sm" variant="dark" onClick={() => action(`/api/experiments/${selected.id}/lock/`, { reason: "Final reviewed experiment" })}>Lock</Button>}<Button size="sm" variant="outline-secondary" onClick={() => action(`/api/experiments/${selected.id}/clone/`, { title: `Copy of ${selected.title}` })}>Clone experiment</Button><Button size="sm" variant="outline-primary" onClick={() => apiDownload(`/api/experiments/${selected.id}/export-pdf/`, `${selected.title}.pdf`)}>Export PDF</Button></div></Card.Body></Card>

          <Card className="app-card"><Card.Body><div className="toolbar-row"><div><h5 className="section-title mb-1">Experiment blocks</h5><div className="feed-meta">Every autosave creates a new immutable revision only when content changed.</div></div>{selected.permissions.write && ["DRAFT", "IN_PROGRESS"].includes(selected.status) && <Form.Select size="sm" style={{ width: 210 }} defaultValue="" onChange={(event) => { if (event.target.value) addBlock(event.target.value); event.target.value = ""; }}><option value="">Add block...</option>{blockTypes.map((type) => <option key={type} value={type}>{type}</option>)}</Form.Select>}</div>{blocks.map((block, index) => <Card className="soft-card mb-3" key={`${block.block_type}-${index}`}><Card.Body><div className="toolbar-row mb-2"><Badge bg="secondary">{index + 1}. {block.block_type}</Badge>{selected.permissions.write && ["DRAFT", "IN_PROGRESS"].includes(selected.status) && <Button size="sm" variant="outline-danger" onClick={() => removeBlock(index)}>Remove</Button>}</div><Form.Control as="textarea" rows={Math.min(10, Math.max(3, blockText(block).split("\n").length))} defaultValue={blockText(block)} disabled={!selected.permissions.write || !["DRAFT", "IN_PROGRESS"].includes(selected.status)} onBlur={(event) => updateBlock(index, event.target.value)} /></Card.Body></Card>)}</Card.Body></Card>

          <Card className="app-card"><Card.Body><h5 className="section-title">Exact linked versions</h5>{selected.permissions.write && ["DRAFT", "IN_PROGRESS"].includes(selected.status) && <Form onSubmit={addLink}><Row className="g-2"><Col md={3}><Form.Select value={linkForm.entity_type} onChange={(event) => setLinkForm({ ...linkForm, entity_type: event.target.value, public_id: "" })}>{Object.keys(linkTargets).map((type) => <option key={type} value={type}>{type}</option>)}</Form.Select></Col><Col md={5}><Form.Select required value={linkForm.public_id} onChange={(event) => setLinkForm({ ...linkForm, public_id: event.target.value })}><option value="">Choose exact record</option>{targetOptions.map((target) => <option key={target.public_id} value={target.public_id}>{target.registry_id || target.sample_id || target.lot_code || target.document_code || target.name || target.template_code || target.key}</option>)}</Form.Select></Col><Col md={2}><Form.Control value={linkForm.relation_type} onChange={(event) => setLinkForm({ ...linkForm, relation_type: event.target.value })} /></Col><Col md={2}><Button type="submit" className="w-100">Link</Button></Col></Row></Form>}<Table responsive className="app-table mt-3"><thead><tr><th>Type</th><th>Record</th><th>Relation</th><th>Captured version</th></tr></thead><tbody>{(selected.current_revision_detail?.links || []).map((link) => <tr key={link.public_id}><td>{link.entity_type}</td><td>{link.label}</td><td>{link.relation_type}</td><td><code>{JSON.stringify(link.version)}</code></td></tr>)}</tbody></Table></Card.Body></Card>

          <Card className="app-card"><Card.Body><h5 className="section-title">Revision history</h5><Table responsive className="app-table"><thead><tr><th>Revision</th><th>Author</th><th>Timestamp</th><th>Change</th><th>Checksum</th><th></th></tr></thead><tbody>{selected.revisions.map((revision) => <tr key={revision.public_id}><td>r{revision.number}</td><td>{revision.created_by_username || "System"}</td><td>{new Date(revision.created_at).toLocaleString()}</td><td>{revision.change_summary}</td><td><code>{revision.checksum.slice(0, 12)}…</code></td><td>{selected.permissions.write && ["DRAFT", "IN_PROGRESS"].includes(selected.status) && revision.number !== selected.current_revision_detail?.number && <Button size="sm" variant="outline-dark" onClick={() => action(`/api/experiments/${selected.id}/restore/`, { revision_public_id: revision.public_id, reason: `Restore r${revision.number}` })}>Restore</Button>}</td></tr>)}</tbody></Table></Card.Body></Card>

          <Card className="app-card"><Card.Body><h5 className="section-title">Comments, mentions, and assignments</h5>{selected.permissions.comment && <Form onSubmit={addComment} className="mb-3"><Row className="g-2"><Col><Form.Control required value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Comment on the signed-off content without modifying it" /></Col><Col xs="auto"><Button type="submit">Comment</Button></Col></Row></Form>}{selected.comments.map((row) => <div className="feed-item mb-2" key={row.public_id}><strong>{row.author_username}</strong><div>{row.body}</div><div className="feed-meta">{new Date(row.created_at).toLocaleString()} · revision {row.revision || "general"}{row.assigned_to_username ? ` · assigned to ${row.assigned_to_username}` : ""}</div></div>)}</Card.Body></Card>
        </div> : <Card className="app-card"><Card.Body><div className="empty-state">Choose an experiment.</div></Card.Body></Card>}</Col>
      </Row>
      {isAdmin(me) && users.length > 0 && <div className="feed-meta mt-4">Directors can configure notebook readers, editors, commenters, reviewers, and lockers through the Notebook API.</div>}
    </div>
  );
}
