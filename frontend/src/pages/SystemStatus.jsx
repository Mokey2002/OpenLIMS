import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Row,
  Spinner,
  Table,
} from "react-bootstrap";
import { apiGet } from "../api";
import { isAdmin } from "../authz";

function formatTimestamp(value) {
  if (!value) return "-";

  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function healthVariant(value) {
  return value ? "success" : "danger";
}

function jobVariant(status) {
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

export default function SystemStatus() {
  const [me, setMe] = useState(null);
  const [health, setHealth] = useState(null);
  const [imports, setImports] = useState([]);
  const [alignments, setAlignments] = useState([]);

  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  async function load() {
    setErr("");
    setLoading(true);

    try {
      const [meData, importData, alignmentData] = await Promise.all([
        apiGet("/api/me/"),
        apiGet("/api/import-jobs/"),
        apiGet("/api/alignment-jobs/"),
      ]);

      let healthData = null;

      try {
        const response = await fetch("api/health/");
        healthData = await response.json();
      } catch (e) {
        healthData = {
          status: "unreachable",
          db_ok: false,
          redis_ok: false,
          clustalo_ok: false,
          error: e.message || String(e),
        };
      }

      setMe(meData);
      setHealth(healthData);
      setImports(importData.results || importData || []);
      setAlignments(alignmentData.results || alignmentData || []);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const userIsAdmin = isAdmin(me);

  const importStats = useMemo(() => {
    return {
      total: imports.length,
      failed: imports.filter((job) => job.status === "FAILED").length,
      running: imports.filter((job) => job.status === "RUNNING").length,
      pending: imports.filter((job) => job.status === "PENDING").length,
      completed: imports.filter((job) => job.status === "COMPLETED").length,
    };
  }, [imports]);

  const alignmentStats = useMemo(() => {
    return {
      total: alignments.length,
      failed: alignments.filter((job) => job.status === "FAILED").length,
      running: alignments.filter((job) => job.status === "RUNNING").length,
      pending: alignments.filter((job) => job.status === "PENDING").length,
      completed: alignments.filter((job) => job.status === "COMPLETED").length,
    };
  }, [alignments]);

  const recentImports = useMemo(() => {
    return [...imports]
      .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
      .slice(0, 8);
  }, [imports]);

  const recentAlignments = useMemo(() => {
    return [...alignments]
      .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
      .slice(0, 8);
  }, [alignments]);

  if (loading) {
    return (
      <div className="d-flex align-items-center gap-2">
        <Spinner animation="border" size="sm" />
        <span>Loading system status...</span>
      </div>
    );
  }

  if (!userIsAdmin) {
    return (
      <div className="w-100">
        <div className="page-header">
          <div>
            <h1 className="page-title">System Status</h1>
            <p className="page-subtitle">
              Admin-only operational dashboard.
            </p>
          </div>
        </div>

        <Alert variant="warning">
          Director/admin access is required to view system status.
        </Alert>
      </div>
    );
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">System Status</h1>
          <p className="page-subtitle">
            Monitor API health, database, Redis, Clustal Omega, imports, and
            alignment jobs.
          </p>
        </div>

        <div className="inline-actions">
          <Badge bg={health?.status === "ok" ? "success" : "danger"}>
            {health?.status || "unknown"}
          </Badge>

          <Button variant="outline-dark" size="sm" onClick={load}>
            Refresh
          </Button>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      <Row className="g-4 mb-4">
        <Col md={3}>
          <Card className="app-card metric-card h-100">
            <Card.Body>
              <div className="metric-label">Database</div>
              <div className="metric-value">
                <Badge bg={healthVariant(health?.db_ok)}>
                  {health?.db_ok ? "OK" : "Down"}
                </Badge>
              </div>
              <div className="metric-note">
                {health?.db_error || "PostgreSQL connectivity"}
              </div>
            </Card.Body>
          </Card>
        </Col>

        <Col md={3}>
          <Card className="app-card metric-card h-100">
            <Card.Body>
              <div className="metric-label">Redis / Cache</div>
              <div className="metric-value">
                <Badge bg={healthVariant(health?.redis_ok)}>
                  {health?.redis_ok ? "OK" : "Down"}
                </Badge>
              </div>
              <div className="metric-note">
                {health?.redis_error || "Celery broker/cache dependency"}
              </div>
            </Card.Body>
          </Card>
        </Col>

        <Col md={3}>
          <Card className="app-card metric-card h-100">
            <Card.Body>
              <div className="metric-label">Clustal Omega</div>
              <div className="metric-value">
                <Badge bg={healthVariant(health?.clustalo_ok)}>
                  {health?.clustalo_ok ? "OK" : "Missing"}
                </Badge>
              </div>
              <div className="metric-note">
                {health?.clustalo_version ||
                  health?.clustalo_error ||
                  "Sequence alignment tool"}
              </div>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="app-card metric-card h-100">
            <Card.Body>
              <div className="metric-label">BLASTN</div>
              <div className="metric-value">
                <Badge bg={healthVariant(health?.blastn_ok)}>
                  {health?.blastn_ok ? "OK" : "Missing"}
                </Badge>
              </div>
              <div className="metric-note">
                {health?.blastn_version ||
                  health?.blastn_error ||
                  "Nucleotide BLAST search"}
              </div>
            </Card.Body>
          </Card>
        </Col>

        <Col md={3}>
          <Card className="app-card metric-card h-100">
            <Card.Body>
              <div className="metric-label">BLASTP</div>
              <div className="metric-value">
                <Badge bg={healthVariant(health?.blastp_ok)}>
                  {health?.blastp_ok ? "OK" : "Missing"}
                </Badge>
              </div>
              <div className="metric-note">
                {health?.blastp_version ||
                  health?.blastp_error ||
                  "Protein BLAST search"}
              </div>
            </Card.Body>
          </Card>
        </Col>

        <Col md={3}>
          <Card className="app-card metric-card h-100">
            <Card.Body>
              <div className="metric-label">makeblastdb</div>
              <div className="metric-value">
                <Badge bg={healthVariant(health?.makeblastdb_ok)}>
                  {health?.makeblastdb_ok ? "OK" : "Missing"}
                </Badge>
              </div>
              <div className="metric-note">
                {health?.makeblastdb_version ||
                  health?.makeblastdb_error ||
                  "BLAST database builder"}
              </div>
            </Card.Body>
          </Card>
        </Col>
        <Col md={3}>
          <Card className="app-card metric-card h-100">
            <Card.Body>
              <div className="metric-label">Background Jobs</div>
              <div className="metric-value">
                {importStats.pending +
                  importStats.running +
                  alignmentStats.pending +
                  alignmentStats.running}
              </div>
              <div className="metric-note">Pending/running jobs</div>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="g-4 mb-4">
        <Col lg={6}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Import Job Health</h5>

              <div className="stat-grid mb-3">
                <div className="soft-card">
                  <div className="feed-meta">Total</div>
                  <strong>{importStats.total}</strong>
                </div>

                <div className="soft-card">
                  <div className="feed-meta">Completed</div>
                  <strong>{importStats.completed}</strong>
                </div>

                <div className="soft-card">
                  <div className="feed-meta">Active</div>
                  <strong>{importStats.pending + importStats.running}</strong>
                </div>

                <div className="soft-card">
                  <div className="feed-meta">Failed</div>
                  <strong>{importStats.failed}</strong>
                </div>
              </div>

              {recentImports.length === 0 ? (
                <div className="empty-state">No import jobs found.</div>
              ) : (
                <Table responsive hover className="app-table">
                  <thead>
                    <tr>
                      <th>Instrument</th>
                      <th>Status</th>
                      <th>Progress</th>
                      <th>Created</th>
                    </tr>
                  </thead>

                  <tbody>
                    {recentImports.map((job) => (
                      <tr key={job.id}>
                        <td>{job.instrument_code || job.instrument_name || `#${job.id}`}</td>
                        <td>
                          <Badge bg={jobVariant(job.status)}>
                            {job.status}
                          </Badge>
                        </td>
                        <td>{job.progress_percent ?? 0}%</td>
                        <td>{formatTimestamp(job.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </Col>

        <Col lg={6}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Alignment Job Health</h5>

              <div className="stat-grid mb-3">
                <div className="soft-card">
                  <div className="feed-meta">Total</div>
                  <strong>{alignmentStats.total}</strong>
                </div>

                <div className="soft-card">
                  <div className="feed-meta">Completed</div>
                  <strong>{alignmentStats.completed}</strong>
                </div>

                <div className="soft-card">
                  <div className="feed-meta">Active</div>
                  <strong>
                    {alignmentStats.pending + alignmentStats.running}
                  </strong>
                </div>

                <div className="soft-card">
                  <div className="feed-meta">Failed</div>
                  <strong>{alignmentStats.failed}</strong>
                </div>
              </div>

              {recentAlignments.length === 0 ? (
                <div className="empty-state">No alignment jobs found.</div>
              ) : (
                <Table responsive hover className="app-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Status</th>
                      <th>Tool</th>
                      <th>Created</th>
                    </tr>
                  </thead>

                  <tbody>
                    {recentAlignments.map((job) => (
                      <tr key={job.id}>
                        <td>{job.name}</td>
                        <td>
                          <Badge bg={jobVariant(job.status)}>
                            {job.status}
                          </Badge>
                        </td>
                        <td>{job.tool}</td>
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
    </div>
  );
}