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
import { apiGet, apiPost } from "../api";
import { canWrite, readOnlyMessage } from "../authz";

function formatTimestamp(ts) {
  if (!ts) return "-";

  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function downloadTextFile(filename, content, mimeType = "text/plain") {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = filename;
  link.click();

  URL.revokeObjectURL(url);
}

function safeFilename(value) {
  return String(value || "openlims-alignment")
    .trim()
    .replaceAll(" ", "_")
    .replace(/[^a-zA-Z0-9_.-]/g, "");
}

function parseFastaRecords(fastaText) {
  const records = [];
  let currentName = "";
  let currentLines = [];

  for (const rawLine of String(fastaText || "").split(/\r?\n/)) {
    const line = rawLine.trim();

    if (!line) continue;

    if (line.startsWith(">")) {
      if (currentName) {
        records.push({
          name: currentName,
          sequence: currentLines.join("").toUpperCase(),
        });
      }

      currentName = line.slice(1).trim();
      currentLines = [];
    } else {
      currentLines.push(line);
    }
  }

  if (currentName) {
    records.push({
      name: currentName,
      sequence: currentLines.join("").toUpperCase(),
    });
  }

  return records;
}

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

function baseStyle(base) {
  const upper = String(base || "").toUpperCase();

  const styles = {
    A: { background: "#fee2e2", color: "#991b1b" },
    T: { background: "#dbeafe", color: "#1e3a8a" },
    U: { background: "#dbeafe", color: "#1e3a8a" },
    G: { background: "#dcfce7", color: "#166534" },
    C: { background: "#fef3c7", color: "#92400e" },
    "-": { background: "#f3f4f6", color: "#6b7280" },
    N: { background: "#ede9fe", color: "#5b21b6" },
  };

  return (
    styles[upper] || {
      background: "#f8fafc",
      color: "#111827",
    }
  );
}

function chunkSequence(sequence, chunkSize = 80) {
  const chunks = [];

  for (let i = 0; i < sequence.length; i += chunkSize) {
    chunks.push({
      start: i,
      end: Math.min(i + chunkSize, sequence.length),
      text: sequence.slice(i, i + chunkSize),
    });
  }

  return chunks;
}

function AlignmentGrid({ records }) {
  if (records.length === 0) {
    return <div className="empty-state">No aligned FASTA records found.</div>;
  }

  const maxLength = Math.max(...records.map((record) => record.sequence.length));
  const chunks = chunkSequence("X".repeat(maxLength), 80);

  return (
    <div className="d-grid gap-4">
      {chunks.map((chunk) => (
        <div key={`${chunk.start}-${chunk.end}`} className="soft-card">
          <div className="feed-meta mb-2">
            Columns {chunk.start + 1}–{chunk.end}
          </div>

          <div style={{ overflowX: "auto" }}>
            <Table responsive className="app-table mb-0">
              <tbody>
                {records.map((record, rowIndex) => {
                  const sequenceChunk = record.sequence
                    .padEnd(maxLength, "-")
                    .slice(chunk.start, chunk.end);

                  return (
                    <tr key={`${record.name}-${rowIndex}-${chunk.start}`}>
                      <td
                        className="fw-semibold"
                        style={{
                          minWidth: "220px",
                          maxWidth: "220px",
                          whiteSpace: "nowrap",
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          verticalAlign: "top",
                        }}
                        title={record.name}
                      >
                        {record.name}
                      </td>

                      <td>
                        <div
                          style={{
                            display: "grid",
                            gridTemplateColumns: `repeat(${sequenceChunk.length}, 18px)`,
                            gap: "2px",
                            fontFamily:
                              "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                            fontSize: "0.75rem",
                          }}
                        >
                          {sequenceChunk.split("").map((base, index) => {
                            const style = baseStyle(base);

                            return (
                              <span
                                key={`${record.name}-${chunk.start}-${index}`}
                                title={`Column ${chunk.start + index + 1}: ${base}`}
                                style={{
                                  ...style,
                                  width: "18px",
                                  height: "22px",
                                  display: "inline-flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                  borderRadius: "4px",
                                  fontWeight: 700,
                                }}
                              >
                                {base}
                              </span>
                            );
                          })}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function Alignments() {
  const [me, setMe] = useState(null);
  const [projects, setProjects] = useState([]);
  const [sequences, setSequences] = useState([]);
  const [alignmentJobs, setAlignmentJobs] = useState([]);

  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedSequenceIds, setSelectedSequenceIds] = useState([]);
  const [selectedJobId, setSelectedJobId] = useState("");

  const [alignmentName, setAlignmentName] = useState(
    "OpenLIMS Clustal Omega Alignment"
  );
  const [err, setErr] = useState("");
  const [success, setSuccess] = useState("");
  const [running, setRunning] = useState(false);
  const [loading, setLoading] = useState(false);

  async function load() {
    setErr("");
    setLoading(true);

    try {
      const [meData, projectsData, sequencesData, jobsData] =
        await Promise.all([
          apiGet("/api/me/"),
          apiGet("/api/projects/"),
          apiGet("/api/sequences/"),
          apiGet("/api/alignment-jobs/"),
        ]);

      const projectList = projectsData.results || projectsData || [];
      const sequenceList = sequencesData.results || sequencesData || [];
      const jobList = jobsData.results || jobsData || [];

      setMe(meData);
      setProjects(projectList);
      setSequences(sequenceList);
      setAlignmentJobs(jobList);

      if (!selectedProjectId && projectList.length > 0) {
        setSelectedProjectId(String(projectList[0].id));
      }

      if (!selectedJobId && jobList.length > 0) {
        setSelectedJobId(String(jobList[0].id));
      }
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const userCanWrite = canWrite(me);
  const readOnlyText = readOnlyMessage(me);

  const filteredSequences = useMemo(() => {
    if (!selectedProjectId) return sequences;

    return sequences.filter(
      (sequence) => String(sequence.project) === String(selectedProjectId)
    );
  }, [sequences, selectedProjectId]);

  const selectedProject = useMemo(() => {
    return projects.find(
      (project) => String(project.id) === String(selectedProjectId)
    );
  }, [projects, selectedProjectId]);

  const selectedJob = useMemo(() => {
    return alignmentJobs.find((job) => String(job.id) === String(selectedJobId));
  }, [alignmentJobs, selectedJobId]);

  const alignmentRecords = useMemo(() => {
    return parseFastaRecords(selectedJob?.aligned_fasta || "");
  }, [selectedJob]);

  const alignmentColumns = useMemo(() => {
    if (alignmentRecords.length === 0) return 0;

    return Math.max(...alignmentRecords.map((record) => record.sequence.length));
  }, [alignmentRecords]);

  function toggleSequence(sequenceId) {
    const id = String(sequenceId);

    setSelectedSequenceIds((prev) =>
      prev.includes(id)
        ? prev.filter((currentId) => currentId !== id)
        : [...prev, id]
    );
  }

  function selectAllVisibleSequences() {
    setSelectedSequenceIds(
      filteredSequences.map((sequence) => String(sequence.id))
    );
  }

  function clearSelectedSequences() {
    setSelectedSequenceIds([]);
  }

  async function runAlignment(e) {
    e.preventDefault();

    setErr("");
    setSuccess("");

    if (!userCanWrite) {
      setErr("Read-only access: you cannot run sequence alignments.");
      return;
    }

    if (selectedSequenceIds.length < 2) {
      setErr("Select at least 2 sequence workspaces to run an alignment.");
      return;
    }

    setRunning(true);

    try {
      const payload = {
        name: alignmentName,
        project: selectedProjectId || null,
        sequence_ids: selectedSequenceIds.map((id) => Number(id)),
        tool: "CLUSTAL_OMEGA",
      };

      const createdJob = await apiPost("/api/alignment-jobs/", payload);

      setSuccess(`Alignment "${createdJob.name}" completed.`);
      setSelectedJobId(String(createdJob.id));

      await load();
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setRunning(false);
    }
  }

  function downloadAlignedFasta() {
    if (!selectedJob?.aligned_fasta) return;

    downloadTextFile(
      `${safeFilename(selectedJob.name)}.aligned.fasta`,
      selectedJob.aligned_fasta,
      "text/plain"
    );
  }

  function downloadAlignmentJson() {
    if (!selectedJob) return;

    downloadTextFile(
      `${safeFilename(selectedJob.name)}.alignment.json`,
      JSON.stringify(selectedJob, null, 2),
      "application/json"
    );
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Alignments</h1>
          <p className="page-subtitle">
            Run Clustal Omega alignments and view aligned FASTA in OpenLIMS.
          </p>
        </div>

        <div className="inline-actions">
          <Button variant="outline-dark" size="sm" onClick={load}>
            {loading ? "Refreshing..." : "Refresh"}
          </Button>

          <Button
            variant="outline-primary"
            size="sm"
            onClick={downloadAlignedFasta}
            disabled={!selectedJob?.aligned_fasta}
          >
            Download FASTA
          </Button>

          <Button
            variant="outline-secondary"
            size="sm"
            onClick={downloadAlignmentJson}
            disabled={!selectedJob}
          >
            Download JSON
          </Button>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}
      {success && <Alert variant="success">{success}</Alert>}
      {readOnlyText && <Alert variant="info">{readOnlyText}</Alert>}

      <Row className="g-4 mb-4">
        <Col lg={4}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Create Alignment</h5>

              <Form onSubmit={runAlignment}>
                <Form.Group className="mb-3">
                  <Form.Label>Alignment Name</Form.Label>
                  <Form.Control
                    value={alignmentName}
                    onChange={(e) => setAlignmentName(e.target.value)}
                    disabled={!userCanWrite}
                  />
                </Form.Group>

                <Form.Group className="mb-3">
                  <Form.Label>Project</Form.Label>
                  <Form.Select
                    value={selectedProjectId}
                    onChange={(e) => {
                      setSelectedProjectId(e.target.value);
                      setSelectedSequenceIds([]);
                    }}
                  >
                    <option value="">All projects</option>

                    {projects.map((project) => (
                      <option key={project.id} value={project.id}>
                        {project.code} — {project.name}
                      </option>
                    ))}
                  </Form.Select>
                </Form.Group>

                <div className="d-flex justify-content-between align-items-center mb-2">
                  <Form.Label className="mb-0">Sequence Workspaces</Form.Label>

                  <div className="d-flex gap-2">
                    <Button
                      type="button"
                      variant="outline-secondary"
                      size="sm"
                      onClick={selectAllVisibleSequences}
                      disabled={!userCanWrite || filteredSequences.length === 0}
                    >
                      Select All
                    </Button>

                    <Button
                      type="button"
                      variant="outline-secondary"
                      size="sm"
                      onClick={clearSelectedSequences}
                      disabled={!userCanWrite}
                    >
                      Clear
                    </Button>
                  </div>
                </div>

                <div
                  className="soft-card mb-3"
                  style={{ maxHeight: "360px", overflowY: "auto" }}
                >
                  {filteredSequences.length === 0 ? (
                    <div className="empty-state">
                      No sequence workspaces found for this project.
                    </div>
                  ) : (
                    <div className="d-grid gap-2">
                      {filteredSequences.map((sequence) => (
                        <Form.Check
                          key={sequence.id}
                          type="checkbox"
                          id={`sequence-${sequence.id}`}
                          label={`${sequence.name} (${sequence.sequence_type}, ${
                            sequence.sequence?.length ?? 0
                          } bp)`}
                          checked={selectedSequenceIds.includes(
                            String(sequence.id)
                          )}
                          disabled={!userCanWrite}
                          onChange={() => toggleSequence(sequence.id)}
                        />
                      ))}
                    </div>
                  )}
                </div>

                <Button
                  type="submit"
                  variant="dark"
                  className="w-100"
                  disabled={
                    !userCanWrite ||
                    running ||
                    !alignmentName ||
                    selectedSequenceIds.length < 2
                  }
                >
                  {running
                    ? "Running Clustal Omega..."
                    : `Run Clustal Omega (${selectedSequenceIds.length})`}
                </Button>
              </Form>
            </Card.Body>
          </Card>
        </Col>

        <Col lg={8}>
          <Card className="app-card h-100">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <div>
                  <h5 className="section-title mb-0">Alignment Jobs</h5>
                  <div className="feed-meta">
                    Previous Clustal Omega alignment runs.
                  </div>
                </div>

                <Badge bg="dark">{alignmentJobs.length}</Badge>
              </div>

              {alignmentJobs.length === 0 ? (
                <div className="empty-state">No alignment jobs yet.</div>
              ) : (
                <Table responsive hover className="app-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Project</th>
                      <th>Status</th>
                      <th>Tool</th>
                      <th>Created</th>
                      <th></th>
                    </tr>
                  </thead>

                  <tbody>
                    {alignmentJobs.map((job) => (
                      <tr key={job.id}>
                        <td className="fw-semibold">{job.name}</td>
                        <td>{job.project_code || selectedProject?.code || "-"}</td>
                        <td>
                          <Badge bg={statusVariant(job.status)}>
                            {job.status}
                          </Badge>
                        </td>
                        <td>{job.tool || "CLUSTAL_OMEGA"}</td>
                        <td>{formatTimestamp(job.created_at)}</td>
                        <td>
                          <Button
                            variant={
                              String(selectedJobId) === String(job.id)
                                ? "dark"
                                : "outline-dark"
                            }
                            size="sm"
                            onClick={() => setSelectedJobId(String(job.id))}
                          >
                            View
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

      <div className="stat-grid mb-4">
        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Selected Sequences</div>
            <div className="metric-value">{selectedSequenceIds.length}</div>
            <div className="metric-note">Used for new alignment</div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Aligned Records</div>
            <div className="metric-value">{alignmentRecords.length}</div>
            <div className="metric-note">Records in selected result</div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Alignment Columns</div>
            <div className="metric-value">{alignmentColumns}</div>
            <div className="metric-note">Longest aligned sequence</div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Viewer</div>
            <div className="metric-value" style={{ fontSize: "1.4rem" }}>
              OpenLIMS
            </div>
            <div className="metric-note">Color-coded alignment grid</div>
          </Card.Body>
        </Card>
      </div>

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Alignment Preview</h5>
              <div className="feed-meta">
                Color-coded alignment grid generated from Clustal Omega output.
              </div>
            </div>

            {selectedJob && (
              <Badge bg={statusVariant(selectedJob.status)}>
                {selectedJob.status}
              </Badge>
            )}
          </div>

          {!selectedJob ? (
            <div className="empty-state">Select an alignment job to view.</div>
          ) : selectedJob.status === "FAILED" ? (
            <Alert variant="danger">
              {selectedJob.error_message || "Alignment failed."}
            </Alert>
          ) : !selectedJob.aligned_fasta ? (
            <div className="empty-state">
              This job does not have aligned FASTA output yet.
            </div>
          ) : (
            <AlignmentGrid records={alignmentRecords} />
          )}
        </Card.Body>
      </Card>

      <Card className="app-card">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Aligned FASTA</h5>
              <div className="feed-meta">
                Raw aligned FASTA returned by Clustal Omega.
              </div>
            </div>
          </div>

          {!selectedJob?.aligned_fasta ? (
            <div className="empty-state">No aligned FASTA selected.</div>
          ) : (
            <pre className="app-pre">{selectedJob.aligned_fasta}</pre>
          )}
        </Card.Body>
      </Card>
    </div>
  );
}