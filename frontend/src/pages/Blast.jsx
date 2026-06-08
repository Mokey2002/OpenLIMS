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
import { apiGet, apiPost, apiPostForm } from "../api";

function formatTimestamp(value) {
  if (!value) return "-";

  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function statusVariant(status) {
  switch (status) {
    case "READY":
    case "COMPLETED":
      return "success";
    case "FAILED":
      return "danger";
    case "BUILDING":
    case "RUNNING":
      return "primary";
    case "PENDING":
    case "NEW":
      return "warning";
    default:
      return "secondary";
  }
}

function programForSequence(sequenceType) {
  if (sequenceType === "PROTEIN") return "blastp";
  return "blastn";
}

export default function Blast() {
  const [databases, setDatabases] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [sequences, setSequences] = useState([]);
  const [projects, setProjects] = useState([]);

  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [success, setSuccess] = useState("");

  const [dbName, setDbName] = useState("");
  const [dbDescription, setDbDescription] = useState("");
  const [dbType, setDbType] = useState("DNA");
  const [dbFile, setDbFile] = useState(null);

  const [jobName, setJobName] = useState("");
  const [querySequenceId, setQuerySequenceId] = useState("");
  const [databaseId, setDatabaseId] = useState("");
  const [program, setProgram] = useState("blastn");
  const [maxTargetSeqs, setMaxTargetSeqs] = useState(25);
  const [evalue, setEvalue] = useState("10");
  const [projectId, setProjectId] = useState("");

  const [selectedJobId, setSelectedJobId] = useState(null);

  async function load() {
    setErr("");
    setLoading(true);

    try {
      const [databaseData, jobData, sequenceData, projectData] =
        await Promise.all([
          apiGet("/api/blast-databases/"),
          apiGet("/api/blast-jobs/"),
          apiGet("/api/sequences/"),
          apiGet("/api/projects/"),
        ]);

      setDatabases(databaseData.results || databaseData || []);
      setJobs(jobData.results || jobData || []);
      setSequences(sequenceData.results || sequenceData || []);
      setProjects(projectData.results || projectData || []);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const readyDatabases = useMemo(() => {
    return databases.filter((database) => database.status === "READY");
  }, [databases]);

  const selectedSequence = useMemo(() => {
    return sequences.find(
      (sequence) => String(sequence.id) === String(querySequenceId)
    );
  }, [sequences, querySequenceId]);

  const selectedJob = useMemo(() => {
    if (!selectedJobId && jobs.length > 0) return jobs[0];

    return jobs.find((job) => String(job.id) === String(selectedJobId));
  }, [jobs, selectedJobId]);

  useEffect(() => {
    if (selectedSequence) {
      const suggestedProgram = programForSequence(selectedSequence.sequence_type);
      setProgram(suggestedProgram);

      if (!jobName) {
        setJobName(`BLAST ${selectedSequence.name}`);
      }

      if (!projectId && selectedSequence.project) {
        setProjectId(String(selectedSequence.project));
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSequence]);

  async function createDatabase(e) {
    e.preventDefault();

    setErr("");
    setSuccess("");

    if (!dbName || !dbFile) {
      setErr("Database name and FASTA file are required.");
      return;
    }

    try {
      const formData = new FormData();

      formData.append("name", dbName);
      formData.append("description", dbDescription);
      formData.append("database_type", dbType);
      formData.append("source_fasta", dbFile);

      await apiPostForm("/api/blast-databases/", formData);

      setDbName("");
      setDbDescription("");
      setDbType("DNA");
      setDbFile(null);
      setSuccess("BLAST database uploaded. Click Build to make it searchable.");

      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function buildDatabase(id) {
    setErr("");
    setSuccess("");

    try {
      await apiPost(`/api/blast-databases/${id}/build/`, {});
      setSuccess("BLAST database build queued.");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function createJob(e) {
    e.preventDefault();

    setErr("");
    setSuccess("");

    if (!querySequenceId || !databaseId) {
      setErr("Query sequence and BLAST database are required.");
      return;
    }

    try {
      const payload = {
        name: jobName || "BLAST search",
        query_sequence: Number(querySequenceId),
        database: Number(databaseId),
        program,
        max_target_seqs: Number(maxTargetSeqs),
        evalue,
      };

      if (projectId) {
        payload.project = Number(projectId);
      }

      const created = await apiPost("/api/blast-jobs/", payload);

      setSuccess("BLAST job queued.");
      setSelectedJobId(created.id);
      setJobName("");
      setQuerySequenceId("");
      setDatabaseId("");
      setProgram("blastn");
      setMaxTargetSeqs(25);
      setEvalue("10");
      setProjectId("");

      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  if (loading) {
    return (
      <div className="d-flex align-items-center gap-2">
        <Spinner animation="border" size="sm" />
        <span>Loading BLAST...</span>
      </div>
    );
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">BLAST</h1>
          <p className="page-subtitle">
            Build local BLAST databases and run sequence similarity searches
            from OpenLIMS sequence workspaces.
          </p>
        </div>

        <div className="inline-actions">
          <Badge bg="dark">{databases.length} databases</Badge>
          <Badge bg="dark">{jobs.length} jobs</Badge>
          <Button variant="outline-dark" size="sm" onClick={load}>
            Refresh
          </Button>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}
      {success && <Alert variant="success">{success}</Alert>}

      <Row className="g-4 mb-4">
        <Col lg={5}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Create BLAST Database</h5>

              <Form onSubmit={createDatabase}>
                <Form.Group className="mb-3">
                  <Form.Label>Name</Form.Label>
                  <Form.Control
                    value={dbName}
                    onChange={(e) => setDbName(e.target.value)}
                    placeholder="Demo DNA BLAST DB"
                  />
                </Form.Group>

                <Form.Group className="mb-3">
                  <Form.Label>Description</Form.Label>
                  <Form.Control
                    as="textarea"
                    rows={2}
                    value={dbDescription}
                    onChange={(e) => setDbDescription(e.target.value)}
                    placeholder="Small local reference database"
                  />
                </Form.Group>

                <Form.Group className="mb-3">
                  <Form.Label>Database Type</Form.Label>
                  <Form.Select
                    value={dbType}
                    onChange={(e) => setDbType(e.target.value)}
                  >
                    <option value="DNA">DNA</option>
                    <option value="PROTEIN">Protein</option>
                  </Form.Select>
                </Form.Group>

                <Form.Group className="mb-3">
                  <Form.Label>Source FASTA</Form.Label>
                  <Form.Control
                    type="file"
                    accept=".fasta,.fa,.fna,.faa,.txt"
                    onChange={(e) => setDbFile(e.target.files?.[0] || null)}
                  />
                  <div className="feed-meta mt-1">
                    Upload a FASTA file that will be indexed with makeblastdb.
                  </div>
                </Form.Group>

                <Button
                  type="submit"
                  variant="dark"
                  disabled={!dbName || !dbFile}
                >
                  Upload Database
                </Button>
              </Form>
            </Card.Body>
          </Card>
        </Col>

        <Col lg={7}>
          <Card className="app-card h-100">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">BLAST Databases</h5>
                <Badge bg="dark">{databases.length}</Badge>
              </div>

              {databases.length === 0 ? (
                <div className="empty-state">
                  No BLAST databases have been uploaded yet.
                </div>
              ) : (
                <Table responsive hover className="app-table align-middle">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Type</th>
                      <th>Status</th>
                      <th>Created</th>
                      <th></th>
                    </tr>
                  </thead>

                  <tbody>
                    {databases.map((database) => (
                      <tr key={database.id}>
                        <td>
                          <div className="fw-semibold">{database.name}</div>
                          <div className="feed-meta">
                            {database.description || "-"}
                          </div>
                        </td>

                        <td>{database.database_type}</td>

                        <td>
                          <Badge bg={statusVariant(database.status)}>
                            {database.status}
                          </Badge>
                        </td>

                        <td>{formatTimestamp(database.created_at)}</td>

                        <td>
                          <Button
                            size="sm"
                            variant="outline-dark"
                            onClick={() => buildDatabase(database.id)}
                            disabled={database.status === "BUILDING"}
                          >
                            {database.status === "READY"
                              ? "Rebuild"
                              : "Build"}
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="g-4 mb-4">
        <Col lg={5}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Run BLAST Search</h5>

              <Form onSubmit={createJob}>
                <Form.Group className="mb-3">
                  <Form.Label>Query Sequence</Form.Label>
                  <Form.Select
                    value={querySequenceId}
                    onChange={(e) => setQuerySequenceId(e.target.value)}
                  >
                    <option value="">Select sequence...</option>

                    {sequences.map((sequence) => (
                      <option key={sequence.id} value={sequence.id}>
                        {sequence.name} ({sequence.sequence_type}){" "}
                        {sequence.project_code
                          ? `— ${sequence.project_code}`
                          : ""}
                      </option>
                    ))}
                  </Form.Select>
                </Form.Group>

                <Form.Group className="mb-3">
                  <Form.Label>BLAST Database</Form.Label>
                  <Form.Select
                    value={databaseId}
                    onChange={(e) => setDatabaseId(e.target.value)}
                  >
                    <option value="">Select ready database...</option>

                    {readyDatabases.map((database) => (
                      <option key={database.id} value={database.id}>
                        {database.name} ({database.database_type})
                      </option>
                    ))}
                  </Form.Select>

                  {readyDatabases.length === 0 && (
                    <div className="feed-meta mt-1">
                      No ready BLAST databases. Upload and build one first.
                    </div>
                  )}
                </Form.Group>

                <Form.Group className="mb-3">
                  <Form.Label>Job Name</Form.Label>
                  <Form.Control
                    value={jobName}
                    onChange={(e) => setJobName(e.target.value)}
                    placeholder="Demo BLAST search"
                  />
                </Form.Group>

                <Row className="g-2">
                  <Col md={6}>
                    <Form.Group className="mb-3">
                      <Form.Label>Program</Form.Label>
                      <Form.Select
                        value={program}
                        onChange={(e) => setProgram(e.target.value)}
                      >
                        <option value="blastn">blastn</option>
                        <option value="blastp">blastp</option>
                      </Form.Select>
                    </Form.Group>
                  </Col>

                  <Col md={6}>
                    <Form.Group className="mb-3">
                      <Form.Label>Project</Form.Label>
                      <Form.Select
                        value={projectId}
                        onChange={(e) => setProjectId(e.target.value)}
                      >
                        <option value="">Auto / none</option>

                        {projects.map((project) => (
                          <option key={project.id} value={project.id}>
                            {project.code} — {project.name}
                          </option>
                        ))}
                      </Form.Select>
                    </Form.Group>
                  </Col>
                </Row>

                <Row className="g-2">
                  <Col md={6}>
                    <Form.Group className="mb-3">
                      <Form.Label>Max Hits</Form.Label>
                      <Form.Control
                        type="number"
                        min="1"
                        max="100"
                        value={maxTargetSeqs}
                        onChange={(e) => setMaxTargetSeqs(e.target.value)}
                      />
                    </Form.Group>
                  </Col>

                  <Col md={6}>
                    <Form.Group className="mb-3">
                      <Form.Label>E-value</Form.Label>
                      <Form.Control
                        value={evalue}
                        onChange={(e) => setEvalue(e.target.value)}
                        placeholder="10"
                      />
                    </Form.Group>
                  </Col>
                </Row>

                <Button
                  type="submit"
                  variant="dark"
                  disabled={!querySequenceId || !databaseId}
                >
                  Run BLAST
                </Button>
              </Form>
            </Card.Body>
          </Card>
        </Col>

        <Col lg={7}>
          <Card className="app-card h-100">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">BLAST Jobs</h5>
                <Badge bg="dark">{jobs.length}</Badge>
              </div>

              {jobs.length === 0 ? (
                <div className="empty-state">No BLAST jobs yet.</div>
              ) : (
                <Table responsive hover className="app-table align-middle">
                  <thead>
                    <tr>
                      <th>Job</th>
                      <th>Query</th>
                      <th>Database</th>
                      <th>Status</th>
                      <th>Hits</th>
                    </tr>
                  </thead>

                  <tbody>
                    {jobs.map((job) => (
                      <tr
                        key={job.id}
                        role="button"
                        onClick={() => setSelectedJobId(job.id)}
                        className={
                          selectedJob?.id === job.id ? "table-active" : ""
                        }
                      >
                        <td>
                          <div className="fw-semibold">{job.name}</div>
                          <div className="feed-meta">
                            {formatTimestamp(job.created_at)}
                          </div>
                        </td>

                        <td>{job.query_sequence_name || job.query_sequence}</td>
                        <td>{job.database_name || job.database}</td>

                        <td>
                          <Badge bg={statusVariant(job.status)}>
                            {job.status}
                          </Badge>
                        </td>

                        <td>{job.hits_count ?? 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Card className="app-card">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">BLAST Results</h5>
              <div className="feed-meta">
                {selectedJob
                  ? `${selectedJob.name} · ${selectedJob.status}`
                  : "Select a BLAST job to view hits."}
              </div>
            </div>

            {selectedJob && (
              <Badge bg={statusVariant(selectedJob.status)}>
                {selectedJob.status}
              </Badge>
            )}
          </div>

          {!selectedJob ? (
            <div className="empty-state">No BLAST job selected.</div>
          ) : selectedJob.status === "FAILED" ? (
            <Alert variant="danger">
              {selectedJob.error_message || "BLAST job failed."}
            </Alert>
          ) : selectedJob.status !== "COMPLETED" ? (
            <Alert variant="info">
              BLAST job is {selectedJob.status}. Refresh to update results.
            </Alert>
          ) : !selectedJob.hits || selectedJob.hits.length === 0 ? (
            <div className="empty-state">No hits found.</div>
          ) : (
            <Table responsive hover className="app-table align-middle">
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Hit</th>
                  <th>Identity</th>
                  <th>E-value</th>
                  <th>Bit Score</th>
                  <th>Alignment</th>
                </tr>
              </thead>

              <tbody>
                {selectedJob.hits.map((hit) => (
                  <tr key={hit.id}>
                    <td>{hit.rank}</td>

                    <td>
                      <div className="fw-semibold">
                        {hit.accession || hit.hit_id || "Unknown hit"}
                      </div>
                      <div className="feed-meta">{hit.hit_def || "-"}</div>
                    </td>

                    <td>
                      {hit.identity_percent !== null &&
                      hit.identity_percent !== undefined
                        ? `${hit.identity_percent}%`
                        : "-"}
                    </td>

                    <td>{hit.evalue ?? "-"}</td>
                    <td>{hit.bit_score ?? "-"}</td>

                    <td>
                      <details>
                        <summary className="feed-meta">View alignment</summary>

                        <pre className="app-pre mt-2">
                          {`Query: ${hit.query_from || ""} ${
                            hit.query_aligned || ""
                          } ${hit.query_to || ""}

       ${hit.midline || ""}

Hit:   ${hit.hit_from || ""} ${
                            hit.hit_aligned || ""
                          } ${hit.hit_to || ""}`}
                        </pre>
                      </details>
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
