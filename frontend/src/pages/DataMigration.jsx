import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Badge, Button, Card, Col, Form, Row, Table } from "react-bootstrap";
import { apiDelete, apiGet, apiPost, apiPostForm } from "../api";
import { canWrite, isAdmin } from "../authz";

const TARGET_TYPES = [
  ["PROJECT_CODE", "Project Code"], ["PROJECT_NAME", "Project Name"],
  ["PROJECT_DESCRIPTION", "Project Description"], ["USER_USERNAME", "User Username"],
  ["USER_EMAIL", "User Email"], ["USER_FIRST_NAME", "User First Name"],
  ["USER_LAST_NAME", "User Last Name"], ["USER_ROLE", "User Role"],
  ["SAMPLE_ID", "Sample ID"], ["SAMPLE_TYPE", "Sample Type"],
  ["SAMPLE_STATUS", "Sample Status"], ["SAMPLE_CREATED_AT", "Sample Created At"],
  ["EXTERNAL_ID", "External ID / Alias"], ["CUSTOM_FIELD", "Sample Custom Field"],
  ["WORK_ITEM_NAME", "Work Item Name"], ["WORK_ITEM_TYPE", "Work Item Type"],
  ["WORK_ITEM_STATUS", "Work Item Status"], ["WORK_ITEM_CREATED_AT", "Work Item Created At"],
  ["RESULT_KEY", "Result Key"], ["RESULT_VALUE", "Result Value"],
  ["RESULT_UNIT", "Result Unit"], ["RESULT_CREATED_AT", "Result Created At"],
  ["RESULT_QC_STATUS", "Result QC Status"], ["RESULT_ENTERED_BY", "Result Entered By"],
  ["RESULT_REFERENCE_MIN", "Result Reference Minimum"],
  ["RESULT_REFERENCE_MAX", "Result Reference Maximum"],
];
const VALUE_TYPES = ["STRING", "NUMBER", "BOOLEAN"];
const ENTITY_TARGETS = {
  PROJECT: ["PROJECT_CODE", "PROJECT_NAME", "PROJECT_DESCRIPTION"],
  USER: ["USER_USERNAME", "USER_EMAIL", "USER_FIRST_NAME", "USER_LAST_NAME", "USER_ROLE"],
  SAMPLE: ["PROJECT_CODE", "SAMPLE_ID", "SAMPLE_TYPE", "SAMPLE_STATUS", "SAMPLE_CREATED_AT", "EXTERNAL_ID", "CUSTOM_FIELD"],
  RESULT: ["SAMPLE_ID", "WORK_ITEM_NAME", "WORK_ITEM_TYPE", "WORK_ITEM_STATUS", "WORK_ITEM_CREATED_AT", "RESULT_KEY", "RESULT_VALUE", "RESULT_UNIT", "RESULT_CREATED_AT", "RESULT_QC_STATUS", "RESULT_ENTERED_BY", "RESULT_REFERENCE_MIN", "RESULT_REFERENCE_MAX"],
};

async function getAll(path) {
  const separator = path.includes("?") ? "&" : "?";
  let page = 1;
  let values = [];
  while (page <= 50) {
    const data = await apiGet(`${path}${separator}page=${page}`);
    if (!data?.results) return data || [];
    values = [...values, ...data.results];
    if (!data.next) break;
    page += 1;
  }
  return values;
}

function countFor(summary, entity, key) {
  return summary?.entity_counts?.[entity]?.[key] || 0;
}

export default function DataMigration() {
  const [me, setMe] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [projects, setProjects] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [connections, setConnections] = useState([]);
  const [datasets, setDatasets] = useState([]);
  const [inspection, setInspection] = useState(null);
  const [err, setErr] = useState("");
  const [success, setSuccess] = useState("");
  const [busy, setBusy] = useState("");

  const [profileName, setProfileName] = useState("SISBI Migration");
  const [sourceSystem, setSourceSystem] = useState("SISBI");
  const [sourceType, setSourceType] = useState("CSV");
  const [description, setDescription] = useState("");
  const [selectedProfile, setSelectedProfile] = useState("");
  const [connectionForm, setConnectionForm] = useState({
    name: "SISBI read-only", engine: "POSTGRESQL", host: "host.docker.internal",
    port: "5432", database_name: "sisbi", username: "sisbi_readonly",
    password_env_var: "SISBI_MIGRATION_PASSWORD", ssl_mode: "prefer",
  });
  const [selectedConnection, setSelectedConnection] = useState("");
  const [datasetForm, setDatasetForm] = useState({
    name: "Projects", entity_type: "PROJECT", source_schema: "public",
    source_table: "", source_key_column: "id", row_limit: "10000",
  });
  const [selectedDataset, setSelectedDataset] = useState("");
  const [sourceColumn, setSourceColumn] = useState("");
  const [targetType, setTargetType] = useState("SAMPLE_ID");
  const [targetField, setTargetField] = useState("");
  const [valueType, setValueType] = useState("STRING");
  const [required, setRequired] = useState(false);
  const [migrationProject, setMigrationProject] = useState("");
  const [uploadFile, setUploadFile] = useState(null);
  const [previewJob, setPreviewJob] = useState(null);

  async function load() {
    setErr("");
    try {
      const meData = await apiGet("/api/me/");
      const [profileList, projectList, jobList] = await Promise.all([
        getAll("/api/migration-profiles/"), getAll("/api/projects/"),
        getAll("/api/migration-jobs/"),
      ]);
      let connectionList = [];
      let datasetList = [];
      if (isAdmin(meData)) {
        [connectionList, datasetList] = await Promise.all([
          getAll("/api/migration-database-connections/"),
          getAll("/api/migration-datasets/"),
        ]);
      }
      setMe(meData); setProfiles(profileList); setProjects(projectList); setJobs(jobList);
      setConnections(connectionList); setDatasets(datasetList);
      if (!selectedProfile && profileList[0]) setSelectedProfile(String(profileList[0].id));
      if (!selectedConnection && connectionList[0]) setSelectedConnection(String(connectionList[0].id));
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => load(), 0);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const director = isAdmin(me);
  const userCanWrite = canWrite(me);
  const activeProfile = profiles.find((item) => String(item.id) === String(selectedProfile));
  const databaseProfile = activeProfile?.source_type === "DATABASE";
  const profileDatasets = datasets.filter((item) => String(item.profile) === String(selectedProfile));
  const activeDataset = profileDatasets.find((item) => String(item.id) === String(selectedDataset));
  const selectedTable = inspection?.tables?.find((item) =>
    item.name === activeDataset?.source_table &&
    (item.schema || "") === (activeDataset?.source_schema || "")
  );
  const inspectedDatasetColumns = selectedTable?.columns || [];
  const selectedConnectionTables = inspection?.tables || [];
  const previewRows = previewJob?.summary?.preview_rows || [];
  const targetOptions = databaseProfile && activeDataset
    ? TARGET_TYPES.filter(([value]) => ENTITY_TARGETS[activeDataset.entity_type]?.includes(value))
    : TARGET_TYPES;
  const selectedTargetType = targetOptions.some(([value]) => value === targetType)
    ? targetType
    : targetOptions[0]?.[0] || "SAMPLE_ID";
  const mappings = useMemo(() => (activeProfile?.field_mappings || []).filter(
    (item) => !databaseProfile || String(item.dataset) === String(selectedDataset)
  ), [activeProfile, databaseProfile, selectedDataset]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      if (databaseProfile && !profileDatasets.some((item) => String(item.id) === selectedDataset)) {
        setSelectedDataset(profileDatasets[0] ? String(profileDatasets[0].id) : "");
      }
      setPreviewJob(null);
    }, 0);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProfile, datasets.length]);

  function showError(e) { setErr(e.message || String(e)); setSuccess(""); }

  async function createProfile(e) {
    e.preventDefault(); setBusy("profile");
    try {
      const profile = await apiPost("/api/migration-profiles/", {
        name: profileName, source_system: sourceSystem, source_type: sourceType, description,
      });
      setSelectedProfile(String(profile.id)); setSuccess("Migration profile created."); await load();
    } catch (e) { showError(e); } finally { setBusy(""); }
  }

  async function createConnection(e) {
    e.preventDefault(); setBusy("connection");
    try {
      const sqlite = connectionForm.engine === "SQLITE";
      const created = await apiPost("/api/migration-database-connections/", {
        ...connectionForm, port: sqlite || !connectionForm.port ? null : Number(connectionForm.port),
        host: sqlite ? "" : connectionForm.host, username: sqlite ? "" : connectionForm.username,
        password_env_var: sqlite ? "" : connectionForm.password_env_var,
      });
      setSelectedConnection(String(created.id)); setSuccess("Read-only database connection saved."); await load();
    } catch (e) { showError(e); } finally { setBusy(""); }
  }

  async function inspectConnection() {
    setBusy("inspect");
    try {
      const data = await apiGet(`/api/migration-database-connections/${selectedConnection}/inspect/`);
      setInspection(data); setSuccess(`Connection verified. Found ${data.tables?.length || 0} table(s).`);
    } catch (e) { showError(e); } finally { setBusy(""); }
  }

  function chooseTable(value) {
    const table = selectedConnectionTables.find((item) => `${item.schema || ""}.${item.name}` === value);
    if (!table) return;
    setDatasetForm((current) => ({ ...current, source_schema: table.schema || "",
      source_table: table.name, source_key_column: table.columns?.[0]?.name || "id" }));
  }

  async function createDataset(e) {
    e.preventDefault(); setBusy("dataset");
    try {
      const created = await apiPost("/api/migration-datasets/", {
        ...datasetForm, profile: Number(selectedProfile), connection: Number(selectedConnection),
        row_limit: Number(datasetForm.row_limit),
      });
      setSelectedDataset(String(created.id)); setSuccess("Source dataset added."); await load();
    } catch (e) { showError(e); } finally { setBusy(""); }
  }

  async function createMapping(e) {
    e.preventDefault(); setBusy("mapping");
    try {
      await apiPost("/api/migration-field-mappings/", {
        profile: Number(selectedProfile), dataset: databaseProfile ? Number(selectedDataset) : null,
        source_column: sourceColumn, target_type: selectedTargetType, target_field: targetField,
        value_type: valueType, required,
      });
      setSourceColumn(""); setTargetField(""); setRequired(false);
      setSuccess("Field mapping added."); await load();
    } catch (e) { showError(e); } finally { setBusy(""); }
  }

  async function deleteMapping(id) {
    try { await apiDelete(`/api/migration-field-mappings/${id}/`); setSuccess("Mapping deleted."); await load(); }
    catch (e) { showError(e); }
  }

  function csvForm() {
    const form = new FormData(); form.append("profile", selectedProfile);
    if (migrationProject) form.append("project", migrationProject);
    if (uploadFile) form.append("uploaded_file", uploadFile);
    return form;
  }

  async function suggestMappings() {
    setBusy("suggest");
    try {
      const data = await apiPostForm("/api/migration-jobs/suggest-mappings/", csvForm());
      setSuccess(`Suggested ${data.created_count || 0} new mapping(s).`); await load();
    } catch (e) { showError(e); } finally { setBusy(""); }
  }

  async function previewMigration() {
    setBusy("preview"); setPreviewJob(null);
    try {
      const data = databaseProfile
        ? await apiPost("/api/migration-jobs/preview/", { profile: Number(selectedProfile) })
        : await apiPostForm("/api/migration-jobs/preview/", csvForm());
      setPreviewJob(data); setSuccess("Migration preview completed. Review validation before committing."); await load();
    } catch (e) { showError(e); } finally { setBusy(""); }
  }

  async function commitMigration() {
    setBusy("commit");
    try {
      const data = await apiPost(`/api/migration-jobs/${previewJob.id}/commit/`, {});
      setPreviewJob(data); setSuccess(`Migration job #${data.id} was queued from the reviewed preview.`); await load();
    } catch (e) { showError(e); } finally { setBusy(""); }
  }

  return <div className="w-100">
    <div className="page-header"><div><h1 className="page-title">Data Migration</h1>
      <p className="page-subtitle">Import projects, users, samples, metadata, and historical results from CSV or a legacy database.</p>
    </div><Badge bg="dark">validated migration</Badge></div>
    {err && <Alert variant="danger">{err}</Alert>}
    {success && <Alert variant="success">{success}</Alert>}
    <Alert variant="info">Database sources use read-only accounts. Preview fingerprints bind the reviewed rows and mappings to the final commit.</Alert>

    <Row className="g-4 mb-4">
      <Col lg={5}><Card className="app-card h-100"><Card.Body><h5 className="section-title">Create Migration Profile</h5>
        <Form onSubmit={createProfile}><Row className="g-2">
          <Col md={12}><Form.Control value={profileName} placeholder="Profile name" onChange={(e) => setProfileName(e.target.value)} disabled={!userCanWrite} /></Col>
          <Col md={7}><Form.Control value={sourceSystem} placeholder="Source system" onChange={(e) => setSourceSystem(e.target.value)} disabled={!userCanWrite} /></Col>
          <Col md={5}><Form.Select value={sourceType} onChange={(e) => setSourceType(e.target.value)} disabled={!userCanWrite}><option value="CSV">CSV</option>{director && <option value="DATABASE">Database</option>}</Form.Select></Col>
          <Col md={12}><Form.Control as="textarea" rows={2} value={description} placeholder="Description" onChange={(e) => setDescription(e.target.value)} disabled={!userCanWrite} /></Col>
          <Col md={12}><Button type="submit" variant="dark" className="w-100" disabled={!userCanWrite || busy === "profile"}>Create Profile</Button></Col>
        </Row></Form>
      </Card.Body></Card></Col>
      <Col lg={7}><Card className="app-card h-100"><Card.Body><h5 className="section-title">Select Migration Profile</h5>
        <Form.Select value={selectedProfile} onChange={(e) => setSelectedProfile(e.target.value)}><option value="">Select profile</option>{profiles.map((profile) => <option key={profile.id} value={profile.id}>{profile.name} — {profile.source_system} ({profile.source_type})</option>)}</Form.Select>
        {activeProfile && <div className="soft-card mt-3"><div className="feed-meta">Migration path</div><div className="fw-semibold">{activeProfile.source_type}</div><div>{activeProfile.description || "No description"}</div></div>}
      </Card.Body></Card></Col>
    </Row>

    {director && databaseProfile && <Row className="g-4 mb-4">
      <Col lg={6}><Card className="app-card h-100"><Card.Body><h5 className="section-title">Read-only Database Connection</h5>
        <Form onSubmit={createConnection}><Row className="g-2">
          <Col md={7}><Form.Control value={connectionForm.name} placeholder="Connection name" onChange={(e) => setConnectionForm({ ...connectionForm, name: e.target.value })} /></Col>
          <Col md={5}><Form.Select value={connectionForm.engine} onChange={(e) => setConnectionForm({ ...connectionForm, engine: e.target.value })}><option value="POSTGRESQL">PostgreSQL</option><option value="MYSQL">MySQL / MariaDB</option><option value="SQLITE">SQLite</option></Form.Select></Col>
          {connectionForm.engine !== "SQLITE" && <><Col md={8}><Form.Control value={connectionForm.host} placeholder="Allowed host" onChange={(e) => setConnectionForm({ ...connectionForm, host: e.target.value })} /></Col><Col md={4}><Form.Control value={connectionForm.port} placeholder="Port" onChange={(e) => setConnectionForm({ ...connectionForm, port: e.target.value })} /></Col></>}
          <Col md={12}><Form.Control value={connectionForm.database_name} placeholder={connectionForm.engine === "SQLITE" ? "File below MIGRATION_SQLITE_ROOT" : "Database name"} onChange={(e) => setConnectionForm({ ...connectionForm, database_name: e.target.value })} /></Col>
          {connectionForm.engine !== "SQLITE" && <><Col md={6}><Form.Control value={connectionForm.username} placeholder="Read-only username" onChange={(e) => setConnectionForm({ ...connectionForm, username: e.target.value })} /></Col><Col md={6}><Form.Control value={connectionForm.password_env_var} placeholder="Password environment variable" onChange={(e) => setConnectionForm({ ...connectionForm, password_env_var: e.target.value })} /></Col></>}
          <Col md={6}><Button type="submit" variant="dark" className="w-100" disabled={busy === "connection"}>Save Connection</Button></Col>
          <Col md={6}><Form.Select value={selectedConnection} onChange={(e) => { setSelectedConnection(e.target.value); setInspection(null); }}><option value="">Select saved connection</option>{connections.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</Form.Select></Col>
          <Col md={12}><Button variant="outline-dark" className="w-100" onClick={inspectConnection} disabled={!selectedConnection || busy === "inspect"}>{busy === "inspect" ? "Inspecting..." : "Test and Inspect Tables"}</Button></Col>
        </Row></Form>
      </Card.Body></Card></Col>
      <Col lg={6}><Card className="app-card h-100"><Card.Body><h5 className="section-title">Source Dataset</h5>
        <Form onSubmit={createDataset}><Row className="g-2">
          <Col md={7}><Form.Control value={datasetForm.name} placeholder="Dataset name" onChange={(e) => setDatasetForm({ ...datasetForm, name: e.target.value })} /></Col>
          <Col md={5}><Form.Select value={datasetForm.entity_type} onChange={(e) => setDatasetForm({ ...datasetForm, entity_type: e.target.value })}><option value="USER">Users</option><option value="PROJECT">Projects</option><option value="SAMPLE">Samples</option><option value="RESULT">Historical Results</option></Form.Select></Col>
          <Col md={12}><Form.Select onChange={(e) => chooseTable(e.target.value)} disabled={!inspection}><option value="">Select inspected table</option>{selectedConnectionTables.map((item) => <option key={`${item.schema}.${item.name}`} value={`${item.schema || ""}.${item.name}`}>{item.schema ? `${item.schema}.` : ""}{item.name}</option>)}</Form.Select></Col>
          <Col md={6}><Form.Control value={datasetForm.source_table} placeholder="Source table" onChange={(e) => setDatasetForm({ ...datasetForm, source_table: e.target.value })} /></Col>
          <Col md={6}><Form.Select value={datasetForm.source_key_column} onChange={(e) => setDatasetForm({ ...datasetForm, source_key_column: e.target.value })}><option value={datasetForm.source_key_column}>{datasetForm.source_key_column || "Source key"}</option>{selectedConnectionTables.find((item) => item.name === datasetForm.source_table)?.columns?.map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}</Form.Select></Col>
          <Col md={6}><Form.Control value={datasetForm.row_limit} type="number" min="1" max="50000" onChange={(e) => setDatasetForm({ ...datasetForm, row_limit: e.target.value })} /></Col>
          <Col md={6}><Button type="submit" variant="dark" className="w-100" disabled={!selectedConnection || !datasetForm.source_table || busy === "dataset"}>Add Dataset</Button></Col>
        </Row></Form>
        <div className="mt-3">{profileDatasets.map((item) => <Badge key={item.id} bg="light" text="dark" className="me-2 mb-2">{item.entity_type}: {item.source_schema ? `${item.source_schema}.` : ""}{item.source_table}</Badge>)}</div>
      </Card.Body></Card></Col>
    </Row>}

    <Card className="app-card mb-4"><Card.Body><h5 className="section-title">Field Mapping</h5>
      <Form onSubmit={createMapping}><Row className="g-2">
        {databaseProfile && <Col md={3}><Form.Select value={selectedDataset} onChange={(e) => setSelectedDataset(e.target.value)} disabled={!director}><option value="">Select dataset</option>{profileDatasets.map((item) => <option key={item.id} value={item.id}>{item.entity_type}: {item.name}</option>)}</Form.Select></Col>}
        <Col md={databaseProfile ? 2 : 3}><Form.Control list="migration-source-columns" value={sourceColumn} placeholder={databaseProfile ? "Source column" : "CSV column"} onChange={(e) => setSourceColumn(e.target.value)} disabled={!userCanWrite || (databaseProfile && !director)} /><datalist id="migration-source-columns">{inspectedDatasetColumns.map((column) => <option key={column.name} value={column.name} />)}</datalist></Col>
        <Col md={3}><Form.Select value={selectedTargetType} onChange={(e) => setTargetType(e.target.value)} disabled={!userCanWrite || (databaseProfile && !director)}>{targetOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</Form.Select></Col>
        <Col md={2}><Form.Control value={targetField} placeholder="Target key (optional)" onChange={(e) => setTargetField(e.target.value)} disabled={!userCanWrite || (databaseProfile && !director)} /></Col>
        <Col md={2}><Form.Select value={valueType} onChange={(e) => setValueType(e.target.value)} disabled={!userCanWrite || (databaseProfile && !director)}>{VALUE_TYPES.map((item) => <option key={item}>{item}</option>)}</Form.Select></Col>
        <Col md={2}><Form.Check className="mt-2" type="checkbox" label="Required" checked={required} onChange={(e) => setRequired(e.target.checked)} /></Col>
        <Col md={2}><Button type="submit" variant="dark" className="w-100" disabled={!selectedProfile || !sourceColumn || (databaseProfile && !selectedDataset) || busy === "mapping"}>Add Mapping</Button></Col>
      </Row></Form>
      {mappings.length === 0 ? <div className="empty-state mt-3">No mappings yet.</div> : <Table responsive hover className="app-table mt-3"><thead><tr><th>Source</th><th>Target</th><th>Field</th><th>Type</th><th>Required</th><th>Actions</th></tr></thead><tbody>{mappings.map((mapping) => <tr key={mapping.id}><td>{mapping.source_column}</td><td>{mapping.target_type}</td><td>{mapping.target_field || "-"}</td><td>{mapping.value_type}</td><td>{mapping.required ? "Yes" : "No"}</td><td><Button size="sm" variant="outline-danger" onClick={() => deleteMapping(mapping.id)}>Delete</Button></td></tr>)}</tbody></Table>}
    </Card.Body></Card>

    <Card className="app-card mb-4"><Card.Body><h5 className="section-title">Preview, Validate, and Commit</h5>
      {!databaseProfile && <Row className="g-2 mb-3"><Col md={5}><Form.Select value={migrationProject} onChange={(e) => setMigrationProject(e.target.value)}><option value="">Use project from CSV mapping</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.code} — {project.name}</option>)}</Form.Select></Col><Col md={5}><Form.Control type="file" accept=".csv,text/csv" onChange={(e) => setUploadFile(e.target.files?.[0] || null)} /></Col><Col md={2}><Button variant="outline-secondary" className="w-100" onClick={suggestMappings} disabled={!uploadFile || busy === "suggest"}>Suggest</Button></Col></Row>}
      <Row className="g-2"><Col md={6}><Button variant="outline-dark" className="w-100" onClick={previewMigration} disabled={!selectedProfile || (!databaseProfile && !uploadFile) || (databaseProfile && !director) || busy === "preview"}>{busy === "preview" ? "Validating..." : "Preview and Validate"}</Button></Col><Col md={6}><Button variant="dark" className="w-100" onClick={commitMigration} disabled={!previewJob?.summary?.ready_to_commit || previewJob?.status !== "PREVIEWED" || busy === "commit"}>{busy === "commit" ? "Queuing..." : "Commit Reviewed Preview"}</Button></Col></Row>
      {previewJob && <div className="mt-4"><Row className="g-3 mb-3">
        <Col md={3}><div className="soft-card"><div className="feed-meta">Rows</div><div className="fw-semibold">{previewJob.summary?.rows_processed || 0}</div></div></Col>
        <Col md={3}><div className="soft-card"><div className="feed-meta">Projects / Users</div><div className="fw-semibold">{countFor(previewJob.summary, "PROJECT", "to_create") + countFor(previewJob.summary, "USER", "to_create") || previewJob.summary?.projects_to_create?.length || 0}</div></div></Col>
        <Col md={3}><div className="soft-card"><div className="feed-meta">Samples / Results</div><div className="fw-semibold">{countFor(previewJob.summary, "SAMPLE", "to_create") + countFor(previewJob.summary, "RESULT", "rows") || (previewJob.summary?.samples_to_create?.length || 0) + (previewJob.summary?.results_to_create || 0)}</div></div></Col>
        <Col md={3}><div className="soft-card"><div className="feed-meta">Validation Errors</div><div className="fw-semibold">{previewJob.summary?.validation_error_count || 0}</div></div></Col>
      </Row><Alert variant={previewJob.summary?.ready_to_commit ? "success" : "danger"}>{previewJob.summary?.ready_to_commit ? "Preview is valid and ready to commit." : "Commit is blocked until all validation errors are resolved."}</Alert>
      {previewJob.summary?.validation_errors?.length > 0 && <Alert variant="danger">{previewJob.summary.validation_errors.slice(0, 10).map((item, index) => <div key={index}>{item.dataset ? `${item.dataset}: ` : ""}{item.row ? `row ${item.row}: ` : ""}{item.message}</div>)}</Alert>}
      {previewJob.summary?.validation_warnings?.length > 0 && <Alert variant="warning">{previewJob.summary.validation_warnings.slice(0, 10).map((item, index) => <div key={index}>{item.dataset}: row {item.row}: {item.message}</div>)}</Alert>}
      {previewRows.length > 0 && <Table responsive hover className="app-table"><thead><tr><th>Dataset</th><th>Row</th><th>Entity</th><th>Identifier</th><th>Action</th><th>Status</th></tr></thead><tbody>{previewRows.map((row, index) => <tr key={`${row.dataset_id || "csv"}-${row.row}-${index}`}><td>{row.dataset || "CSV"}</td><td>{row.row}</td><td>{row.entity_type || "SAMPLE"}</td><td>{row.identifier || row.sample_id || "-"}</td><td>{row.action || "CREATE"}</td><td>{row.will_skip ? <span className="text-danger">{row.errors?.join(", ")}</span> : row.warnings?.length ? <span className="text-warning">{row.warnings.join(", ")}</span> : "Ready"}</td></tr>)}</tbody></Table>}</div>}
    </Card.Body></Card>

    <Card className="app-card"><Card.Body><h5 className="section-title">Migration History</h5>
      {jobs.length === 0 ? <div className="empty-state">No migration jobs yet.</div> : <Table responsive hover className="app-table"><thead><tr><th>ID</th><th>Profile</th><th>Source</th><th>Status</th><th>Rows</th><th>Created</th></tr></thead><tbody>{jobs.map((job) => <tr key={job.id}><td><Link to={`/data-migration/jobs/${job.id}`}>#{job.id}</Link></td><td>{job.profile_name}</td><td>{job.source_connection_name || job.project_code || "CSV mapping"}</td><td><Badge bg={job.status === "COMPLETED" ? "success" : job.status === "FAILED" ? "danger" : job.status === "PREVIEWED" ? "info" : "secondary"}>{job.status}</Badge></td><td>{job.summary?.rows_processed || job.summary?.progress?.processed_rows || 0}</td><td>{new Date(job.created_at).toLocaleString()}</td></tr>)}</tbody></Table>}
    </Card.Body></Card>
  </div>;
}
