import { useEffect, useMemo, useState } from "react";
import { Alert, Badge, Button, Card, Col, Form, Row, Table } from "react-bootstrap";
import { apiGet, apiPost, apiPostForm } from "../api";

function statusVariant(status) {
  switch (status) {
    case "COMPLETED": return "success";
    case "FAILED": return "danger";
    case "PENDING": return "warning";
    default: return "secondary";
  }
}
function formatTimestamp(ts) { try { return new Date(ts).toLocaleString(); } catch { return ts; } }

export default function Imports() {
  const [me, setMe] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [projects, setProjects] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [err, setErr] = useState("");
  const [profileName, setProfileName] = useState("");
  const [profileCode, setProfileCode] = useState("");
  const [delimiter, setDelimiter] = useState(",");
  const [hasHeader, setHasHeader] = useState(true);
  const [sampleIdColumn, setSampleIdColumn] = useState("sample_id");
  const [mappingInstrument, setMappingInstrument] = useState("");
  const [mappingSourceColumn, setMappingSourceColumn] = useState("");
  const [mappingTargetKey, setMappingTargetKey] = useState("");
  const [mappingValueType, setMappingValueType] = useState("NUMBER");
  const [mappingMinValue, setMappingMinValue] = useState("");
  const [mappingMaxValue, setMappingMaxValue] = useState("");
  const [mappingAllowedValues, setMappingAllowedValues] = useState("");
  const [uploadInstrument, setUploadInstrument] = useState("");
  const [uploadProject, setUploadProject] = useState("");
  const [uploadFile, setUploadFile] = useState(null);
  const [previewData, setPreviewData] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  async function load() {
    setErr("");
    try {
      const [meData, profilesData, jobsData, projectsData] = await Promise.all([
        apiGet("/api/me/"), apiGet("/api/instrument-profiles/"), apiGet("/api/import-jobs/"), apiGet("/api/projects/")
      ]);
      const profileList = profilesData.results || profilesData || [];
      setMe(meData);
      setProfiles(profileList);
      setJobs(jobsData.results || jobsData || []);
      setProjects(projectsData.results || projectsData || []);
      if (!uploadInstrument && profileList.length > 0) setUploadInstrument(String(profileList[0].id));
      if (!mappingInstrument && profileList.length > 0) setMappingInstrument(String(profileList[0].id));
    } catch (e) { setErr(e.message || String(e)); }
  }
  useEffect(() => { load(); }, []);
  const isAdmin = me?.roles?.includes("admin");
  const selectedProfile = useMemo(() => profiles.find((p) => String(p.id) === String(mappingInstrument)), [profiles, mappingInstrument]);

  async function createProfile(e) {
    e.preventDefault();
    setErr("");
    try {
      await apiPost("/api/instrument-profiles/", { name: profileName, code: profileCode, delimiter, has_header: hasHeader, sample_id_column: sampleIdColumn });
      setProfileName(""); setProfileCode(""); setDelimiter(","); setHasHeader(true); setSampleIdColumn("sample_id");
      await load();
    } catch (e) { setErr(e.message || String(e)); }
  }

  async function createMapping(e) {
    e.preventDefault();
    setErr("");
    try {
      await apiPost("/api/instrument-mappings/", {
        instrument: Number(mappingInstrument),
        source_column: mappingSourceColumn,
        target_key: mappingTargetKey,
        value_type: mappingValueType,
        min_value: mappingMinValue === "" ? null : Number(mappingMinValue),
        max_value: mappingMaxValue === "" ? null : Number(mappingMaxValue),
        allowed_values: mappingAllowedValues.trim() === "" ? null : mappingAllowedValues.split(",").map((v) => v.trim()),
      });
      setMappingSourceColumn(""); setMappingTargetKey(""); setMappingValueType("NUMBER"); setMappingMinValue(""); setMappingMaxValue(""); setMappingAllowedValues("");
      await load();
    } catch (e) { setErr(e.message || String(e)); }
  }

  async function previewImport() {
    setErr(""); setPreviewData(null); setPreviewLoading(true);
    try {
      const formData = new FormData();
      formData.append("instrument", uploadInstrument);
      formData.append("uploaded_file", uploadFile);
      const data = await apiPostForm("/api/import-jobs/preview/", formData);
      setPreviewData(data);
    } catch (e) { setErr(e.message || String(e)); }
    finally { setPreviewLoading(false); }
  }

  async function uploadImportJob(e) {
    e.preventDefault();
    setErr("");
    try {
      const formData = new FormData();
      formData.append("instrument", uploadInstrument);
      if (uploadProject) formData.append("project", uploadProject);
      formData.append("uploaded_file", uploadFile);
      await apiPostForm("/api/import-jobs/", formData);
      setUploadFile(null); setPreviewData(null);
      await load();
    } catch (e) { setErr(e.message || String(e)); }
  }

  return (
    <div className="w-100">
      <div className="page-header"><div><h1 className="page-title">Imports</h1><p className="page-subtitle">Manage instrument profiles, mappings, and ingestion runs.</p></div></div>
      {err && <Alert variant="danger">{err}</Alert>}

      {isAdmin && (
        <div className="row g-4 mb-4">
          <div className="col-lg-5">
            <Card className="app-card h-100"><Card.Body>
              <h5 className="section-title">Create Instrument Profile</h5>
              <Form onSubmit={createProfile}>
                <Row className="g-2">
                  <Col md={6}><Form.Control placeholder="Name" value={profileName} onChange={(e) => setProfileName(e.target.value)} /></Col>
                  <Col md={3}><Form.Control placeholder="Code" value={profileCode} onChange={(e) => setProfileCode(e.target.value)} /></Col>
                  <Col md={3}><Form.Control placeholder="Delimiter" value={delimiter} onChange={(e) => setDelimiter(e.target.value)} /></Col>
                  <Col md={8}><Form.Control placeholder="Sample ID column" value={sampleIdColumn} onChange={(e) => setSampleIdColumn(e.target.value)} /></Col>
                  <Col md={4}><Button type="submit" variant="dark" className="w-100" disabled={!profileName || !profileCode || !sampleIdColumn}>Create</Button></Col>
                </Row>
                <Form.Check className="mt-3" type="checkbox" label="CSV has header row" checked={hasHeader} onChange={(e) => setHasHeader(e.target.checked)} />
              </Form>
            </Card.Body></Card>
          </div>

          <div className="col-lg-7">
            <Card className="app-card h-100"><Card.Body>
              <h5 className="section-title">Create Column Mapping</h5>
              <Form onSubmit={createMapping}>
                <Row className="g-2">
                  <Col md={3}><Form.Select value={mappingInstrument} onChange={(e) => setMappingInstrument(e.target.value)}>{profiles.map((p) => <option key={p.id} value={p.id}>{p.code} - {p.name}</option>)}</Form.Select></Col>
                  <Col md={3}><Form.Control placeholder="Source column" value={mappingSourceColumn} onChange={(e) => setMappingSourceColumn(e.target.value)} /></Col>
                  <Col md={3}><Form.Control placeholder="Target key" value={mappingTargetKey} onChange={(e) => setMappingTargetKey(e.target.value)} /></Col>
                  <Col md={3}><Form.Select value={mappingValueType} onChange={(e) => setMappingValueType(e.target.value)}><option value="NUMBER">NUMBER</option><option value="STRING">STRING</option><option value="BOOLEAN">BOOLEAN</option></Form.Select></Col>
                  <Col md={2}><Form.Control placeholder="Min" value={mappingMinValue} onChange={(e) => setMappingMinValue(e.target.value)} /></Col>
                  <Col md={2}><Form.Control placeholder="Max" value={mappingMaxValue} onChange={(e) => setMappingMaxValue(e.target.value)} /></Col>
                  <Col md={6}><Form.Control placeholder="Allowed values (comma-separated)" value={mappingAllowedValues} onChange={(e) => setMappingAllowedValues(e.target.value)} /></Col>
                  <Col md={2}><Button type="submit" variant="dark" className="w-100" disabled={!mappingInstrument || !mappingSourceColumn || !mappingTargetKey}>Add</Button></Col>
                </Row>
              </Form>

              {selectedProfile && (
                <div className="mt-4">
                  <div className="feed-meta mb-2">Current mappings for {selectedProfile.code}</div>
                  {selectedProfile.column_mappings?.length === 0 ? (
                    <div className="empty-state">No mappings yet.</div>
                  ) : (
                    <Table responsive hover className="app-table">
                      <thead><tr><th>Source</th><th>Target</th><th>Type</th><th>Min</th><th>Max</th><th>Allowed</th></tr></thead>
                      <tbody>
                        {selectedProfile.column_mappings.map((m) => (
                          <tr key={m.id}>
                            <td>{m.source_column}</td><td>{m.target_key}</td><td>{m.value_type}</td><td>{m.min_value ?? "-"}</td><td>{m.max_value ?? "-"}</td><td>{m.allowed_values?.join(", ") || "-"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  )}
                </div>
              )}
            </Card.Body></Card>
          </div>
        </div>
      )}

      <Card className="app-card mb-4"><Card.Body>
        <h5 className="section-title">Run Import</h5>
        <Form onSubmit={uploadImportJob}>
          <Row className="g-2 align-items-center mb-3">
            <Col md={4}><Form.Select value={uploadInstrument} onChange={(e) => setUploadInstrument(e.target.value)}><option value="">Select instrument</option>{profiles.map((p) => <option key={p.id} value={p.id}>{p.code} - {p.name}</option>)}</Form.Select></Col>
            <Col md={4}><Form.Select value={uploadProject} onChange={(e) => setUploadProject(e.target.value)}><option value="">No project</option>{projects.map((p) => <option key={p.id} value={p.id}>{p.code} - {p.name}</option>)}</Form.Select></Col>
            <Col md={4}><Form.Control type="file" accept=".csv,text/csv" onChange={(e) => setUploadFile(e.target.files?.[0] || null)} /></Col>
          </Row>
          <Row className="g-2">
            <Col md={6}><Button type="button" variant="outline-dark" className="w-100" onClick={previewImport} disabled={!uploadInstrument || !uploadFile || previewLoading}>{previewLoading ? "Previewing..." : "Preview Import"}</Button></Col>
            <Col md={6}><Button type="submit" variant="dark" className="w-100" disabled={!uploadInstrument || !uploadFile}>Run Import</Button></Col>
          </Row>
        </Form>

        {previewData && (
          <Card className="app-card mt-4"><Card.Body>
            <h5 className="section-title">Preview</h5>
            <div className="row g-3 mb-3">
              <div className="col-md-3"><div className="soft-card"><div className="feed-meta">Instrument</div><div className="fw-semibold">{previewData.instrument_code}</div></div></div>
              <div className="col-md-3"><div className="soft-card"><div className="feed-meta">Rows</div><div className="fw-semibold">{previewData.rows_processed}</div></div></div>
              <div className="col-md-3"><div className="soft-card"><div className="feed-meta">Existing Samples</div><div className="fw-semibold">{previewData.existing_samples}</div></div></div>
              <div className="col-md-3"><div className="soft-card"><div className="feed-meta">New Samples</div><div className="fw-semibold">{previewData.new_samples}</div></div></div>
            </div>
          </Card.Body></Card>
        )}
      </Card.Body></Card>

      <Card className="app-card"><Card.Body>
        <h5 className="section-title">Import History</h5>
        {jobs.length === 0 ? (
          <div className="empty-state">No import jobs yet.</div>
        ) : (
          <Table responsive hover className="app-table">
            <thead><tr><th>ID</th><th>Instrument</th><th>Source</th><th>Status</th><th>Uploaded By</th><th>Created</th><th>Summary</th></tr></thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id}>
                  <td>{job.id}</td>
                  <td>{profiles.find((p) => p.id === job.instrument)?.code || job.instrument}</td>
                  <td><Badge bg={job.source_type === "API" ? "dark" : "secondary"}>{job.source_type || "UPLOAD"}</Badge></td>
                  <td><Badge bg={statusVariant(job.status)}>{job.status}</Badge></td>
                  <td>{job.uploaded_by_username || "-"}</td>
                  <td>{formatTimestamp(job.created_at)}</td>
                  <td style={{ minWidth: "320px" }}>
                    {job.summary?.error ? <span className="text-danger">{job.summary.error}</span> : (
                      <div className="small">
                        <div>Rows: {job.summary?.rows_processed ?? 0}</div>
                        <div>Samples created: {job.summary?.samples_created ?? 0}</div>
                        <div>Results created: {job.summary?.results_created ?? 0}</div>
                        <div>Skipped rows: {job.summary?.skipped_rows?.length ?? 0}</div>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card.Body></Card>
    </div>
  );
}
