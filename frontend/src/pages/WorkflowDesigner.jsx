import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  Row,
  Spinner,
  Table,
} from "react-bootstrap";
import { apiGet, apiGetAll, apiPatch, apiPost } from "../api";
import { isAdmin } from "../authz";

function emptyRequiredField() {
  return { key: "", label: "", value_type: "STRING", required: true, unit: "" };
}

function emptyAnalysis() {
  return {
    code: "",
    name: "",
    category: "",
    description: "",
    required_fields: [emptyRequiredField()],
    active: true,
  };
}

function emptyProcedure() {
  return {
    code: "",
    name: "",
    version: "1",
    analysis: "",
    sop_document: "",
    instructions: "",
    estimated_duration_minutes: 60,
    active: true,
  };
}

function emptyPipelineStep() {
  return { procedure: "", name: "", requires_qc: false };
}

function emptyPipeline() {
  return {
    code: "",
    name: "",
    description: "",
    active: true,
    is_default: false,
    default_project: "",
    default_sample_type: "",
    steps: [emptyPipelineStep()],
  };
}

function requiredFieldSummary(fields) {
  const required = (fields || []).filter((field) => field.required !== false);
  return required.length
    ? required.map((field) => `${field.label || field.key} (${field.value_type})`).join(", ")
    : "None";
}

export default function WorkflowDesigner() {
  const [me, setMe] = useState(null);
  const [analyses, setAnalyses] = useState([]);
  const [procedures, setProcedures] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [projects, setProjects] = useState([]);
  const [sops, setSops] = useState([]);
  const [analysisForm, setAnalysisForm] = useState(emptyAnalysis);
  const [procedureForm, setProcedureForm] = useState(emptyProcedure);
  const [pipelineForm, setPipelineForm] = useState(emptyPipeline);
  const [analysisEditingId, setAnalysisEditingId] = useState(null);
  const [procedureEditingId, setProcedureEditingId] = useState(null);
  const [pipelineEditingId, setPipelineEditingId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const meData = await apiGet("/api/me/");
      setMe(meData);
      if (!isAdmin(meData)) return;
      const [analysisRows, procedureRows, templateRows, projectRows, sopRows] =
        await Promise.all([
          apiGetAll("/api/analysis-definitions/"),
          apiGetAll("/api/procedure-definitions/"),
          apiGetAll("/api/pipeline-templates/"),
          apiGetAll("/api/projects/"),
          apiGetAll("/api/sop-documents/"),
        ]);
      setAnalyses(analysisRows);
      setProcedures(procedureRows);
      setTemplates(templateRows);
      setProjects(projectRows);
      setSops(sopRows);
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, []);

  const activeProcedures = useMemo(
    () => procedures.filter((procedure) => procedure.active),
    [procedures]
  );

  function updateRequiredField(index, field, value) {
    setAnalysisForm((current) => ({
      ...current,
      required_fields: current.required_fields.map((item, itemIndex) =>
        itemIndex === index ? { ...item, [field]: value } : item
      ),
    }));
  }

  function resetAnalysis() {
    setAnalysisForm(emptyAnalysis());
    setAnalysisEditingId(null);
  }

  function editAnalysis(analysis) {
    setAnalysisEditingId(analysis.id);
    setAnalysisForm({
      code: analysis.code,
      name: analysis.name,
      category: analysis.category || "",
      description: analysis.description || "",
      required_fields: analysis.required_fields?.length
        ? analysis.required_fields
        : [emptyRequiredField()],
      active: analysis.active,
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function saveAnalysis(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setSuccess("");
    const payload = {
      ...analysisForm,
      required_fields: analysisForm.required_fields.filter((field) => field.key.trim()),
    };
    try {
      const result = analysisEditingId
        ? await apiPatch(`/api/analysis-definitions/${analysisEditingId}/`, payload)
        : await apiPost("/api/analysis-definitions/", payload);
      setSuccess(`Analysis ${result.code} ${analysisEditingId ? "updated" : "created"}.`);
      resetAnalysis();
      await load();
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    } finally {
      setSaving(false);
    }
  }

  function resetProcedure() {
    setProcedureForm(emptyProcedure());
    setProcedureEditingId(null);
  }

  function editProcedure(procedure) {
    setProcedureEditingId(procedure.id);
    setProcedureForm({
      code: procedure.code,
      name: procedure.name,
      version: procedure.version,
      analysis: String(procedure.analysis),
      sop_document: procedure.sop_document ? String(procedure.sop_document) : "",
      instructions: procedure.instructions || "",
      estimated_duration_minutes: procedure.estimated_duration_minutes,
      active: procedure.active,
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function saveProcedure(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setSuccess("");
    const payload = {
      ...procedureForm,
      analysis: Number(procedureForm.analysis),
      sop_document: procedureForm.sop_document ? Number(procedureForm.sop_document) : null,
      estimated_duration_minutes: Number(procedureForm.estimated_duration_minutes),
    };
    try {
      const result = procedureEditingId
        ? await apiPatch(`/api/procedure-definitions/${procedureEditingId}/`, payload)
        : await apiPost("/api/procedure-definitions/", payload);
      setSuccess(`Procedure ${result.code} v${result.version} ${procedureEditingId ? "updated" : "created"}.`);
      resetProcedure();
      await load();
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    } finally {
      setSaving(false);
    }
  }

  function updatePipelineStep(index, field, value) {
    setPipelineForm((current) => ({
      ...current,
      steps: current.steps.map((step, stepIndex) =>
        stepIndex === index ? { ...step, [field]: value } : step
      ),
    }));
  }

  function movePipelineStep(index, direction) {
    setPipelineForm((current) => {
      const nextIndex = index + direction;
      if (nextIndex < 0 || nextIndex >= current.steps.length) return current;
      const steps = [...current.steps];
      [steps[index], steps[nextIndex]] = [steps[nextIndex], steps[index]];
      return { ...current, steps };
    });
  }

  function resetPipeline() {
    setPipelineForm(emptyPipeline());
    setPipelineEditingId(null);
  }

  function editPipeline(template) {
    setPipelineEditingId(template.id);
    setPipelineForm({
      code: template.code,
      name: template.name,
      description: template.description || "",
      active: template.active,
      is_default: template.is_default,
      default_project: template.default_project ? String(template.default_project) : "",
      default_sample_type: template.default_sample_type || "",
      steps: template.steps.map((step) => ({
        procedure: String(step.procedure),
        name: step.name || "",
        requires_qc: step.requires_qc,
      })),
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function savePipeline(event) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setSuccess("");
    const payload = {
      ...pipelineForm,
      default_project: pipelineForm.default_project
        ? Number(pipelineForm.default_project)
        : null,
      steps: pipelineForm.steps.map((step, index) => ({
        ...step,
        position: index + 1,
        procedure: Number(step.procedure),
      })),
    };
    try {
      const result = pipelineEditingId
        ? await apiPatch(`/api/pipeline-templates/${pipelineEditingId}/`, payload)
        : await apiPost("/api/pipeline-templates/", payload);
      setSuccess(`Pipeline ${result.code} ${pipelineEditingId ? "updated" : "created"}.`);
      resetPipeline();
      await load();
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return <div className="d-flex gap-2 align-items-center"><Spinner size="sm" /><span>Loading workflow configuration...</span></div>;
  }

  if (!isAdmin(me)) {
    return <Alert variant="warning">Director/admin access is required to configure analyses, procedures, and pipelines.</Alert>;
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Workflow Designer</h1>
          <p className="page-subtitle">
            Configure analysis requirements, versioned procedures, reusable ordered pipelines, and project or sample-type defaults.
          </p>
        </div>
        <div className="inline-actions"><Badge bg="dark">Director only</Badge><Button size="sm" variant="outline-dark" onClick={load}>Refresh</Button></div>
      </div>

      {error && <Alert variant="danger">{error}</Alert>}
      {success && <Alert variant="success">{success}</Alert>}

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">1. Analysis definitions</h5>
          <Form onSubmit={saveAnalysis}>
            <Row className="g-3">
              <Col md={3}><Form.Label>Code</Form.Label><Form.Control required value={analysisForm.code} onChange={(event) => setAnalysisForm({ ...analysisForm, code: event.target.value })} placeholder="EXTRACTION" /></Col>
              <Col md={5}><Form.Label>Name</Form.Label><Form.Control required value={analysisForm.name} onChange={(event) => setAnalysisForm({ ...analysisForm, name: event.target.value })} /></Col>
              <Col md={4}><Form.Label>Category</Form.Label><Form.Control value={analysisForm.category} onChange={(event) => setAnalysisForm({ ...analysisForm, category: event.target.value })} placeholder="Genomics" /></Col>
              <Col xs={12}><Form.Label>Description</Form.Label><Form.Control as="textarea" rows={2} value={analysisForm.description} onChange={(event) => setAnalysisForm({ ...analysisForm, description: event.target.value })} /></Col>
            </Row>
            <div className="toolbar-row mt-3 mb-2"><div><strong>Required result fields</strong><div className="feed-meta">A pipeline step cannot complete until required results are recorded.</div></div><Button type="button" size="sm" variant="outline-dark" onClick={() => setAnalysisForm({ ...analysisForm, required_fields: [...analysisForm.required_fields, emptyRequiredField()] })}>Add field</Button></div>
            {analysisForm.required_fields.map((field, index) => (
              <Row className="g-2 mb-2" key={index}>
                <Col md={3}><Form.Control value={field.key} onChange={(event) => updateRequiredField(index, "key", event.target.value)} placeholder="Result key" /></Col>
                <Col md={3}><Form.Control value={field.label} onChange={(event) => updateRequiredField(index, "label", event.target.value)} placeholder="Display label" /></Col>
                <Col md={2}><Form.Select value={field.value_type} onChange={(event) => updateRequiredField(index, "value_type", event.target.value)}><option>STRING</option><option>NUMBER</option><option>BOOLEAN</option></Form.Select></Col>
                <Col md={2}><Form.Control value={field.unit} onChange={(event) => updateRequiredField(index, "unit", event.target.value)} placeholder="Unit" /></Col>
                <Col md={1} className="d-flex align-items-center"><Form.Check label="Required" checked={field.required} onChange={(event) => updateRequiredField(index, "required", event.target.checked)} /></Col>
                <Col md={1}><Button type="button" variant="outline-danger" className="w-100" onClick={() => setAnalysisForm({ ...analysisForm, required_fields: analysisForm.required_fields.filter((_, itemIndex) => itemIndex !== index) })}>×</Button></Col>
              </Row>
            ))}
            <div className="inline-actions mt-3"><Button type="submit" variant="dark" disabled={saving || !analysisForm.code || !analysisForm.name}>{analysisEditingId ? "Update analysis" : "Create analysis"}</Button>{analysisEditingId && <Button type="button" variant="outline-secondary" onClick={resetAnalysis}>Cancel edit</Button>}</div>
          </Form>

          <Table responsive hover className="app-table mt-4">
            <thead><tr><th>Analysis</th><th>Category</th><th>Required results</th><th>Status</th><th></th></tr></thead>
            <tbody>{analyses.map((analysis) => <tr key={analysis.id}><td><strong>{analysis.code}</strong><div className="feed-meta">{analysis.name}</div></td><td>{analysis.category || "—"}</td><td>{requiredFieldSummary(analysis.required_fields)}</td><td><Badge bg={analysis.active ? "success" : "secondary"}>{analysis.active ? "Active" : "Inactive"}</Badge></td><td><Button size="sm" variant="outline-dark" onClick={() => editAnalysis(analysis)}>Edit</Button></td></tr>)}</tbody>
          </Table>
        </Card.Body>
      </Card>

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">2. Procedure definitions</h5>
          <Form onSubmit={saveProcedure}>
            <Row className="g-3">
              <Col md={3}><Form.Label>Code</Form.Label><Form.Control required value={procedureForm.code} onChange={(event) => setProcedureForm({ ...procedureForm, code: event.target.value })} placeholder="DNA-EXT" /></Col>
              <Col md={4}><Form.Label>Name</Form.Label><Form.Control required value={procedureForm.name} onChange={(event) => setProcedureForm({ ...procedureForm, name: event.target.value })} /></Col>
              <Col md={2}><Form.Label>Version</Form.Label><Form.Control required value={procedureForm.version} onChange={(event) => setProcedureForm({ ...procedureForm, version: event.target.value })} /></Col>
              <Col md={3}><Form.Label>Analysis</Form.Label><Form.Select required value={procedureForm.analysis} onChange={(event) => setProcedureForm({ ...procedureForm, analysis: event.target.value })}><option value="">Select analysis</option>{analyses.filter((analysis) => analysis.active).map((analysis) => <option key={analysis.id} value={analysis.id}>{analysis.code} — {analysis.name}</option>)}</Form.Select></Col>
              <Col md={4}><Form.Label>Linked SOP</Form.Label><Form.Select value={procedureForm.sop_document} onChange={(event) => setProcedureForm({ ...procedureForm, sop_document: event.target.value })}><option value="">No linked SOP</option>{sops.map((sop) => <option key={sop.id} value={sop.id}>{sop.document_code} v{sop.version} — {sop.title}</option>)}</Form.Select></Col>
              <Col md={3}><Form.Label>Expected duration (minutes)</Form.Label><Form.Control type="number" min="1" required value={procedureForm.estimated_duration_minutes} onChange={(event) => setProcedureForm({ ...procedureForm, estimated_duration_minutes: event.target.value })} /></Col>
              <Col md={5}><Form.Label>Instructions</Form.Label><Form.Control value={procedureForm.instructions} onChange={(event) => setProcedureForm({ ...procedureForm, instructions: event.target.value })} /></Col>
            </Row>
            <div className="inline-actions mt-3"><Button type="submit" variant="dark" disabled={saving || !procedureForm.code || !procedureForm.name || !procedureForm.analysis}>{procedureEditingId ? "Update procedure" : "Create procedure"}</Button>{procedureEditingId && <Button type="button" variant="outline-secondary" onClick={resetProcedure}>Cancel edit</Button>}</div>
          </Form>
          <Table responsive hover className="app-table mt-4">
            <thead><tr><th>Procedure</th><th>Analysis</th><th>SOP</th><th>Duration</th><th>Status</th><th></th></tr></thead>
            <tbody>{procedures.map((procedure) => <tr key={procedure.id}><td><strong>{procedure.code} v{procedure.version}</strong><div className="feed-meta">{procedure.name}</div></td><td>{procedure.analysis_code}</td><td>{procedure.sop_document_code || "—"}</td><td>{procedure.estimated_duration_minutes} min</td><td><Badge bg={procedure.active ? "success" : "secondary"}>{procedure.active ? "Active" : "Inactive"}</Badge></td><td><Button size="sm" variant="outline-dark" onClick={() => editProcedure(procedure)}>Edit</Button></td></tr>)}</tbody>
          </Table>
        </Card.Body>
      </Card>

      <Card className="app-card">
        <Card.Body>
          <h5 className="section-title">3. Pipeline templates</h5>
          <Form onSubmit={savePipeline}>
            <Row className="g-3">
              <Col md={3}><Form.Label>Code</Form.Label><Form.Control required value={pipelineForm.code} onChange={(event) => setPipelineForm({ ...pipelineForm, code: event.target.value })} placeholder="DNA-WORKFLOW" /></Col>
              <Col md={5}><Form.Label>Name</Form.Label><Form.Control required value={pipelineForm.name} onChange={(event) => setPipelineForm({ ...pipelineForm, name: event.target.value })} /></Col>
              <Col md={4}><Form.Label>Description</Form.Label><Form.Control value={pipelineForm.description} onChange={(event) => setPipelineForm({ ...pipelineForm, description: event.target.value })} /></Col>
              <Col md={3}><Form.Check type="switch" label="Use as a default" checked={pipelineForm.is_default} onChange={(event) => setPipelineForm({ ...pipelineForm, is_default: event.target.checked })} /></Col>
              <Col md={4}><Form.Label>Default project</Form.Label><Form.Select disabled={!pipelineForm.is_default} value={pipelineForm.default_project} onChange={(event) => setPipelineForm({ ...pipelineForm, default_project: event.target.value })}><option value="">All projects</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.code} — {project.name}</option>)}</Form.Select></Col>
              <Col md={4}><Form.Label>Default sample type</Form.Label><Form.Control disabled={!pipelineForm.is_default} value={pipelineForm.default_sample_type} onChange={(event) => setPipelineForm({ ...pipelineForm, default_sample_type: event.target.value })} placeholder="DNA (blank means all)" /></Col>
            </Row>
            <div className="toolbar-row mt-4 mb-2"><div><strong>Ordered steps</strong><div className="feed-meta">Only the current step receives a work item; later steps remain blocked.</div></div><Button type="button" size="sm" variant="outline-dark" onClick={() => setPipelineForm({ ...pipelineForm, steps: [...pipelineForm.steps, emptyPipelineStep()] })}>Add step</Button></div>
            {pipelineForm.steps.map((step, index) => (
              <Row className="g-2 mb-2 align-items-center" key={index}>
                <Col md={1}><Badge bg="dark">Step {index + 1}</Badge></Col>
                <Col md={4}><Form.Select required value={step.procedure} onChange={(event) => updatePipelineStep(index, "procedure", event.target.value)}><option value="">Select procedure</option>{activeProcedures.map((procedure) => <option key={procedure.id} value={procedure.id}>{procedure.code} v{procedure.version} — {procedure.name}</option>)}</Form.Select></Col>
                <Col md={3}><Form.Control value={step.name} onChange={(event) => updatePipelineStep(index, "name", event.target.value)} placeholder="Optional step name" /></Col>
                <Col md={2}><Form.Check label="QC approval required" checked={step.requires_qc} onChange={(event) => updatePipelineStep(index, "requires_qc", event.target.checked)} /></Col>
                <Col md={2} className="inline-actions"><Button type="button" size="sm" variant="outline-secondary" disabled={index === 0} onClick={() => movePipelineStep(index, -1)}>↑</Button><Button type="button" size="sm" variant="outline-secondary" disabled={index === pipelineForm.steps.length - 1} onClick={() => movePipelineStep(index, 1)}>↓</Button><Button type="button" size="sm" variant="outline-danger" disabled={pipelineForm.steps.length === 1} onClick={() => setPipelineForm({ ...pipelineForm, steps: pipelineForm.steps.filter((_, itemIndex) => itemIndex !== index) })}>×</Button></Col>
              </Row>
            ))}
            <div className="inline-actions mt-3"><Button type="submit" variant="dark" disabled={saving || !pipelineForm.code || !pipelineForm.name || pipelineForm.steps.some((step) => !step.procedure)}>{pipelineEditingId ? "Update pipeline" : "Create pipeline"}</Button>{pipelineEditingId && <Button type="button" variant="outline-secondary" onClick={resetPipeline}>Cancel edit</Button>}</div>
          </Form>

          <div className="d-grid gap-3 mt-4">
            {templates.map((template) => (
              <div className="feed-item" key={template.id}>
                <div className="toolbar-row"><div><strong>{template.code} — {template.name}</strong><div className="feed-meta">{template.default_project_code || "All projects"} · {template.default_sample_type || "All sample types"} · {template.steps.length} steps</div></div><div className="inline-actions">{template.is_default && <Badge bg="info">Default</Badge>}<Badge bg={template.active ? "success" : "secondary"}>{template.active ? "Active" : "Inactive"}</Badge><Button size="sm" variant="outline-dark" onClick={() => editPipeline(template)}>Edit</Button></div></div>
                <div className="d-flex flex-wrap gap-2 mt-3">{template.steps.map((step) => <Badge bg="light" text="dark" key={step.id}>{step.position}. {step.display_name} ({step.analysis_code}){step.requires_qc ? " · QC" : ""}</Badge>)}</div>
              </div>
            ))}
          </div>
        </Card.Body>
      </Card>
    </div>
  );
}
