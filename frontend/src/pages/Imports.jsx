import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  ProgressBar,
  Row,
  Table,
} from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGet, apiPost, apiPostForm } from "../api";
import { canWrite, isAdmin, readOnlyMessage } from "../authz";
import useJobSocket from "../hooks/useJobSocket";

function statusVariant(status) {
  switch (status) {
    case "COMPLETED":
      return "success";
    case "FAILED":
      return "danger";
    case "RUNNING":
      return "primary";
    case "PENDING":
      return "warning";
    default:
      return "secondary";
  }
}

function sourceVariant(sourceType) {
  switch (sourceType) {
    case "API":
      return "dark";
    case "SEQUENCE_FASTA":
      return "info";
    case "UPLOAD":
      return "secondary";
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

function progressPercent(job) {
  if (typeof job.progress_percent === "number") return job.progress_percent;
  if (!job.progress_total) return job.status === "COMPLETED" ? 100 : 0;
  return Math.round((job.progress_current / job.progress_total) * 100);
}

async function apiGetAllPages(basePath) {
  const separator = basePath.includes("?") ? "&" : "?";
  let page = 1;
  let results = [];

  while (page <= 50) {
    const data = await apiGet(`${basePath}${separator}page=${page}`);

    if (!data?.results) {
      return data || [];
    }

    results = [...results, ...data.results];

    if (!data.next) {
      break;
    }

    page += 1;
  }

  return results;
}

function isImportRealtimeMessage(message) {
  return [
    "import_job_update",
    "import_job_started",
    "import_job_completed",
    "import_job_failed",
  ].includes(message?.type);
}

export default function Imports() {
  const [me, setMe] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [projects, setProjects] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [err, setErr] = useState("");
  const [lastLiveUpdate, setLastLiveUpdate] = useState("");

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

  const [sequenceUploadInstrument, setSequenceUploadInstrument] = useState("");
  const [sequenceUploadProject, setSequenceUploadProject] = useState("");
  const [sequenceUploadFile, setSequenceUploadFile] = useState(null);
  const [sequencePreviewLoading, setSequencePreviewLoading] = useState(false);
  const [sequencePreviewData, setSequencePreviewData] = useState(null);
  const [sequenceImportLoading, setSequenceImportLoading] = useState(false);
  const [sequenceImportSummary, setSequenceImportSummary] = useState(null);

  const { connected } = useJobSocket({
    onMessage: (message) => {
      if (!isImportRealtimeMessage(message)) {
        return;
      }

      setLastLiveUpdate(message.message || "Import data updated.");
      load();
    },
  });

  async function load() {
    setErr("");

    try {
      const [meData, profileList, jobList, projectList] = await Promise.all([
        apiGet("/api/me/"),
        apiGetAllPages("/api/instrument-profiles/"),
        apiGetAllPages("/api/import-jobs/"),
        apiGetAllPages("/api/projects/"),
      ]);

      setMe(meData);
      setProfiles(profileList);
      setJobs(jobList);
      setProjects(projectList);

      if (!uploadInstrument && profileList.length > 0) {
        setUploadInstrument(String(profileList[0].id));
      }

      if (!sequenceUploadInstrument && profileList.length > 0) {
        const fastaProfile =
          profileList.find((p) => p.code === "FASTA-SEQ") ||
          profileList.find((p) => p.code === "MISEQ") ||
          profileList[0];

        setSequenceUploadInstrument(String(fastaProfile.id));
      }

      if (!mappingInstrument && profileList.length > 0) {
        setMappingInstrument(String(profileList[0].id));
      }
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const userIsAdmin = isAdmin(me);
  const userCanWrite = canWrite(me);
  const readOnlyText = readOnlyMessage(me);

  const selectedProfile = useMemo(
    () => profiles.find((p) => String(p.id) === String(mappingInstrument)),
    [profiles, mappingInstrument]
  );

  async function createProfile(e) {
    e.preventDefault();
    setErr("");

    if (!userIsAdmin) return;

    try {
      const createdProfile = await apiPost("/api/instrument-profiles/", {
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

      const profileList = await apiGetAllPages("/api/instrument-profiles/");
      setProfiles(profileList);

      const profileToSelect =
        profileList.find(
          (profile) => String(profile.id) === String(createdProfile?.id)
        ) ||
        profileList.find(
          (profile) =>
            profile.code?.toLowerCase() === createdProfile?.code?.toLowerCase()
        ) ||
        profileList.find(
          (profile) =>
            profile.code?.toLowerCase() === profileCode.toLowerCase()
        );

      if (profileToSelect) {
        setMappingInstrument(String(profileToSelect.id));
        setUploadInstrument(String(profileToSelect.id));
        setSequenceUploadInstrument(String(profileToSelect.id));
      }

      await load();
    } catch (e) {
      setErr(e.message || String(e));

      const profileList = await apiGetAllPages("/api/instrument-profiles/");
      setProfiles(profileList);

      const existingProfile = profileList.find(
        (profile) => profile.code?.toLowerCase() === profileCode.toLowerCase()
      );

      if (existingProfile) {
        setMappingInstrument(String(existingProfile.id));
        setUploadInstrument(String(existingProfile.id));
        setSequenceUploadInstrument(String(existingProfile.id));
      }
    }
  }

  async function createMapping(e) {
    e.preventDefault();
    setErr("");

    if (!userIsAdmin) return;

    try {
      await apiPost("/api/instrument-mappings/", {
        instrument: Number(mappingInstrument),
        source_column: mappingSourceColumn,
        target_key: mappingTargetKey,
        value_type: mappingValueType,
        min_value: mappingMinValue === "" ? null : Number(mappingMinValue),
        max_value: mappingMaxValue === "" ? null : Number(mappingMaxValue),
        allowed_values:
          mappingAllowedValues.trim() === ""
            ? null
            : mappingAllowedValues.split(",").map((v) => v.trim()),
      });

      setMappingSourceColumn("");
      setMappingTargetKey("");
      setMappingValueType("NUMBER");
      setMappingMinValue("");
      setMappingMaxValue("");
      setMappingAllowedValues("");

      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function previewImport() {
    setErr("");
    setPreviewData(null);
    setPreviewLoading(true);

    if (!userCanWrite) {
      setPreviewLoading(false);
      return;
    }

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
    setLastLiveUpdate("");

    if (!userCanWrite) return;

    try {
      const formData = new FormData();
      formData.append("instrument", uploadInstrument);
      if (uploadProject) formData.append("project", uploadProject);
      formData.append("uploaded_file", uploadFile);

      await apiPostForm("/api/import-jobs/", formData);

      setUploadFile(null);
      setPreviewData(null);
      setLastLiveUpdate("CSV import queued. Progress will update automatically.");

      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function previewFastaSequenceImport() {
    setErr("");
    setSequenceImportSummary(null);
    setSequencePreviewData(null);
    setSequencePreviewLoading(true);

    if (!userCanWrite) {
      setSequencePreviewLoading(false);
      return;
    }

    try {
      const formData = new FormData();

      formData.append("instrument", sequenceUploadInstrument);

      if (sequenceUploadProject) {
        formData.append("project", sequenceUploadProject);
      }

      formData.append("uploaded_file", sequenceUploadFile);

      const data = await apiPostForm(
        "/api/import-jobs/sequence-fasta-preview/",
        formData
      );

      setSequencePreviewData(data);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setSequencePreviewLoading(false);
    }
  }

  async function uploadFastaSequenceImport(e) {
    e.preventDefault();

    setErr("");
    setSequenceImportSummary(null);
    setSequenceImportLoading(true);

    if (!userCanWrite) {
      setSequenceImportLoading(false);
      return;
    }

    if (!sequencePreviewData) {
      setErr("Preview the FASTA import before confirming.");
      setSequenceImportLoading(false);
      return;
    }

    try {
      const formData = new FormData();

      formData.append("instrument", sequenceUploadInstrument);

      if (sequenceUploadProject) {
        formData.append("project", sequenceUploadProject);
      }

      formData.append("uploaded_file", sequenceUploadFile);

      const data = await apiPostForm(
        "/api/import-jobs/sequence-fasta-import/",
        formData
      );

      setSequenceUploadFile(null);
      setSequencePreviewData(null);
      setSequenceImportSummary(data.summary || {});

      await load();
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setSequenceImportLoading(false);
    }
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Imports</h1>
          <p className="page-subtitle">
            Manage instrument profiles, mappings, result imports, and sequence
            imports.
          </p>
        </div>

        <div className="inline-actions">
          <Badge bg={connected ? "success" : "secondary"}>
            {connected ? "Live updates on" : "Live updates off"}
          </Badge>

          <Button variant="outline-dark" size="sm" onClick={load}>
            Refresh
          </Button>
        </div>
      </div>

      {lastLiveUpdate && (
        <Alert variant="info" className="mb-4">
          {lastLiveUpdate}
        </Alert>
      )}

      {err && <Alert variant="danger">{err}</Alert>}
      {readOnlyText && <Alert variant="info">{readOnlyText}</Alert>}

      {userIsAdmin && (
        <div className="row g-4 mb-4">
          <div className="col-lg-5">
            <Card className="app-card h-100">
              <Card.Body>
                <h5 className="section-title">Create Instrument Profile</h5>

                <Form onSubmit={createProfile}>
                  <Row className="g-2">
                    <Col md={6}>
                      <Form.Control
                        placeholder="Name"
                        value={profileName}
                        onChange={(e) => setProfileName(e.target.value)}
                      />
                    </Col>

                    <Col md={3}>
                      <Form.Control
                        placeholder="Code"
                        value={profileCode}
                        onChange={(e) => setProfileCode(e.target.value)}
                      />
                    </Col>

                    <Col md={3}>
                      <Form.Control
                        placeholder="Delimiter"
                        value={delimiter}
                        onChange={(e) => setDelimiter(e.target.value)}
                      />
                    </Col>

                    <Col md={8}>
                      <Form.Control
                        placeholder="Sample ID column"
                        value={sampleIdColumn}
                        onChange={(e) => setSampleIdColumn(e.target.value)}
                      />
                    </Col>

                    <Col md={4}>
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
          </div>

          <div className="col-lg-7">
            <Card className="app-card h-100">
              <Card.Body>
                <h5 className="section-title">Create Column Mapping</h5>

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

                    <Col md={3}>
                      <Form.Select
                        value={mappingValueType}
                        onChange={(e) => setMappingValueType(e.target.value)}
                      >
                        <option value="NUMBER">NUMBER</option>
                        <option value="STRING">STRING</option>
                        <option value="BOOLEAN">BOOLEAN</option>
                      </Form.Select>
                    </Col>

                    <Col md={2}>
                      <Form.Control
                        placeholder="Min"
                        value={mappingMinValue}
                        onChange={(e) => setMappingMinValue(e.target.value)}
                      />
                    </Col>

                    <Col md={2}>
                      <Form.Control
                        placeholder="Max"
                        value={mappingMaxValue}
                        onChange={(e) => setMappingMaxValue(e.target.value)}
                      />
                    </Col>

                    <Col md={6}>
                      <Form.Control
                        placeholder="Allowed values, comma-separated"
                        value={mappingAllowedValues}
                        onChange={(e) => setMappingAllowedValues(e.target.value)}
                      />
                    </Col>

                    <Col md={2}>
                      <Button
                        type="submit"
                        variant="dark"
                        className="w-100"
                        disabled={
                          !mappingInstrument ||
                          !mappingSourceColumn ||
                          !mappingTargetKey
                        }
                      >
                        Add
                      </Button>
                    </Col>
                  </Row>
                </Form>

                {selectedProfile && (
                  <div className="mt-4">
                    <div className="feed-meta mb-2">
                      Current mappings for {selectedProfile.code}
                    </div>

                    {selectedProfile.column_mappings?.length === 0 ? (
                      <div className="empty-state">No mappings yet.</div>
                    ) : (
                      <Table responsive hover className="app-table">
                        <thead>
                          <tr>
                            <th>Source</th>
                            <th>Target</th>
                            <th>Type</th>
                            <th>Min</th>
                            <th>Max</th>
                            <th>Allowed</th>
                          </tr>
                        </thead>

                        <tbody>
                          {selectedProfile.column_mappings.map((m) => (
                            <tr key={m.id}>
                              <td>{m.source_column}</td>
                              <td>{m.target_key}</td>
                              <td>{m.value_type}</td>
                              <td>{m.min_value ?? "-"}</td>
                              <td>{m.max_value ?? "-"}</td>
                              <td>{m.allowed_values?.join(", ") || "-"}</td>
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
      )}

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Run CSV Result Import</h5>

          <Form onSubmit={uploadImportJob}>
            <Row className="g-2 align-items-center mb-3">
              <Col md={4}>
                <Form.Select
                  value={uploadInstrument}
                  onChange={(e) => setUploadInstrument(e.target.value)}
                  disabled={!userCanWrite}
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
                  disabled={!userCanWrite}
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
                  disabled={!userCanWrite}
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
                  disabled={
                    !userCanWrite || !uploadInstrument || !uploadFile || previewLoading
                  }
                >
                  {previewLoading ? "Previewing..." : "Preview CSV Import"}
                </Button>
              </Col>

              <Col md={6}>
                <Button
                  type="submit"
                  variant="dark"
                  className="w-100"
                  disabled={!userCanWrite || !uploadInstrument || !uploadFile}
                >
                  Queue CSV Import
                </Button>
              </Col>
            </Row>
          </Form>

          {previewData && (
            <Card className="app-card mt-4">
              <Card.Body>
                <h5 className="section-title">CSV Import Preview</h5>

                <div className="row g-3 mb-3">
                  <div className="col-md-3">
                    <div className="soft-card">
                      <div className="feed-meta">Instrument</div>
                      <div className="fw-semibold">
                        {previewData.instrument_code}
                      </div>
                    </div>
                  </div>

                  <div className="col-md-3">
                    <div className="soft-card">
                      <div className="feed-meta">Rows</div>
                      <div className="fw-semibold">
                        {previewData.rows_processed}
                      </div>
                    </div>
                  </div>

                  <div className="col-md-3">
                    <div className="soft-card">
                      <div className="feed-meta">Existing Samples</div>
                      <div className="fw-semibold">
                        {previewData.existing_samples}
                      </div>
                    </div>
                  </div>

                  <div className="col-md-3">
                    <div className="soft-card">
                      <div className="feed-meta">New Samples</div>
                      <div className="fw-semibold">
                        {previewData.new_samples}
                      </div>
                    </div>
                  </div>
                </div>

                {previewData.preview_rows?.length > 0 && (
                  <Table responsive hover className="app-table">
                    <thead>
                      <tr>
                        <th>Row</th>
                        <th>Sample</th>
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
                              ? row.errors.map((error, idx) => (
                                  <div key={idx} className="text-danger small">
                                    {error.column}: {error.reason}
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

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Run FASTA Sequence Import</h5>

          <p className="text-muted">
            Upload FASTA records from a sequencer. The first token in each FASTA
            header should match an existing sample ID, such as S-ALPHA-001.
          </p>

          <Form onSubmit={uploadFastaSequenceImport}>
            <Row className="g-2 align-items-center mb-3">
              <Col md={4}>
                <Form.Select
                  value={sequenceUploadInstrument}
                  onChange={(e) => {
                    setSequenceUploadInstrument(e.target.value);
                    setSequencePreviewData(null);
                    setSequenceImportSummary(null);
                  }}
                  disabled={!userCanWrite}
                >
                  <option value="">Select sequencer/instrument</option>

                  {profiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.code} - {p.name}
                    </option>
                  ))}
                </Form.Select>
              </Col>

              <Col md={4}>
                <Form.Select
                  value={sequenceUploadProject}
                  onChange={(e) => {
                    setSequenceUploadProject(e.target.value);
                    setSequencePreviewData(null);
                    setSequenceImportSummary(null);
                  }}
                  disabled={!userCanWrite}
                >
                  <option value="">Use sample project</option>

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
                  accept=".fasta,.fa,.fna,text/plain"
                  disabled={!userCanWrite}
                  onChange={(e) => {
                    setSequenceUploadFile(e.target.files?.[0] || null);
                    setSequencePreviewData(null);
                    setSequenceImportSummary(null);
                  }}
                />
              </Col>
            </Row>

            <Row className="g-2">
              <Col md={6}>
                <Button
                  type="button"
                  variant="outline-dark"
                  className="w-100"
                  onClick={previewFastaSequenceImport}
                  disabled={
                    !userCanWrite ||
                    !sequenceUploadInstrument ||
                    !sequenceUploadFile ||
                    sequencePreviewLoading
                  }
                >
                  {sequencePreviewLoading
                    ? "Previewing..."
                    : "Preview FASTA Import"}
                </Button>
              </Col>

              <Col md={6}>
                <Button
                  type="submit"
                  variant="dark"
                  className="w-100"
                  disabled={
                    !userCanWrite ||
                    !sequenceUploadInstrument ||
                    !sequenceUploadFile ||
                    !sequencePreviewData ||
                    sequencePreviewData.will_create_count === 0 ||
                    sequenceImportLoading
                  }
                >
                  {sequenceImportLoading
                    ? "Importing FASTA..."
                    : `Confirm Import ${
                        sequencePreviewData
                          ? `(${sequencePreviewData.will_create_count})`
                          : ""
                      }`}
                </Button>
              </Col>
            </Row>
          </Form>

          {sequencePreviewData && (
            <Card className="app-card mt-4">
              <Card.Body>
                <h5 className="section-title">FASTA Import Preview</h5>

                <div className="row g-3 mb-4">
                  <div className="col-md-3">
                    <div className="soft-card">
                      <div className="feed-meta">Records Found</div>
                      <div className="fw-semibold">
                        {sequencePreviewData.records_processed}
                      </div>
                    </div>
                  </div>

                  <div className="col-md-3">
                    <div className="soft-card">
                      <div className="feed-meta">Matched Samples</div>
                      <div className="fw-semibold">
                        {sequencePreviewData.matched_count}
                      </div>
                    </div>
                  </div>

                  <div className="col-md-3">
                    <div className="soft-card">
                      <div className="feed-meta">Will Create</div>
                      <div className="fw-semibold">
                        {sequencePreviewData.will_create_count}
                      </div>
                    </div>
                  </div>

                  <div className="col-md-3">
                    <div className="soft-card">
                      <div className="feed-meta">Unmatched</div>
                      <div className="fw-semibold">
                        {sequencePreviewData.unmatched_count}
                      </div>
                    </div>
                  </div>
                </div>

                {sequencePreviewData.matched_records?.length > 0 && (
                  <>
                    <div className="feed-meta mb-2">Matched Records</div>

                    <Table responsive hover className="app-table">
                      <thead>
                        <tr>
                          <th>Header</th>
                          <th>Sample</th>
                          <th>Project</th>
                          <th>Type</th>
                          <th>Length</th>
                        </tr>
                      </thead>

                      <tbody>
                        {sequencePreviewData.matched_records.map((record) => (
                          <tr key={`${record.row}-${record.header}`}>
                            <td>{record.header}</td>
                            <td>{record.sample_code}</td>
                            <td>{record.project_code || "-"}</td>
                            <td>{record.sequence_type}</td>
                            <td>{record.sequence_length} bp</td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  </>
                )}

                {sequencePreviewData.unmatched_records?.length > 0 && (
                  <>
                    <Alert variant="warning" className="mt-3">
                      <strong>Unmatched FASTA records:</strong> These records
                      will be skipped because the first token in the FASTA
                      header does not match an existing sample ID.
                    </Alert>

                    <Table responsive hover className="app-table">
                      <thead>
                        <tr>
                          <th>Header</th>
                          <th>Sample Token</th>
                          <th>Length</th>
                          <th>Reason</th>
                        </tr>
                      </thead>

                      <tbody>
                        {sequencePreviewData.unmatched_records.map((record) => (
                          <tr key={`${record.row}-${record.header}`}>
                            <td>{record.header}</td>
                            <td>{record.sample_code}</td>
                            <td>{record.sequence_length} bp</td>
                            <td>{record.reason}</td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  </>
                )}

                {sequencePreviewData.skipped_records?.length > 0 && (
                  <Alert variant="secondary" className="mt-3 mb-0">
                    {sequencePreviewData.skipped_records.length} empty records
                    will be skipped.
                  </Alert>
                )}
              </Card.Body>
            </Card>
          )}

          {sequenceImportSummary && (
            <Card className="app-card mt-4">
              <Card.Body>
                <h5 className="section-title">FASTA Import Summary</h5>

                <div className="row g-3 mb-3">
                  <div className="col-md-3">
                    <div className="soft-card">
                      <div className="feed-meta">Records Processed</div>
                      <div className="fw-semibold">
                        {sequenceImportSummary.records_processed ?? 0}
                      </div>
                    </div>
                  </div>

                  <div className="col-md-3">
                    <div className="soft-card">
                      <div className="feed-meta">Sequences Created</div>
                      <div className="fw-semibold">
                        {sequenceImportSummary.sequences_created ?? 0}
                      </div>
                    </div>
                  </div>

                  <div className="col-md-3">
                    <div className="soft-card">
                      <div className="feed-meta">Samples Matched</div>
                      <div className="fw-semibold">
                        {sequenceImportSummary.samples_matched ?? 0}
                      </div>
                    </div>
                  </div>

                  <div className="col-md-3">
                    <div className="soft-card">
                      <div className="feed-meta">Unmatched</div>
                      <div className="fw-semibold">
                        {sequenceImportSummary.unmatched_records?.length ?? 0}
                      </div>
                    </div>
                  </div>
                </div>

                {sequenceImportSummary.unmatched_records?.length > 0 && (
                  <Alert variant="warning" className="mb-0">
                    Some FASTA records did not match existing samples. Make sure
                    the first token in the FASTA header is the sample ID.
                  </Alert>
                )}
              </Card.Body>
            </Card>
          )}
        </Card.Body>
      </Card>

      <Card className="app-card">
        <Card.Body>
          <h5 className="section-title">Import History</h5>

          {jobs.length === 0 ? (
            <div className="empty-state">No import jobs yet.</div>
          ) : (
            <Table responsive hover className="app-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Instrument</th>
                  <th>Source</th>
                  <th>Status</th>
                  <th>Progress</th>
                  <th>Created</th>
                  <th>Summary</th>
                </tr>
              </thead>

              <tbody>
                {jobs.map((job) => {
                  const percent = progressPercent(job);

                  return (
                    <tr key={job.id}>
                      <td>
                        <Link to={`/imports/${job.id}`}>#{job.id}</Link>
                      </td>

                      <td>
                        {job.instrument_code ||
                          profiles.find((p) => p.id === job.instrument)?.code ||
                          job.instrument}
                      </td>

                      <td>
                        <Badge bg={sourceVariant(job.source_type)}>
                          {job.source_type || "UPLOAD"}
                        </Badge>
                      </td>

                      <td>
                        <Badge bg={statusVariant(job.status)}>
                          {job.status}
                        </Badge>
                      </td>

                      <td style={{ minWidth: "220px" }}>
                        <ProgressBar
                          now={percent}
                          label={`${percent}%`}
                          variant={job.status === "FAILED" ? "danger" : "dark"}
                        />

                        <div className="feed-meta mt-1">
                          {job.progress_message || "-"}
                        </div>
                      </td>

                      <td>{formatTimestamp(job.created_at)}</td>

                      <td style={{ minWidth: "320px" }}>
                        {job.summary?.error ? (
                          <span className="text-danger">
                            {job.summary.error}
                          </span>
                        ) : job.source_type === "SEQUENCE_FASTA" ? (
                          <div className="small">
                            <div>
                              Records: {job.summary?.records_processed ?? 0}
                            </div>
                            <div>
                              Sequences created:{" "}
                              {job.summary?.sequences_created ?? 0}
                            </div>
                            <div>
                              Samples matched:{" "}
                              {job.summary?.samples_matched ?? 0}
                            </div>
                            <div>
                              Unmatched:{" "}
                              {job.summary?.unmatched_records?.length ?? 0}
                            </div>
                          </div>
                        ) : (
                          <div className="small">
                            <div>Rows: {job.summary?.rows_processed ?? 0}</div>
                            <div>
                              Samples created:{" "}
                              {job.summary?.samples_created ?? 0}
                            </div>
                            <div>
                              Results created:{" "}
                              {job.summary?.results_created ?? 0}
                            </div>
                            <div>
                              Skipped rows:{" "}
                              {job.summary?.skipped_rows?.length ?? 0}
                            </div>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>
    </div>
  );
}