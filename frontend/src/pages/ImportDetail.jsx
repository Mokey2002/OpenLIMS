import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  ProgressBar,
  Table,
} from "react-bootstrap";
import { Link, useParams } from "react-router-dom";
import { apiGet, apiPost } from "../api";

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
    case "UPLOAD":
      return "secondary";
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

function getProgressPercent(job) {
  if (!job) return 0;

  if (typeof job.progress_percent === "number") {
    return job.progress_percent;
  }

  if (job.status === "COMPLETED") return 100;

  if (!job.progress_total) return 0;

  return Math.round((job.progress_current / job.progress_total) * 100);
}

function safeSummary(job) {
  return job?.summary || {};
}

function normalizeSkippedRows(summary) {
  const skipped = summary?.skipped_rows;
  return Array.isArray(skipped) ? skipped : [];
}

function downloadSkippedRowsCsv(job) {
  const skippedRows = normalizeSkippedRows(job.summary);

  if (skippedRows.length === 0) return;

  const headers = Array.from(
    skippedRows.reduce((set, row) => {
      Object.keys(row || {}).forEach((key) => set.add(key));
      return set;
    }, new Set())
  );

  const escapeCsv = (value) => {
    const stringValue =
      value === null || value === undefined ? "" : String(value);

    if (
      stringValue.includes(",") ||
      stringValue.includes('"') ||
      stringValue.includes("\n")
    ) {
      return `"${stringValue.replaceAll('"', '""')}"`;
    }

    return stringValue;
  };

  const csv = [
    headers.join(","),
    ...skippedRows.map((row) =>
      headers.map((header) => escapeCsv(row?.[header])).join(",")
    ),
  ].join("\n");

  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);

  const link = document.createElement("a");
  link.href = url;
  link.download = `import-job-${job.id}-skipped-rows.csv`;
  link.click();

  URL.revokeObjectURL(url);
}

export default function ImportDetail() {
  const { id } = useParams();

  const [job, setJob] = useState(null);
  const [err, setErr] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState(false);
  const [linkedSamples, setLinkedSamples] = useState([]);
async function load() {
  setErr("");

  try {
    const [jobData, sampleData] = await Promise.all([
      apiGet(`/api/import-jobs/${id}/`),
      apiGet(`/api/import-jobs/${id}/samples/`),
    ]);

    setJob(jobData);
    setLinkedSamples(sampleData.results || sampleData || []);
  } catch (e) {
    setErr(e.message || String(e));
  } finally {
    setLoading(false);
  }
}

  useEffect(() => {
    load();
  }, [id]);

  useEffect(() => {
    if (!job || !["PENDING", "RUNNING"].includes(job.status)) return;

    const interval = setInterval(load, 3000);
    return () => clearInterval(interval);
  }, [job?.status, id]);

  async function retryImport() {
    setErr("");
    setSuccess("");
    setRetrying(true);

    try {
      const updated = await apiPost(`/api/import-jobs/${id}/retry/`, {});
      setJob(updated);
      setSuccess("Import retry queued.");
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setRetrying(false);
    }
  }

  const summary = useMemo(() => safeSummary(job), [job]);
  const skippedRows = useMemo(() => normalizeSkippedRows(summary), [summary]);
  const progress = getProgressPercent(job);

  const canRetry =
    job &&
    job.source_type === "UPLOAD" &&
    !["PENDING", "RUNNING"].includes(job.status);

  if (loading) {
    return (
      <div className="w-100">
        <Card className="app-card">
          <Card.Body>Loading import job...</Card.Body>
        </Card>
      </div>
    );
  }

  if (!job) {
    return (
      <div className="w-100">
        <Alert variant="danger">Import job not found.</Alert>
      </div>
    );
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Import Job #{job.id}</h1>
          <p className="page-subtitle">
            Inspect import progress, summary, skipped rows, and errors.
          </p>
        </div>

        <div className="inline-actions">
          <Button variant="outline-dark" size="sm" onClick={load}>
            Refresh
          </Button>

          <Button
            variant="dark"
            size="sm"
            onClick={retryImport}
            disabled={!canRetry || retrying}
          >
            {retrying ? "Queueing..." : "Retry Import"}
          </Button>

          <Link to="/imports" className="btn btn-outline-secondary btn-sm">
            Back to Imports
          </Link>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}
      {success && <Alert variant="success">{success}</Alert>}

      <div className="row g-4 mb-4">
        <div className="col-lg-8">
          <Card className="app-card h-100">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">Job Overview</h5>
                <div className="inline-actions">
                  <Badge bg={statusVariant(job.status)}>{job.status}</Badge>
                  <Badge bg={sourceVariant(job.source_type)}>
                    {job.source_type || "UNKNOWN"}
                  </Badge>
                </div>
              </div>

              <div className="soft-card mb-3">
                <div className="feed-meta mb-2">Progress</div>
                <ProgressBar
                  now={progress}
                  label={`${progress}%`}
                  variant={job.status === "FAILED" ? "danger" : "dark"}
                />
                <div className="feed-meta mt-2">
                  {job.progress_message || "-"}
                </div>
              </div>

              <div className="row g-3">
                <div className="col-md-6">
                  <div className="soft-card">
                    <div className="feed-meta">Instrument</div>
                    <div className="fw-semibold">
                      {job.instrument_code || job.instrument}{" "}
                      {job.instrument_name ? `— ${job.instrument_name}` : ""}
                    </div>
                  </div>
                </div>

                <div className="col-md-6">
                  <div className="soft-card">
                    <div className="feed-meta">Project</div>
                    <div className="fw-semibold">
                      {job.project_code || "-"}{" "}
                      {job.project_name ? `— ${job.project_name}` : ""}
                    </div>
                  </div>
                </div>

                <div className="col-md-6">
                  <div className="soft-card">
                    <div className="feed-meta">Run ID</div>
                    <div className="fw-semibold">{job.run_id || "-"}</div>
                  </div>
                </div>

                <div className="col-md-6">
                  <div className="soft-card">
                    <div className="feed-meta">Uploaded By</div>
                    <div className="fw-semibold">
                      {job.uploaded_by_username || "Instrument/API"}
                    </div>
                  </div>
                </div>

                <div className="col-md-6">
                  <div className="soft-card">
                    <div className="feed-meta">Created</div>
                    <div className="fw-semibold">
                      {formatTimestamp(job.created_at)}
                    </div>
                  </div>
                </div>

                <div className="col-md-6">
                  <div className="soft-card">
                    <div className="feed-meta">Progress Count</div>
                    <div className="fw-semibold">
                      {job.progress_current ?? 0} / {job.progress_total ?? 0}
                    </div>
                  </div>
                </div>
              </div>
            </Card.Body>
          </Card>
        </div>

        <div className="col-lg-4">
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Summary</h5>

              {summary?.error ? (
                <Alert variant="danger" className="mb-0">
                  {summary.error}
                </Alert>
              ) : (
                <div className="d-grid gap-2">
                  <div className="soft-card">
                    <div className="feed-meta">Rows Processed</div>
                    <div className="fs-4 fw-bold">
                      {summary.rows_processed ?? 0}
                    </div>
                  </div>

                  <div className="soft-card">
                    <div className="feed-meta">Samples Matched</div>
                    <div className="fs-4 fw-bold">
                      {summary.samples_matched ?? 0}
                    </div>
                  </div>

                  <div className="soft-card">
                    <div className="feed-meta">Samples Created</div>
                    <div className="fs-4 fw-bold">
                      {summary.samples_created ?? 0}
                    </div>
                  </div>

                  <div className="soft-card">
                    <div className="feed-meta">Results Created</div>
                    <div className="fs-4 fw-bold">
                      {summary.results_created ?? 0}
                    </div>
                  </div>

                  <div className="soft-card">
                    <div className="feed-meta">Skipped Rows</div>
                    <div className="fs-4 fw-bold">{skippedRows.length}</div>
                  </div>
                </div>
              )}
            </Card.Body>
          </Card>
        </div>
      </div>

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <h5 className="section-title mb-0">Skipped Rows</h5>

            <Button
              variant="outline-dark"
              size="sm"
              onClick={() => downloadSkippedRowsCsv(job)}
              disabled={skippedRows.length === 0}
            >
              Download CSV
            </Button>
          </div>

          {skippedRows.length === 0 ? (
            <div className="empty-state">No skipped rows for this import.</div>
          ) : (
            <Table responsive hover className="app-table">
              <thead>
                <tr>
                  <th>Row</th>
                  <th>Sample</th>
                  <th>Column</th>
                  <th>Reason</th>
                </tr>
              </thead>

              <tbody>
                {skippedRows.map((row, index) => (
                  <tr key={`${row.row || index}-${row.column || "row"}`}>
                    <td>{row.row ?? "-"}</td>
                    <td>{row.sample_id ?? "-"}</td>
                    <td>{row.column ?? "-"}</td>
                    <td>{row.reason ?? JSON.stringify(row)}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>

      <Card className="app-card mb-4">
  <Card.Body>
    <div className="toolbar-row mb-3">
      <h5 className="section-title mb-0">Linked Samples</h5>
      <div className="feed-meta">{linkedSamples.length} samples</div>
    </div>

    {linkedSamples.length === 0 ? (
      <div className="empty-state">
        No samples were linked to this import.
      </div>
    ) : (
      <Table responsive hover className="app-table">
        <thead>
          <tr>
            <th>Sample</th>
            <th>Import Action</th>
            <th>Status</th>
            <th>Project</th>
            <th>Container</th>
            <th>Created</th>
          </tr>
        </thead>

        <tbody>
          {linkedSamples.map((sample) => (
            <tr key={sample.id}>
              <td>
                <Link to={`/samples/${sample.id}`}>
                  {sample.sample_id}
                </Link>
              </td>
              <td>
                <Badge
                  bg={
                    sample.import_action === "CREATED"
                      ? "success"
                      : sample.import_action === "MATCHED"
                      ? "primary"
                      : "secondary"
                  }
                >
                  {sample.import_action}
                </Badge>
              </td>
              <td>{sample.status}</td>
              <td>{sample.project_code || "-"}</td>
              <td>{sample.container_code || "-"}</td>
              <td>{formatTimestamp(sample.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </Table>
    )}
  </Card.Body>
</Card>

      <Card className="app-card">
        <Card.Body>
          <h5 className="section-title">Raw Summary</h5>
          <pre className="app-pre">{JSON.stringify(summary, null, 2)}</pre>
        </Card.Body>
      </Card>
    </div>
  );
}