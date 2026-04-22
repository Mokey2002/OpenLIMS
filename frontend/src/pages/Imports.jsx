import { useEffect, useMemo, useState } from "react";
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


function statusVariant(status) {
  switch (status) {
    case "COMPLETED":
      return "success";
    case "FAILED":
      return "danger";
    case "PENDING":
      return "warning";
    default:
      return "secondary";
  }
}

function formatTimestamp(ts) {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export default function Imports() {
  const [me, setMe] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [projects, setProjects] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  const [profileName, setProfileName] = useState("");
  const [profileCode, setProfileCode] = useState("");
  const [delimiter, setDelimiter] = useState(",");
  const [hasHeader, setHasHeader] = useState(true);
  const [sampleIdColumn, setSampleIdColumn] = useState("sample_id");

  const [mappingInstrument, setMappingInstrument] = useState("");
  const [mappingSourceColumn, setMappingSourceColumn] = useState("");
  const [mappingTargetKey, setMappingTargetKey] = useState("");
  const [mappingValueType, setMappingValueType] = useState("NUMBER");

  const [uploadInstrument, setUploadInstrument] = useState("");
  const [uploadProject, setUploadProject] = useState("");
  const [uploadFile, setUploadFile] = useState(null);

  const [previewData, setPreviewData] = useState(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  async function load() {
    setErr("");
    setLoading(true);

    try {
      const [meData, profilesData, jobsData, projectsData] = await Promise.all([
        apiGet("/api/me/"),
        apiGet("/api/instrument-profiles/"),
        apiGet("/api/import-jobs/"),
        apiGet("/api/projects/"),
      ]);

      setMe(meData);
      setProfiles(profilesData);
      setJobs(jobsData);
      setProjects(projectsData);

      if (!uploadInstrument && profilesData.length > 0) {
        setUploadInstrument(String(profilesData[0].id));
      }

      if (!mappingInstrument && profilesData.length > 0) {
        setMappingInstrument(String(profilesData[0].id));
      }
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const isAdmin = me?.roles?.includes("admin");
  const selectedProfile = useMemo(
    () => profiles.find((p) => String(p.id) === String(mappingInstrument)),
    [profiles, mappingInstrument]
  );

  async function createProfile(e) {
    e.preventDefault();
    setErr("");

    try {
      await apiPost("/api/instrument-profiles/", {
        name: profileName,
        code: profileCode,
        delimiter,
        has_header: hasHeader,
        sample_id_column: sampleIdColumn,
      });

      setProfileName("");
      setProfileCode("");
      setDelimiter(",");
      setHasHeader(true);
      setSampleIdColumn("sample_id");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
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
      });

      setMappingSourceColumn("");
      setMappingTargetKey("");
      setMappingValueType("NUMBER");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

async function previewImport() {
  setErr("");
  setPreviewData(null);
  setPreviewLoading(true);

  try {
    const formData = new FormData();
    formData.append("instrument", uploadInstrument);
    formData.append("uploaded_file", uploadFile);

    const data = await apiPostForm("/api/import-jobs/preview/", formData);
    setPreviewData(data);
  } catch (e) {
    setErr(e.message || String(e));
  } finally {
    setPreviewLoading(false);
  }
}

  async function uploadImportJob(e) {
    e.preventDefault();
    setErr("");

    try {
      const formData = new FormData();
      formData.append("instrument", uploadInstrument);
      if (uploadProject) {
        formData.append("project", uploadProject);
      }
      formData.append("uploaded_file", uploadFile);

      await apiPostForm("/api/import-jobs/", formData);

      setUploadFile(null);
      setPreviewData(null);
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  if (loading) {
    return <div>Loading...</div>;
  }

  return (
    <div className="w-100">
      <h2 className="mb-3">Imports</h2>

      {err && <Alert variant="danger">{err}</Alert>}

      {isAdmin && (
        <>
          <Card className="shadow-sm border-0 mb-4">
            <Card.Body>
              <h5 className="mb-3">Create Instrument Profile</h5>

              <Form onSubmit={createProfile}>
                <Row className="g-2">
                  <Col md={3}>
                    <Form.Control
                      placeholder="Name"
                      value={profileName}
                      onChange={(e) => setProfileName(e.target.value)}
                    />
                  </Col>
                  <Col md={2}>
                    <Form.Control
                      placeholder="Code"
                      value={profileCode}
                      onChange={(e) => setProfileCode(e.target.value)}
                    />
                  </Col>
                  <Col md={2}>
                    <Form.Control
                      placeholder="Delimiter"
                      value={delimiter}
                      onChange={(e) => setDelimiter(e.target.value)}
                    />
                  </Col>
                  <Col md={3}>
                    <Form.Control
                      placeholder="Sample ID column"
                      value={sampleIdColumn}
                      onChange={(e) => setSampleIdColumn(e.target.value)}
                    />
                  </Col>
                  <Col md={2}>
                    <Button
                      type="submit"
                      variant="dark"
                      className="w-100"
                      disabled={!profileName || !profileCode || !sampleIdColumn}
                    >
                      Create
                    </Button>
                  </Col>
                </Row>

                <Form.Check
                  className="mt-3"
                  type="checkbox"
                  label="CSV has header row"
                  checked={hasHeader}
                  onChange={(e) => setHasHeader(e.target.checked)}
                />
              </Form>
            </Card.Body>
          </Card>

          <Card className="shadow-sm border-0 mb-4">
            <Card.Body>
              <h5 className="mb-3">Create Column Mapping</h5>

              <Form onSubmit={createMapping}>
                <Row className="g-2">
                  <Col md={3}>
                    <Form.Select
                      value={mappingInstrument}
                      onChange={(e) => setMappingInstrument(e.target.value)}
                    >
                      {profiles.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.code} - {p.name}
                        </option>
                      ))}
                    </Form.Select>
                  </Col>
                  <Col md={3}>
                    <Form.Control
                      placeholder="Source column"
                      value={mappingSourceColumn}
                      onChange={(e) => setMappingSourceColumn(e.target.value)}
                    />
                  </Col>
                  <Col md={3}>
                    <Form.Control
                      placeholder="Target key"
                      value={mappingTargetKey}
                      onChange={(e) => setMappingTargetKey(e.target.value)}
                    />
                  </Col>
                  <Col md={2}>
                    <Form.Select
                      value={mappingValueType}
                      onChange={(e) => setMappingValueType(e.target.value)}
                    >
                      <option value="NUMBER">NUMBER</option>
                      <option value="STRING">STRING</option>
                      <option value="BOOLEAN">BOOLEAN</option>
                    </Form.Select>
                  </Col>
                  <Col md={1}>
                    <Button
                      type="submit"
                      variant="dark"
                      className="w-100"
                      disabled={!mappingInstrument || !mappingSourceColumn || !mappingTargetKey}
                    >
                      Add
                    </Button>
                  </Col>
                </Row>
              </Form>

              {selectedProfile && (
                <div className="mt-4">
                  <div className="fw-semibold mb-2">
                    Current mappings for {selectedProfile.code}
                  </div>

                  {selectedProfile.column_mappings?.length === 0 ? (
                    <Alert variant="light" className="mb-0">
                      No mappings yet.
                    </Alert>
                  ) : (
                    <Table responsive hover className="mb-0">
                      <thead>
                        <tr>
                          <th>Source Column</th>
                          <th>Target Key</th>
                          <th>Value Type</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selectedProfile.column_mappings.map((m) => (
                          <tr key={m.id}>
                            <td>{m.source_column}</td>
                            <td>{m.target_key}</td>
                            <td>{m.value_type}</td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  )}
                </div>
              )}
            </Card.Body>
          </Card>
        </>
      )}

      <Card className="shadow-sm border-0 mb-4">
        <Card.Body>
          <h5 className="mb-3">Upload Import File</h5>

          <Form onSubmit={uploadImportJob}>
            <Row className="g-2 align-items-center mb-3">
              <Col md={4}>
                <Form.Select
                  value={uploadInstrument}
                  onChange={(e) => setUploadInstrument(e.target.value)}
                >
                  <option value="">Select instrument</option>
                  {profiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.code} - {p.name}
                    </option>
                  ))}
                </Form.Select>
              </Col>
              <Col md={4}>
                <Form.Select
                  value={uploadProject}
                  onChange={(e) => setUploadProject(e.target.value)}
                >
                  <option value="">No project</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.code} - {p.name}
                    </option>
                  ))}
                </Form.Select>
              </Col>
              <Col md={4}>
                <Form.Control
                  type="file"
                  accept=".csv,text/csv"
                  onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                />
              </Col>
            </Row>

            <Row className="g-2">
              <Col md={6}>
                <Button
                  type="button"
                  variant="outline-dark"
                  className="w-100"
                  onClick={previewImport}
                  disabled={!uploadInstrument || !uploadFile || previewLoading}
                >
                  {previewLoading ? "Previewing..." : "Preview Import"}
                </Button>
              </Col>
              <Col md={6}>
                <Button
                  type="submit"
                  variant="dark"
                  className="w-100"
                  disabled={!uploadInstrument || !uploadFile}
                >
                  Run Import
                </Button>
              </Col>
            </Row>
          </Form>

          {previewData && (
            <Card className="mt-4 border">
              <Card.Body>
                <h6 className="mb-3">Preview</h6>
                <div className="small mb-3">
                  <div>Instrument: {previewData.instrument_code}</div>
                  <div>Rows: {previewData.rows_processed}</div>
                  <div>Existing samples: {previewData.existing_samples}</div>
                  <div>New samples to create: {previewData.new_samples}</div>
                  <div>Valid result cells: {previewData.valid_result_cells}</div>
                  <div>Skipped rows: {previewData.skipped_rows?.length ?? 0}</div>
                </div>

                {previewData.skipped_rows?.length > 0 && (
                  <Alert variant="warning">
                    {previewData.skipped_rows.map((row, idx) => (
                      <div key={idx}>
                        Row {row.row}: {row.reason}
                      </div>
                    ))}
                  </Alert>
                )}

                {previewData.preview_rows?.length > 0 && (
                  <Table responsive hover className="mb-0">
                    <thead>
                      <tr>
                        <th>Row</th>
                        <th>Sample ID</th>
                        <th>Status</th>
                        <th>Valid Cells</th>
                        <th>Errors</th>
                      </tr>
                    </thead>
                    <tbody>
                      {previewData.preview_rows.map((row) => (
                        <tr key={row.row}>
                          <td>{row.row}</td>
                          <td>{row.sample_id}</td>
                          <td>{row.exists ? "Existing" : "Will create"}</td>
                          <td>{row.valid_result_cells}</td>
                          <td>
                            {row.errors?.length > 0
                              ? row.errors.map((e, i) => (
                                  <div key={i} className="small text-danger">
                                    {e.column}: {e.reason}
                                  </div>
                                ))
                              : "-"}
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

      <Card className="shadow-sm border-0">
        <Card.Body>
          <h5 className="mb-3">Import History</h5>

          {jobs.length === 0 ? (
            <Alert variant="light" className="mb-0">
              No import jobs yet.
            </Alert>
          ) : (
            <Table responsive hover className="mb-0">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Instrument</th>
                  <th>Status</th>
                  <th>Uploaded By</th>
                  <th>Created</th>
                  <th>Summary</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id}>
                    <td>{job.id}</td>
                    <td>{profiles.find((p) => p.id === job.instrument)?.code || job.instrument}</td>
                    <td>
                      <Badge bg={statusVariant(job.status)}>
                        {job.status}
                      </Badge>
                    </td>
                    <td>{job.uploaded_by_username || "-"}</td>
                    <td>{formatTimestamp(job.created_at)}</td>
                    <td style={{ minWidth: "320px" }}>
                      {job.summary?.error ? (
                        <span className="text-danger">{job.summary.error}</span>
                      ) : (
                        <div className="small">
                          <div>Rows: {job.summary?.rows_processed ?? 0}</div>
                          <div>Samples matched: {job.summary?.samples_matched ?? 0}</div>
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
        </Card.Body>
      </Card>
    </div>
  );
}