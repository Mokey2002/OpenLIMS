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
import { apiGet } from "../api";

function formatTimestamp(value) {
  if (!value) return "-";

  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function csvEscape(value) {
  if (value === null || value === undefined) return "";

  const stringValue = String(value);

  if (
    stringValue.includes(",") ||
    stringValue.includes('"') ||
    stringValue.includes("\n")
  ) {
    return `"${stringValue.replaceAll('"', '""')}"`;
  }

  return stringValue;
}

function downloadCsv(filename, headers, rows) {
  const csv = [
    headers.map(csvEscape).join(","),
    ...rows.map((row) => headers.map((header) => csvEscape(row[header])).join(",")),
  ].join("\n");

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = url;
  link.download = filename;
  link.click();

  URL.revokeObjectURL(url);
}

function statusVariant(status) {
  switch (status) {
    case "READY":
    case "COMPLETED":
    case "APPROVED":
    case "REPORTED":
      return "success";
    case "FAILED":
    case "REJECTED":
      return "danger";
    case "BUILDING":
    case "RUNNING":
    case "IN_PROGRESS":
      return "primary";
    case "NEW":
    case "PENDING":
    case "QC":
    case "RERUN_REQUIRED":
      return "warning";
    case "ARCHIVED":
      return "dark";
    default:
      return "secondary";
  }
}

function countBy(items, getter) {
  return items.reduce((acc, item) => {
    const key = getter(item) || "Unknown";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
}

function getProjectId(value) {
  if (value === null || value === undefined) return "";

  if (typeof value === "object") {
    return value.id || "";
  }

  return value;
}

function getProjectCode(value) {
  if (!value) return "";

  if (typeof value === "object") {
    return value.code || value.name || "";
  }

  return "";
}

export default function Reports() {
  const [projects, setProjects] = useState([]);
  const [samples, setSamples] = useState([]);
  const [workItems, setWorkItems] = useState([]);
  const [imports, setImports] = useState([]);
  const [alignments, setAlignments] = useState([]);
  const [blastDatabases, setBlastDatabases] = useState([]);
  const [blastJobs, setBlastJobs] = useState([]);
  const [events, setEvents] = useState([]);

  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  async function load() {
    setErr("");
    setLoading(true);

    try {
      const [
        projectsData,
        samplesData,
        workItemsData,
        importsData,
        alignmentsData,
        blastDatabasesData,
        blastJobsData,
        eventsData,
      ] = await Promise.all([
        apiGet("/api/projects/"),
        apiGet("/api/samples/"),
        apiGet("/api/work-items/"),
        apiGet("/api/import-jobs/"),
        apiGet("/api/alignment-jobs/"),
        apiGet("/api/blast-databases/"),
        apiGet("/api/blast-jobs/"),
        apiGet("/api/events/"),
      ]);

      setProjects(projectsData.results || projectsData || []);
      setSamples(samplesData.results || samplesData || []);
      setWorkItems(workItemsData.results || workItemsData || []);
      setImports(importsData.results || importsData || []);
      setAlignments(alignmentsData.results || alignmentsData || []);
      setBlastDatabases(blastDatabasesData.results || blastDatabasesData || []);
      setBlastJobs(blastJobsData.results || blastJobsData || []);
      setEvents(eventsData.results || eventsData || []);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const filteredSamples = useMemo(() => {
    if (!selectedProjectId) return samples;

    return samples.filter(
      (sample) => String(sample.project) === String(selectedProjectId)
    );
  }, [samples, selectedProjectId]);

  const filteredWorkItems = useMemo(() => {
    const sampleIds = new Set(filteredSamples.map((sample) => sample.id));
    return workItems.filter((item) => sampleIds.has(item.sample));
  }, [workItems, filteredSamples]);

  const filteredImports = useMemo(() => {
    if (!selectedProjectId) return imports;

    return imports.filter((job) => String(job.project) === String(selectedProjectId));
  }, [imports, selectedProjectId]);

  const filteredAlignments = useMemo(() => {
    if (!selectedProjectId) return alignments;

    return alignments.filter(
      (job) => String(job.project) === String(selectedProjectId)
    );
  }, [alignments, selectedProjectId]);

  const filteredBlastJobs = useMemo(() => {
    if (!selectedProjectId) return blastJobs;

    return blastJobs.filter((job) => {
      const projectId =
        job.project_id ||
        job.project ||
        getProjectId(job.project_detail) ||
        getProjectId(job.project_obj);

      return String(projectId) === String(selectedProjectId);
    });
  }, [blastJobs, selectedProjectId]);

  const filteredEvents = useMemo(() => {
    if (!selectedProjectId) return events;

    const selectedProject = projects.find(
      (project) => String(project.id) === String(selectedProjectId)
    );

    return events.filter((event) => {
      const payload = event.payload || {};

      return (
        String(payload.project_id) === String(selectedProjectId) ||
        String(payload.project) === String(selectedProjectId) ||
        payload.project_code === selectedProject?.code ||
        (event.entity_type === "Project" &&
          String(event.entity_id) === String(selectedProjectId))
      );
    });
  }, [events, projects, selectedProjectId]);

  const sampleStatusCounts = useMemo(() => {
    return countBy(filteredSamples, (sample) => sample.status);
  }, [filteredSamples]);

  const qcCounts = useMemo(() => {
    return countBy(filteredWorkItems, (item) => item.qc_status);
  }, [filteredWorkItems]);

  const importStatusCounts = useMemo(() => {
    return countBy(filteredImports, (job) => job.status);
  }, [filteredImports]);

  const alignmentStatusCounts = useMemo(() => {
    return countBy(filteredAlignments, (job) => job.status);
  }, [filteredAlignments]);

  const blastDatabaseStatusCounts = useMemo(() => {
    return countBy(blastDatabases, (database) => database.status);
  }, [blastDatabases]);

  const blastJobStatusCounts = useMemo(() => {
    return countBy(filteredBlastJobs, (job) => job.status);
  }, [filteredBlastJobs]);

  const totalBlastHits = useMemo(() => {
    return filteredBlastJobs.reduce(
      (total, job) => total + Number(job.hits_count || 0),
      0
    );
  }, [filteredBlastJobs]);

  const recentBlastJobs = useMemo(() => {
    return [...filteredBlastJobs]
      .sort(
        (a, b) =>
          new Date(b.created_at || b.updated_at) -
          new Date(a.created_at || a.updated_at)
      )
      .slice(0, 10);
  }, [filteredBlastJobs]);

  const recentEvents = useMemo(() => {
    return [...filteredEvents]
      .sort(
        (a, b) =>
          new Date(b.timestamp || b.created_at) -
          new Date(a.timestamp || a.created_at)
      )
      .slice(0, 10);
  }, [filteredEvents]);

  function exportProjectSummary() {
    const rows = projects.map((project) => {
      const projectSamples = samples.filter(
        (sample) => String(sample.project) === String(project.id)
      );

      const projectImports = imports.filter(
        (job) => String(job.project) === String(project.id)
      );

      const projectAlignments = alignments.filter(
        (job) => String(job.project) === String(project.id)
      );

      const projectBlastJobs = blastJobs.filter((job) => {
        const projectId =
          job.project_id ||
          job.project ||
          getProjectId(job.project_detail) ||
          getProjectId(job.project_obj);

        return String(projectId) === String(project.id);
      });

      return {
        project_id: project.id,
        code: project.code,
        name: project.name,
        sample_count: projectSamples.length,
        import_count: projectImports.length,
        alignment_count: projectAlignments.length,
        blast_job_count: projectBlastJobs.length,
        blast_hit_count: projectBlastJobs.reduce(
          (total, job) => total + Number(job.hits_count || 0),
          0
        ),
        members: (project.member_usernames || []).join("; "),
        created_at: project.created_at,
      };
    });

    downloadCsv(
      "openlims-project-summary.csv",
      [
        "project_id",
        "code",
        "name",
        "sample_count",
        "import_count",
        "alignment_count",
        "blast_job_count",
        "blast_hit_count",
        "members",
        "created_at",
      ],
      rows
    );
  }

  function exportSampleInventory() {
    const rows = filteredSamples.map((sample) => ({
      id: sample.id,
      sample_id: sample.sample_id,
      status: sample.status,
      project_code: sample.project_code,
      project_name: sample.project_name,
      container_code: sample.container_code,
      location_name: sample.location_name,
      created_at: sample.created_at,
    }));

    downloadCsv(
      "openlims-sample-inventory.csv",
      [
        "id",
        "sample_id",
        "status",
        "project_code",
        "project_name",
        "container_code",
        "location_name",
        "created_at",
      ],
      rows
    );
  }

  function exportQcReview() {
    const rows = filteredWorkItems.map((item) => ({
      id: item.id,
      sample_id: item.sample,
      name: item.name,
      status: item.status,
      qc_status: item.qc_status,
      reviewed_by: item.reviewed_by_username,
      reviewed_at: item.reviewed_at,
      review_note: item.review_note,
      created_at: item.created_at,
    }));

    downloadCsv(
      "openlims-qc-review-report.csv",
      [
        "id",
        "sample_id",
        "name",
        "status",
        "qc_status",
        "reviewed_by",
        "reviewed_at",
        "review_note",
        "created_at",
      ],
      rows
    );
  }

  function exportImportSummary() {
    const rows = filteredImports.map((job) => ({
      id: job.id,
      instrument_code: job.instrument_code,
      instrument_name: job.instrument_name,
      project_code: job.project_code,
      run_id: job.run_id,
      status: job.status,
      source_type: job.source_type,
      progress_percent: job.progress_percent,
      created_at: job.created_at,
    }));

    downloadCsv(
      "openlims-import-summary.csv",
      [
        "id",
        "instrument_code",
        "instrument_name",
        "project_code",
        "run_id",
        "status",
        "source_type",
        "progress_percent",
        "created_at",
      ],
      rows
    );
  }

  function exportAlignmentSummary() {
    const rows = filteredAlignments.map((job) => ({
      id: job.id,
      name: job.name,
      project_code: job.project_code,
      tool: job.tool,
      status: job.status,
      sequence_count: job.sequence_count,
      created_by: job.created_by_username,
      created_at: job.created_at,
      updated_at: job.updated_at,
    }));

    downloadCsv(
      "openlims-alignment-summary.csv",
      [
        "id",
        "name",
        "project_code",
        "tool",
        "status",
        "sequence_count",
        "created_by",
        "created_at",
        "updated_at",
      ],
      rows
    );
  }

  function exportBlastSummary() {
    const rows = filteredBlastJobs.map((job) => ({
      id: job.id,
      name: job.name,
      project_id:
        job.project_id ||
        job.project ||
        getProjectId(job.project_detail) ||
        getProjectId(job.project_obj),
      project_code:
        job.project_code ||
        getProjectCode(job.project_detail) ||
        getProjectCode(job.project_obj),
      program: job.program,
      status: job.status,
      query_sequence_id: job.query_sequence || job.query_sequence_id,
      query_sequence_name: job.query_sequence_name || job.query_name,
      database_id: job.database || job.database_id,
      database_name: job.database_name,
      hits_count: job.hits_count || 0,
      evalue: job.evalue,
      max_target_seqs: job.max_target_seqs,
      created_by: job.created_by_username,
      created_at: job.created_at,
      updated_at: job.updated_at,
    }));

    downloadCsv(
      "openlims-blast-summary.csv",
      [
        "id",
        "name",
        "project_id",
        "project_code",
        "program",
        "status",
        "query_sequence_id",
        "query_sequence_name",
        "database_id",
        "database_name",
        "hits_count",
        "evalue",
        "max_target_seqs",
        "created_by",
        "created_at",
        "updated_at",
      ],
      rows
    );
  }

  function exportAuditActivity() {
    const rows = filteredEvents.map((event) => ({
      id: event.id,
      timestamp: event.timestamp || event.created_at,
      actor: event.actor_username || event.actor,
      entity_type: event.entity_type,
      entity_id: event.entity_id,
      action: event.action,
      payload: JSON.stringify(event.payload || {}),
    }));

    downloadCsv(
      "openlims-audit-activity-report.csv",
      [
        "id",
        "timestamp",
        "actor",
        "entity_type",
        "entity_id",
        "action",
        "payload",
      ],
      rows
    );
  }

  if (loading) {
    return (
      <div className="d-flex align-items-center gap-2">
        <Spinner animation="border" size="sm" />
        <span>Loading reports...</span>
      </div>
    );
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Reports</h1>
          <p className="page-subtitle">
            Generate project, sample, QC, import, alignment, BLAST, and audit
            activity reports.
          </p>
        </div>

        <div className="inline-actions">
          <Button variant="outline-dark" size="sm" onClick={load}>
            Refresh
          </Button>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Report Scope</h5>

          <Row className="g-3">
            <Col md={6}>
              <Form.Group>
                <Form.Label>Project Filter</Form.Label>
                <Form.Select
                  value={selectedProjectId}
                  onChange={(e) => setSelectedProjectId(e.target.value)}
                >
                  <option value="">All projects</option>

                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.code} — {project.name}
                    </option>
                  ))}
                </Form.Select>
              </Form.Group>
            </Col>

            <Col md={6} className="d-flex align-items-end">
              <Alert variant="info" className="mb-0 w-100">
                Reports are generated from the current OpenLIMS data and can be
                exported as CSV.
              </Alert>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      <div className="stat-grid mb-4">
        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Samples</div>
            <div className="metric-value">{filteredSamples.length}</div>
            <div className="metric-note">Matching report scope</div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">QC Pending</div>
            <div className="metric-value">
              {qcCounts.PENDING_REVIEW || 0}
            </div>
            <div className="metric-note">
              Approved: {qcCounts.APPROVED || 0}
            </div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Imports</div>
            <div className="metric-value">{filteredImports.length}</div>
            <div className="metric-note">
              Failed: {importStatusCounts.FAILED || 0}
            </div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Alignments</div>
            <div className="metric-value">{filteredAlignments.length}</div>
            <div className="metric-note">
              Failed: {alignmentStatusCounts.FAILED || 0}
            </div>
          </Card.Body>
        </Card>
      </div>

      <Row className="g-4 mb-4">
        <Col lg={6}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Export Reports</h5>

              <div className="d-grid gap-2">
                <Button variant="outline-dark" onClick={exportProjectSummary}>
                  Export Project Summary CSV
                </Button>

                <Button variant="outline-dark" onClick={exportSampleInventory}>
                  Export Sample Inventory CSV
                </Button>

                <Button variant="outline-dark" onClick={exportQcReview}>
                  Export QC Review CSV
                </Button>

                <Button variant="outline-dark" onClick={exportImportSummary}>
                  Export Import Summary CSV
                </Button>

                <Button variant="outline-dark" onClick={exportAlignmentSummary}>
                  Export Alignment Summary CSV
                </Button>

                <Button variant="outline-dark" onClick={exportBlastSummary}>
                  Export BLAST Summary CSV
                </Button>

                <Button variant="outline-dark" onClick={exportAuditActivity}>
                  Export Audit Activity CSV
                </Button>
              </div>
            </Card.Body>
          </Card>
        </Col>

        <Col lg={6}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Sample Status Summary</h5>

              {Object.keys(sampleStatusCounts).length === 0 ? (
                <div className="empty-state">No samples found.</div>
              ) : (
                <div className="d-grid gap-2">
                  {Object.entries(sampleStatusCounts).map(([status, count]) => (
                    <div
                      key={status}
                      className="soft-card d-flex justify-content-between align-items-center"
                    >
                      <Badge bg={statusVariant(status)}>{status}</Badge>
                      <strong>{count}</strong>
                    </div>
                  ))}
                </div>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="g-4 mb-4">
        <Col lg={6}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">QC Review Summary</h5>

              {Object.keys(qcCounts).length === 0 ? (
                <div className="empty-state">No work items found.</div>
              ) : (
                <div className="d-grid gap-2">
                  {Object.entries(qcCounts).map(([status, count]) => (
                    <div
                      key={status}
                      className="soft-card d-flex justify-content-between align-items-center"
                    >
                      <Badge bg={statusVariant(status)}>{status}</Badge>
                      <strong>{count}</strong>
                    </div>
                  ))}
                </div>
              )}
            </Card.Body>
          </Card>
        </Col>

        <Col lg={6}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">BLAST Summary</h5>

              <Row className="g-3 mb-3">
                <Col sm={6}>
                  <div className="soft-card">
                    <div className="metric-label">BLAST Databases</div>
                    <div className="metric-value">{blastDatabases.length}</div>
                    <div className="metric-note">
                      Ready: {blastDatabaseStatusCounts.READY || 0}
                    </div>
                  </div>
                </Col>

                <Col sm={6}>
                  <div className="soft-card">
                    <div className="metric-label">BLAST Jobs</div>
                    <div className="metric-value">{filteredBlastJobs.length}</div>
                    <div className="metric-note">
                      Completed: {blastJobStatusCounts.COMPLETED || 0}
                    </div>
                  </div>
                </Col>

                <Col sm={6}>
                  <div className="soft-card">
                    <div className="metric-label">Failed Jobs</div>
                    <div className="metric-value">
                      {blastJobStatusCounts.FAILED || 0}
                    </div>
                    <div className="metric-note">
                      Running: {blastJobStatusCounts.RUNNING || 0}
                    </div>
                  </div>
                </Col>

                <Col sm={6}>
                  <div className="soft-card">
                    <div className="metric-label">BLAST Hits</div>
                    <div className="metric-value">{totalBlastHits}</div>
                    <div className="metric-note">Across matching jobs</div>
                  </div>
                </Col>
              </Row>

              {Object.keys(blastJobStatusCounts).length === 0 ? (
                <div className="empty-state">No BLAST jobs found.</div>
              ) : (
                <div className="d-grid gap-2">
                  {Object.entries(blastJobStatusCounts).map(([status, count]) => (
                    <div
                      key={status}
                      className="soft-card d-flex justify-content-between align-items-center"
                    >
                      <Badge bg={statusVariant(status)}>{status}</Badge>
                      <strong>{count}</strong>
                    </div>
                  ))}
                </div>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="g-4 mb-4">
        <Col lg={12}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Recent BLAST Jobs</h5>

              {recentBlastJobs.length === 0 ? (
                <div className="empty-state">No BLAST jobs found.</div>
              ) : (
                <Table responsive hover className="app-table">
                  <thead>
                    <tr>
                      <th>Job</th>
                      <th>Program</th>
                      <th>Query</th>
                      <th>Database</th>
                      <th>Status</th>
                      <th>Hits</th>
                      <th>Created</th>
                    </tr>
                  </thead>

                  <tbody>
                    {recentBlastJobs.map((job) => (
                      <tr key={job.id}>
                        <td>{job.name}</td>
                        <td>{job.program}</td>
                        <td>
                          {job.query_sequence_name ||
                            job.query_name ||
                            job.query_sequence ||
                            "-"}
                        </td>
                        <td>{job.database_name || job.database || "-"}</td>
                        <td>
                          <Badge bg={statusVariant(job.status)}>
                            {job.status}
                          </Badge>
                        </td>
                        <td>{job.hits_count || 0}</td>
                        <td>{formatTimestamp(job.created_at)}</td>
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
        <Col lg={12}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Recent Audit Activity</h5>

              {recentEvents.length === 0 ? (
                <div className="empty-state">No audit activity found.</div>
              ) : (
                <Table responsive hover className="app-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Actor</th>
                      <th>Entity</th>
                      <th>Action</th>
                    </tr>
                  </thead>

                  <tbody>
                    {recentEvents.map((event) => (
                      <tr key={event.id}>
                        <td>{formatTimestamp(event.timestamp || event.created_at)}</td>
                        <td>{event.actor_username || event.actor || "-"}</td>
                        <td>{event.entity_type}</td>
                        <td>
                          <Badge bg="secondary">{event.action}</Badge>
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
    </div>
  );
}