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

function parseFasta(value) {
  const records = [];
  let currentName = "";
  let currentLines = [];

  for (const rawLine of String(value || "").split(/\r?\n/)) {
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

export default function Alignments() {
  const [me, setMe] = useState(null);
  const [projects, setProjects] = useState([]);
  const [sequences, setSequences] = useState([]);
  const [jobs, setJobs] = useState([]);

  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedSequenceIds, setSelectedSequenceIds] = useState([]);
  const [name, setName] = useState("Alpha Clustal Omega Alignment");

  const [selectedJobId, setSelectedJobId] = useState("");
  const [err, setErr] = useState("");
  const [success, setSuccess] = useState("");
  const [running, setRunning] = useState(false);

  async function load() {
    setErr("");

    try {
      const [meData, projectsData, sequencesData, jobsData] = await Promise.all([
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
      setJobs(jobList);

      if (!selectedProjectId && projectList.length > 0) {
        setSelectedProjectId(String(projectList[0].id));
      }

      if (!selectedJobId && jobList.length > 0) {
        setSelectedJobId(String(jobList[0].id));
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
  const readOnlyText = readOnlyMessage(me);

  const filteredSequences = useMemo(() => {
    if (!selectedProjectId) return sequences;

    return sequences.filter(
      (sequence) => String(sequence.project) === String(selectedProjectId)
    );
  }, [sequences, selectedProjectId]);

  const selectedJob = useMemo(() => {
    return jobs.find((job) => String(job.id) === String(selectedJobId));
  }, [jobs, selectedJobId]);

  const alignmentRecords = useMemo(() => {
    return parseFasta(selectedJob?.aligned_fasta || "");
  }, [selectedJob]);

  const alignmentLength = useMemo(() => {
    if (alignmentRecords.length === 0) return 0;
    return Math.max(...alignmentRecords.map((record) => record.sequence.length));
  }, [alignmentRecords]);

  function toggleSequence(sequenceId) {
    const value = String(sequenceId);

    setSelectedSequenceIds((prev) =>
      prev.includes(value)
        ? prev.filter((item) => item !== value)
        : [...prev, value]
    );
  }

  async function runAlignment(e) {
    e.preventDefault();

    setErr("");
    setSuccess("");

    if (!userCanWrite) {
      setErr("Read-only access: you cannot run alignments.");
      return;
    }

    if (selectedSequenceIds.length < 2) {
      setErr("Select at least 2 sequences to align.");
      return;
    }

    setRunning(true);

    try {
      const payload = {
        name,
        project: selectedProjectId || null,
        sequence_ids: selectedSequenceIds.map((id) => Number(id)),
        tool: "CLUSTAL_OMEGA",
      };

      const created = await apiPost("/api/alignment-jobs/", payload);

      setSuccess(`Alignment completed: ${created.name}`);
      setSelectedJobId(String(created.id));
      setSelectedSequenceIds([]);

      await load();
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setRunning(false);
    }
  }

  function downloadAlignedFasta() {
    if (!selectedJob?.aligned_fasta) return;

    const safeName = selectedJob.name || `alignment-${selectedJob.id}`;

    downloadTextFile(
      `${safeName.replaceAll(" ", "_")}.aligned.fasta`,
      selectedJob.aligned_fasta,
      "text/plain"
    );
  }

  function downloadAlignmentJson() {
    if (!selectedJob) return;

    const safeName = selectedJob.name || `alignment-${selectedJob.id}`;

    downloadTextFile(
      `${safeName.replaceAll(" ", "_")}.alignment.json`,
      JSON.stringify(selectedJob, null, 2),
      "application/json"
    );
  }

  function openExternalViewer() {
    window.open("https://fast.alignmentviewer.org/", "_blank", "noreferrer");
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Alignments</h1>
          <p className="page-subtitle">
            Run Clustal Omega on saved sequence workspaces and review aligned
            FASTA output.
          </p>
        </div>

        <div className="inline-actions">
          <Button variant="outline-dark" size="sm" onClick={load}>
            Refresh
          </Button>

          <Button variant="outline-secondary" size="sm" onClick={openExternalViewer}>
            Open Fast AlignmentViewer
          </Button>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}
      {success && <Alert variant="success">{success}</Alert>}
      {readOnlyText && <Alert variant="info">{readOnlyText}</Alert>}

      <Row className="g-4 mb-4">
        <Col lg={5}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Create Alignment</h5>

              <Form onSubmit={runAlignment}>
                <Form.Group className="mb-3">
                  <Form.Label>Alignment Name</Form.Label>
                  <Form.Control
                    value={name}
                    onChange={(e) => setName(e.target.value)}
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

                <div className="toolbar-row mb-2">
                  <div className="feed-meta">Select sequences</div>
                  <Badge bg="dark">{selectedSequenceIds.length} selected</Badge>
                </div>

                <div
                  className="d-grid gap-2 mb-3"
                  style={{ maxHeight: "420px", overflowY: "auto" }}
                >
                  {filteredSequences.length === 0 ? (
                    <div className="empty-state">
                      No sequences found for this project.
                    </div>
                  ) : (
                    filteredSequences.map((sequence) => {
                      const checked = selectedSequenceIds.includes(
                        String(sequence.id)
                      );

                      return (
                        <div key={sequence.id} className="soft-card">
                          <Form.Check
                            type="checkbox"
                            checked={checked}
                            disabled={!userCanWrite}
                            onChange={() => toggleSequence(sequence.id)}
                            label={
                              <span>
                                <span className="fw-semibold">
                                  {sequence.name}
                                </span>
                                <span className="text-muted small d-block">
                                  {sequence.sample_code || "No sample"} ·{" "}
                                  {sequence.sequence_type} ·{" "}
                                  {sequence.sequence?.length ?? 0} bp
                                </span>
                              </span>
                            }
                          />
                        </div>
                      );
                    })
                  )}
                </div>

                <Button
                  type="submit"
                  variant="dark"
                  className="w-100"
                  disabled={
                    !userCanWrite ||
                    running ||
                    !name ||
                    selectedSequenceIds.length < 2
                  }
                >
                  {running ? "Running Clustal Omega..." : "Run Clustal Omega"}
                </Button>
              </Form>
            </Card.Body>
          </Card>
        </Col>

        <Col lg={7}>
          <Card className="app-card h-100">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">Alignment Jobs</h5>
                <Badge bg="dark">{jobs.length}</Badge>
              </div>

              {jobs.length === 0 ? (
                <div className="empty-state">No alignment jobs yet.</div>
              ) : (
                <Table responsive hover className="app-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Status</th>
                      <th>Tool</th>
                      <th>Sequences</th>
                      <th>Created</th>
                      <th></th>
                    </tr>
                  </thead>

                  <tbody>
                    {jobs.map((job) => (
                      <tr key={job.id}>
                        <td className="fw-semibold">{job.name}</td>
                        <td>
                          <Badge
                            bg={
                              job.status === "COMPLETED"
                                ? "success"
                                : job.status === "FAILED"
                                ? "danger"
                                : "warning"
                            }
                          >
                            {job.status}
                          </Badge>
                        </td>
                        <td>{job.tool}</td>
                        <td>{job.sequence_count}</td>
                        <td>{formatTimestamp(job.created_at)}</td>
                        <td>
                          <Button
                            size="sm"
                            variant="outline-dark"
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

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Alignment Result</h5>
              <div className="feed-meta">
                {selectedJob
                  ? `${selectedJob.name} · ${alignmentRecords.length} sequences · ${alignmentLength} columns`
                  : "Select an alignment job to view results."}
              </div>
            </div>

            <div className="inline-actions">
              <Button
                variant="outline-dark"
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

          {!selectedJob ? (
            <div className="empty-state">No alignment selected.</div>
          ) : selectedJob.status === "FAILED" ? (
            <Alert variant="danger">
              {selectedJob.error_message || "Alignment failed."}
            </Alert>
          ) : alignmentRecords.length === 0 ? (
            <div className="empty-state">No aligned FASTA available yet.</div>
          ) : (
            <div
              style={{
                overflowX: "auto",
                border: "1px solid #e5e7eb",
                borderRadius: "14px",
                padding: "14px",
                background: "#ffffff",
              }}
            >
              <Table responsive hover className="app-table mb-0">
                <thead>
                  <tr>
                    <th style={{ minWidth: "220px" }}>Sequence</th>
                    <th>Aligned FASTA</th>
                  </tr>
                </thead>

                <tbody>
                  {alignmentRecords.map((record, index) => (
                    <tr key={`${record.name}-${index}`}>
                      <td className="fw-semibold">{record.name}</td>
                      <td>
                        <code
                          style={{
                            whiteSpace: "pre",
                            fontFamily:
                              "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
                          }}
                        >
                          {record.sequence}
                        </code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          )}
        </Card.Body>
      </Card>

      <Card className="app-card">
        <Card.Body>
          <h5 className="section-title">Fast AlignmentViewer</h5>
          <p className="text-muted">
            Use the download button above to download aligned FASTA, then open it
            in the external AlignmentViewer if you want a dedicated interactive
            visualization.
          </p>

          <div
            style={{
              height: "520px",
              border: "1px solid #e5e7eb",
              borderRadius: "14px",
              overflow: "hidden",
              background: "#ffffff",
            }}
          >
            <iframe
              title="Fast AlignmentViewer"
              src="https://fast.alignmentviewer.org/"
              style={{
                border: 0,
                width: "100%",
                height: "100%",
              }}
            />
          </div>
        </Card.Body>
      </Card>
    </div>
  );
}
