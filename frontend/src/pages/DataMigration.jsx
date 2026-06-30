import { useEffect, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  Row,
  Table,
} from "react-bootstrap";
import { apiGet, apiPost, apiPostForm } from "../api";
import { canWrite } from "../authz";

const TARGET_TYPES = [
  ["PROJECT_CODE", "Project Code"],
  ["PROJECT_NAME", "Project Name"],
  ["SAMPLE_ID", "Sample ID"],
  ["EXTERNAL_ID", "External ID / Alias"],
  ["CUSTOM_FIELD", "Sample Custom Field"],
  ["WORK_ITEM_NAME", "Work Item Name"],
  ["RESULT_VALUE", "Result Value"],
];

const VALUE_TYPES = ["STRING", "NUMBER", "BOOLEAN"];

async function apiGetAllPages(basePath) {
  const separator = basePath.includes("?") ? "&" : "?";
  let page = 1;
  let results = [];

  while (page <= 50) {
    const data = await apiGet(`${basePath}${separator}page=${page}`);

    if (!data?.results) return data || [];

    results = [...results, ...data.results];

    if (!data.next) break;

    page += 1;
  }

  return results;
}

export default function DataMigration() {
  const [me, setMe] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [projects, setProjects] = useState([]);
  const [jobs, setJobs] = useState([]);

  const [err, setErr] = useState("");
  const [success, setSuccess] = useState("");

  const [profileName, setProfileName] = useState("Pilot Migration");
  const [sourceSystem, setSourceSystem] = useState("Legacy DB");
  const [description, setDescription] = useState("");

  const [selectedProfile, setSelectedProfile] = useState("");
  const [sourceColumn, setSourceColumn] = useState("");
  const [targetType, setTargetType] = useState("SAMPLE_ID");
  const [targetField, setTargetField] = useState("");
  const [valueType, setValueType] = useState("STRING");
  const [required, setRequired] = useState(false);

  const [migrationProject, setMigrationProject] = useState("");
  const [uploadFile, setUploadFile] = useState(null);
  const [previewJob, setPreviewJob] = useState(null);
  const [confirming, setConfirming] = useState(false);
  const [previewing, setPreviewing] = useState(false);

  async function load() {
    setErr("");

    try {
      const [meData, profileList, projectList, jobList] = await Promise.all([
        apiGet("/api/me/"),
        apiGetAllPages("/api/migration-profiles/"),
        apiGetAllPages("/api/projects/"),
        apiGetAllPages("/api/migration-jobs/"),
      ]);

      setMe(meData);
      setProfiles(profileList);
      setProjects(projectList);
      setJobs(jobList);

      if (!selectedProfile && profileList.length > 0) {
        setSelectedProfile(String(profileList[0].id));
      }
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const userCanWrite = canWrite(me);
  const activeProfile = profiles.find(
    (profile) => String(profile.id) === String(selectedProfile)
  );

  async function createProfile(e) {
    e.preventDefault();
    setErr("");
    setSuccess("");

    try {
      const profile = await apiPost("/api/migration-profiles/", {
        name: profileName,
        source_system: sourceSystem,
        source_type: "CSV",
        description,
      });

      setSuccess("Migration profile created.");
      setSelectedProfile(String(profile.id));
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function createMapping(e) {
    e.preventDefault();
    setErr("");
    setSuccess("");

    try {
      await apiPost("/api/migration-field-mappings/", {
        profile: Number(selectedProfile),
        source_column: sourceColumn,
        target_type: targetType,
        target_field: targetField,
        value_type: valueType,
        required,
      });

      setSourceColumn("");
      setTargetField("");
      setRequired(false);
      setSuccess("Field mapping added.");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  function buildFormData() {
    const formData = new FormData();
    formData.append("profile", selectedProfile);
    if (migrationProject) formData.append("project", migrationProject);
    formData.append("uploaded_file", uploadFile);
    return formData;
  }

  async function previewMigration() {
    setErr("");
    setSuccess("");
    setPreviewJob(null);
    setPreviewing(true);

    try {
      const data = await apiPostForm(
        "/api/migration-jobs/preview/",
        buildFormData()
      );

      setPreviewJob(data);
      setSuccess("Migration preview completed.");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setPreviewing(false);
    }
  }

  async function confirmMigration() {
    setErr("");
    setSuccess("");
    setConfirming(true);

    try {
      const data = await apiPostForm(
        "/api/migration-jobs/confirm/",
        buildFormData()
      );

      setPreviewJob(data);
      setSuccess("Migration imported successfully.");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Data Migration</h1>
          <p className="page-subtitle">
            Map old database exports into OpenLIMS projects, samples, external IDs,
            custom fields, work items, and results.
          </p>
        </div>

        <Badge bg="dark">v0.16 preview</Badge>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}
      {success && <Alert variant="success">{success}</Alert>}

      <Alert variant="info">
        Start with one CSV from an old database. Create a profile, map columns,
        preview the migration, then confirm only after reviewing the dry run.
      </Alert>

      <div className="row g-4 mb-4">
        <div className="col-lg-5">
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Create Migration Profile</h5>

              <Form onSubmit={createProfile}>
                <Row className="g-2">
                  <Col md={12}>
                    <Form.Control
                      placeholder="Profile name"
                      value={profileName}
                      onChange={(e) => setProfileName(e.target.value)}
                      disabled={!userCanWrite}
                    />
                  </Col>

                  <Col md={12}>
                    <Form.Control
                      placeholder="Source system"
                      value={sourceSystem}
                      onChange={(e) => setSourceSystem(e.target.value)}
                      disabled={!userCanWrite}
                    />
                  </Col>

                  <Col md={12}>
                    <Form.Control
                      as="textarea"
                      rows={2}
                      placeholder="Description"
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      disabled={!userCanWrite}
                    />
                  </Col>

                  <Col md={12}>
                    <Button
                      type="submit"
                      variant="dark"
                      className="w-100"
                      disabled={!userCanWrite || !profileName || !sourceSystem}
                    >
                      Create Profile
                    </Button>
                  </Col>
                </Row>
              </Form>
            </Card.Body>
          </Card>
        </div>

        <div className="col-lg-7">
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Add Field Mapping</h5>

              <Form onSubmit={createMapping}>
                <Row className="g-2">
                  <Col md={12}>
                    <Form.Select
                      value={selectedProfile}
                      onChange={(e) => setSelectedProfile(e.target.value)}
                      disabled={!userCanWrite}
                    >
                      <option value="">Select profile</option>
                      {profiles.map((profile) => (
                        <option key={profile.id} value={profile.id}>
                          {profile.name} — {profile.source_system}
                        </option>
                      ))}
                    </Form.Select>
                  </Col>

                  <Col md={4}>
                    <Form.Control
                      placeholder="Old CSV column"
                      value={sourceColumn}
                      onChange={(e) => setSourceColumn(e.target.value)}
                      disabled={!userCanWrite}
                    />
                  </Col>

                  <Col md={4}>
                    <Form.Select
                      value={targetType}
                      onChange={(e) => setTargetType(e.target.value)}
                      disabled={!userCanWrite}
                    >
                      {TARGET_TYPES.map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </Form.Select>
                  </Col>

                  <Col md={4}>
                    <Form.Control
                      placeholder="Target field/key/label"
                      value={targetField}
                      onChange={(e) => setTargetField(e.target.value)}
                      disabled={!userCanWrite}
                    />
                  </Col>

                  <Col md={4}>
                    <Form.Select
                      value={valueType}
                      onChange={(e) => setValueType(e.target.value)}
                      disabled={!userCanWrite}
                    >
                      {VALUE_TYPES.map((item) => (
                        <option key={item} value={item}>
                          {item}
                        </option>
                      ))}
                    </Form.Select>
                  </Col>

                  <Col md={4} className="d-flex align-items-center">
                    <Form.Check
                      type="checkbox"
                      label="Required"
                      checked={required}
                      onChange={(e) => setRequired(e.target.checked)}
                      disabled={!userCanWrite}
                    />
                  </Col>

                  <Col md={4}>
                    <Button
                      type="submit"
                      variant="dark"
                      className="w-100"
                      disabled={!userCanWrite || !selectedProfile || !sourceColumn}
                    >
                      Add Mapping
                    </Button>
                  </Col>
                </Row>
              </Form>

              {activeProfile && (
                <div className="mt-4">
                  <div className="feed-meta mb-2">
                    Current mappings for {activeProfile.name}
                  </div>

                  {activeProfile.field_mappings?.length === 0 ? (
                    <div className="empty-state">No mappings yet.</div>
                  ) : (
                    <Table responsive hover className="app-table">
                      <thead>
                        <tr>
                          <th>Source</th>
                          <th>Target</th>
                          <th>Field</th>
                          <th>Type</th>
                        </tr>
                      </thead>

                      <tbody>
                        {activeProfile.field_mappings.map((mapping) => (
                          <tr key={mapping.id}>
                            <td>{mapping.source_column}</td>
                            <td>{mapping.target_type}</td>
                            <td>{mapping.target_field || "-"}</td>
                            <td>{mapping.value_type}</td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  )}
                </div>
              )}
            </Card.Body>
          </Card>
        </div>
      </div>

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Upload and Preview Migration CSV</h5>

          <Row className="g-2 align-items-center">
            <Col md={4}>
              <Form.Select
                value={selectedProfile}
                onChange={(e) => setSelectedProfile(e.target.value)}
                disabled={!userCanWrite}
              >
                <option value="">Select profile</option>
                {profiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {profile.name}
                  </option>
                ))}
              </Form.Select>
            </Col>

            <Col md={4}>
              <Form.Select
                value={migrationProject}
                onChange={(e) => setMigrationProject(e.target.value)}
                disabled={!userCanWrite}
              >
                <option value="">Use project from CSV mapping</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.code} - {project.name}
                  </option>
                ))}
              </Form.Select>
            </Col>

            <Col md={4}>
              <Form.Control
                type="file"
                accept=".csv,text/csv"
                disabled={!userCanWrite}
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
              />
            </Col>
          </Row>

          <Row className="g-2 mt-3">
            <Col md={6}>
              <Button
                variant="outline-dark"
                className="w-100"
                onClick={previewMigration}
                disabled={!userCanWrite || !selectedProfile || !uploadFile || previewing}
              >
                {previewing ? "Previewing..." : "Preview Migration"}
              </Button>
            </Col>

            <Col md={6}>
              <Button
                variant="dark"
                className="w-100"
                onClick={confirmMigration}
                disabled={!userCanWrite || !selectedProfile || !uploadFile || confirming}
              >
                {confirming ? "Importing..." : "Confirm Migration Import"}
              </Button>
            </Col>
          </Row>

          {previewJob && (
            <Card className="app-card mt-4">
              <Card.Body>
                <h5 className="section-title">Migration Summary</h5>

                <div className="row g-3 mb-3">
                  <div className="col-md-3">
                    <div className="soft-card">
                      <div className="feed-meta">Rows</div>
                      <div className="fw-semibold">
                        {previewJob.summary?.rows_processed ?? 0}
                      </div>
                    </div>
                  </div>

                  <div className="col-md-3">
                    <div className="soft-card">
                      <div className="feed-meta">Samples to Create</div>
                      <div className="fw-semibold">
                        {previewJob.summary?.samples_to_create?.length ??
                          previewJob.summary?.samples_created?.length ??
                          0}
                      </div>
                    </div>
                  </div>

                  <div className="col-md-3">
                    <div className="soft-card">
                      <div className="feed-meta">Results</div>
                      <div className="fw-semibold">
                        {previewJob.summary?.results_to_create ??
                          previewJob.summary?.results_created ??
                          0}
                      </div>
                    </div>
                  </div>

                  <div className="col-md-3">
                    <div className="soft-card">
                      <div className="feed-meta">Skipped</div>
                      <div className="fw-semibold">
                        {previewJob.summary?.skipped_rows?.length ?? 0}
                      </div>
                    </div>
                  </div>
                </div>

                {previewJob.summary?.unmapped_columns?.length > 0 && (
                  <Alert variant="warning">
                    <strong>Unmapped columns:</strong>{" "}
                    {previewJob.summary.unmapped_columns.join(", ")}
                  </Alert>
                )}

                {previewJob.summary?.preview_rows?.length > 0 && (
                  <Table responsive hover className="app-table">
                    <thead>
                      <tr>
                        <th>Row</th>
                        <th>Sample</th>
                        <th>Project</th>
                        <th>Status</th>
                      </tr>
                    </thead>

                    <tbody>
                      {previewJob.summary.preview_rows.map((row) => (
                        <tr key={row.row}>
                          <td>{row.row}</td>
                          <td>{row.sample_id || "-"}</td>
                          <td>{row.project || "-"}</td>
                          <td>
                            {row.will_skip ? (
                              <span className="text-danger">
                                {row.errors?.join(", ")}
                              </span>
                            ) : (
                              "Ready"
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                )}
              </Card.Body>
            </Card>
          )}
        </Card.Body>
      </Card>

      <Card className="app-card">
        <Card.Body>
          <h5 className="section-title">Migration History</h5>

          {jobs.length === 0 ? (
            <div className="empty-state">No migration jobs yet.</div>
          ) : (
            <Table responsive hover className="app-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Profile</th>
                  <th>Project</th>
                  <th>Status</th>
                  <th>Rows</th>
                  <th>Created</th>
                </tr>
              </thead>

              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id}>
                    <td>#{job.id}</td>
                    <td>{job.profile_name}</td>
                    <td>{job.project_code || "-"}</td>
                    <td>{job.status}</td>
                    <td>{job.summary?.rows_processed ?? 0}</td>
                    <td>{new Date(job.created_at).toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>
    </div>
  );
}
