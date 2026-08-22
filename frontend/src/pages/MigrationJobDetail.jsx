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
import { Link, useParams } from "react-router-dom";
import { apiGet } from "../api";

function statusVariant(status) {
  switch (status) {
    case "COMPLETED":
      return "success";
    case "PARTIAL_FAILED":
      return "warning";
    case "FAILED":
      return "danger";
    case "RUNNING":
      return "primary";
    case "PENDING":
      return "secondary";
    case "PREVIEWED":
      return "info";
    default:
      return "secondary";
  }
}

function formatTimestamp(ts) {
  if (!ts) return "-";

  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function asText(value) {
  if (value === null || value === undefined || value === "") return "-";

  if (typeof value === "object") {
    return JSON.stringify(value);
  }

  return String(value);
}

export default function MigrationJobDetail() {
  const { id } = useParams();

  const [job, setJob] = useState(null);
  const [rowsData, setRowsData] = useState(null);
  const [err, setErr] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [downloading, setDownloading] = useState(false);

  async function load(targetPage = page) {
    setErr("");

    try {
      const params = new URLSearchParams();

      params.set("job", id);
      params.set("page", targetPage);

      if (statusFilter) params.set("status", statusFilter);
      if (search.trim()) params.set("search", search.trim());

      const [jobData, rowData] = await Promise.all([
        apiGet(`/api/migration-jobs/${id}/`),
        apiGet(`/api/migration-row-records/?${params.toString()}`),
      ]);

      setJob(jobData);
      setRowsData(rowData);
      setPage(targetPage);
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function applyFilters(e) {
    e.preventDefault();
    await load(1);
  }

  async function downloadRows(exportStatus = "") {
    setDownloading(true);
    setErr("");

    try {
      const params = new URLSearchParams();

      if (exportStatus) params.set("status", exportStatus);
      if (search.trim()) params.set("search", search.trim());

      const token = localStorage.getItem("access");
      const response = await fetch(
        `/api/migration-jobs/${id}/export-rows/?${params.toString()}`,
        {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        }
      );

      if (!response.ok) {
        throw new Error(`Export failed with status ${response.status}`);
      }

      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");

      link.href = url;
      link.download = `migration_job_${id}_rows.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setDownloading(false);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => load(1), 0);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    if (!job || !["PENDING", "RUNNING"].includes(job.status)) return;

    const timer = setInterval(() => {
      load(page);
    }, 3000);

    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status, page]);

  const rows = rowsData?.results || rowsData || [];
  const progress = job?.summary?.progress || {};
  const skippedRows = job?.summary?.skipped_rows || [];

  if (!job) {
    return (
      <div className="w-100">
        {err ? (
          <Alert variant="danger">{err}</Alert>
        ) : (
          <Card className="app-card">
            <Card.Body>Loading migration job...</Card.Body>
          </Card>
        )}
      </div>
    );
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Migration Job #{job.id}</h1>
          <p className="page-subtitle">
            Review imported, skipped, and failed rows from this migration.
          </p>
        </div>

        <div className="inline-actions">
          <Badge bg={statusVariant(job.status)}>{job.status}</Badge>
          <Button variant="outline-dark" size="sm" onClick={() => load(page)}>
            Refresh
          </Button>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      <Row className="g-3 mb-4">
        <Col md={3}>
          <Card className="app-card metric-card h-100">
            <Card.Body>
              <div className="metric-label">Progress</div>
              <div className="metric-value">{progress.percent ?? 0}%</div>
              <div className="metric-note">
                {progress.processed_rows ?? 0} of {progress.total_rows ?? "-"} rows
              </div>
            </Card.Body>
          </Card>
        </Col>

        <Col md={3}>
          <Card className="app-card metric-card h-100">
            <Card.Body>
              <div className="metric-label">Rows Processed</div>
              <div className="metric-value">{job.summary?.rows_processed ?? 0}</div>
              <div className="metric-note">
                Row records: {job.row_record_count ?? 0}
              </div>
            </Card.Body>
          </Card>
        </Col>

        <Col md={3}>
          <Card className="app-card metric-card h-100">
            <Card.Body>
              <div className="metric-label">Samples</div>
              <div className="metric-value">
                {(job.summary?.samples_created?.length ?? 0) +
                  (job.summary?.samples_matched?.length ?? 0)}
              </div>
              <div className="metric-note">
                Created: {job.summary?.samples_created?.length ?? 0} · Matched:{" "}
                {job.summary?.samples_matched?.length ?? 0}
              </div>
            </Card.Body>
          </Card>
        </Col>

        <Col md={3}>
          <Card className="app-card metric-card h-100">
            <Card.Body>
              <div className="metric-label">Skipped / Warnings</div>
              <div className="metric-value">{skippedRows.length}</div>
              <div className="metric-note">
                Results: {job.summary?.results_created ?? 0}
              </div>
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Job Summary</h5>

          <Row className="g-3">
            <Col md={4}>
              <div className="soft-card">
                <div className="feed-meta">Profile</div>
                <div>{job.profile_name || `Profile #${job.profile}`}</div>
              </div>
            </Col>

            <Col md={4}>
              <div className="soft-card">
                <div className="feed-meta">Source</div>
                <div>{job.source_connection_name || job.project_code || "Project from CSV mapping"}</div>
              </div>
            </Col>

            <Col md={4}>
              <div className="soft-card">
                <div className="feed-meta">Created</div>
                <div>{formatTimestamp(job.created_at)}</div>
              </div>
            </Col>
          </Row>

          {job.summary?.error && (
            <Alert variant="danger" className="mt-3">
              {job.summary.error}
            </Alert>
          )}
        </Card.Body>
      </Card>

      <Card className="app-card">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Row Review</h5>
              <div className="feed-meta">
                Filter imported, skipped, or error rows without loading the full file.
              </div>
            </div>

            <div className="d-flex gap-2">
              <Button
                size="sm"
                variant="outline-dark"
                disabled={downloading}
                onClick={() => downloadRows("")}
              >
                Export Rows
              </Button>

              <Button
                size="sm"
                variant="outline-danger"
                disabled={downloading}
                onClick={() => downloadRows("ERROR")}
              >
                Export Errors
              </Button>

              <Button
                size="sm"
                variant="outline-warning"
                disabled={downloading}
                onClick={() => downloadRows("SKIPPED")}
              >
                Export Skipped
              </Button>
            </div>
          </div>

          <Form onSubmit={applyFilters} className="mb-3">
            <Row className="g-2">
              <Col md={3}>
                <Form.Select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                >
                  <option value="">All statuses</option>
                  <option value="IMPORTED">Imported</option>
                  <option value="SKIPPED">Skipped</option>
                  <option value="ERROR">Error</option>
                </Form.Select>
              </Col>

              <Col md={7}>
                <Form.Control
                  placeholder="Search project code, sample ID, or raw row text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                />
              </Col>

              <Col md={2}>
                <Button type="submit" variant="dark" className="w-100">
                  Search
                </Button>
              </Col>
            </Row>
          </Form>

          {rows.length === 0 ? (
            <div className="empty-state">No row records found.</div>
          ) : (
            <>
              <Table responsive hover className="app-table">
                <thead>
                  <tr>
                    <th>Row</th>
                    <th>Status</th>
                    <th>Dataset / Entity</th>
                    <th>Source Key</th>
                    <th>Project</th>
                    <th>Sample</th>
                    <th>Errors</th>
                    <th>Raw Row</th>
                  </tr>
                </thead>

                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id}>
                      <td>{row.row_number}</td>
                      <td>
                        <Badge bg={row.status === "IMPORTED" ? "success" : row.status === "ERROR" ? "danger" : "warning"}>
                          {row.status}
                        </Badge>
                      </td>
                      <td>
                        {row.source_dataset ? `#${row.source_dataset} / ` : ""}
                        {row.entity_type || "CSV"}
                      </td>
                      <td>{row.source_key || "-"}</td>
                      <td>
                        {row.project ? (
                          <Link to={`/projects/${row.project}`}>
                            {row.project_code_resolved || row.project_code}
                          </Link>
                        ) : (
                          row.project_code || "-"
                        )}
                      </td>
                      <td>
                        {row.sample ? (
                          <Link to={`/samples/${row.sample}`}>
                            {row.sample_code_resolved || row.sample_code}
                          </Link>
                        ) : (
                          row.sample_code || "-"
                        )}
                      </td>
                      <td>{row.errors?.length ? row.errors.join(", ") : "-"}</td>
                      <td style={{ minWidth: 360 }}>
                        <details>
                          <summary>View</summary>
                          <pre className="mt-2 mb-0 small">
                            {asText(row.raw_row)}
                          </pre>
                        </details>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>

              <div className="d-flex justify-content-between align-items-center">
                <Button
                  variant="outline-dark"
                  size="sm"
                  disabled={!rowsData?.previous}
                  onClick={() => load(Math.max(page - 1, 1))}
                >
                  Previous
                </Button>

                <div className="feed-meta">Page {page}</div>

                <Button
                  variant="outline-dark"
                  size="sm"
                  disabled={!rowsData?.next}
                  onClick={() => load(page + 1)}
                >
                  Next
                </Button>
              </div>
            </>
          )}
        </Card.Body>
      </Card>
    </div>
  );
}
