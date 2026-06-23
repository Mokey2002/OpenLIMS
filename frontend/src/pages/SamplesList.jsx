import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  Card,
  Form,
  Row,
  Col,
  Table,
  Pagination,
} from "react-bootstrap";
import { apiGet, apiPost } from "../api";
import { getAccessToken } from "../auth";
import { isAdmin, isTech, canWrite } from "../authz";

const STATUS_OPTIONS = [
  "",
  "RECEIVED",
  "IN_PROGRESS",
  "QC",
  "REPORTED",
  "ARCHIVED",
];

function formatTimestamp(value) {
  if (!value) return "-";

  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function linkedProjectBadges(sample) {
  const linkedProjects = sample.linked_project_summaries || [];

  if (linkedProjects.length === 0) {
    return "-";
  }

  return (
    <div className="d-flex gap-1 flex-wrap">
      {linkedProjects.map((project) => (
        <Badge key={project.id} bg="info">
          {project.code || `Project #${project.id}`}
        </Badge>
      ))}
    </div>
  );
}

function statusVariant(status) {
  switch (status) {
    case "RECEIVED":
      return "secondary";
    case "IN_PROGRESS":
      return "primary";
    case "QC":
      return "warning";
    case "REPORTED":
      return "success";
    case "ARCHIVED":
      return "dark";
    default:
      return "light";
  }
}

async function downloadSelectedSamples(ids) {
  const token = getAccessToken();

  const response = await fetch("/api/samples/export-selected/", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ids }),
  });

  if (!response.ok) {
    throw new Error(`Export failed with status ${response.status}`);
  }

  const blob = await response.blob();
  const downloadUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = downloadUrl;
  link.download = "openlims-selected-samples.csv";
  link.click();

  URL.revokeObjectURL(downloadUrl);
}

export default function SamplesList() {
  const [samples, setSamples] = useState([]);
  const [projects, setProjects] = useState([]);
  const [containers, setContainers] = useState([]);
  const [me, setMe] = useState(null);

  const [err, setErr] = useState("");
  const [success, setSuccess] = useState("");
  const [bulkResult, setBulkResult] = useState(null);

  const [sampleId, setSampleId] = useState("");
  const [projectId, setProjectId] = useState("");

  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [containerFilter, setContainerFilter] = useState("");

  const [selectedIds, setSelectedIds] = useState([]);
  const [bulkStatus, setBulkStatus] = useState("");
  const [bulkProject, setBulkProject] = useState("");
  const [bulkContainer, setBulkContainer] = useState("");
  const [bulkReason, setBulkReason] = useState("");

  const [exporting, setExporting] = useState(false);

  const [page, setPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [nextPageUrl, setNextPageUrl] = useState(null);
  const [previousPageUrl, setPreviousPageUrl] = useState(null);

  async function load() {
    setErr("");

    try {
      const params = new URLSearchParams();

      if (search.trim()) params.set("search", search.trim());
      if (status) params.set("status", status);
      if (projectFilter) params.set("project", projectFilter);
      if (containerFilter) params.set("container", containerFilter);

      params.set("page", page);

      const [samplesData, projectsData, containersData, meData] = await Promise.all([
        apiGet(`/api/samples/?${params.toString()}`),
        apiGet("/api/projects/"),
        apiGet("/api/containers/"),
        apiGet("/api/me/"),
      ]);

      setSamples(samplesData.results || []);
      setTotalCount(samplesData.count || 0);
      setNextPageUrl(samplesData.next || null);
      setPreviousPageUrl(samplesData.previous || null);
      setProjects(projectsData.results || projectsData || []);
      setContainers(containersData.results || containersData || []);
      setMe(meData);
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, status, projectFilter, containerFilter, page]);

  useEffect(() => {
    setPage(1);
  }, [search, status, projectFilter, containerFilter]);

  const selectedVisibleCount = useMemo(() => {
    return samples.filter((sample) => selectedIds.includes(sample.id)).length;
  }, [samples, selectedIds]);

  const allVisibleSelected = useMemo(() => {
    return samples.length > 0 && selectedVisibleCount === samples.length;
  }, [samples, selectedVisibleCount]);

  const totalPages = Math.max(1, Math.ceil(totalCount / 10));

  const userIsAdmin = isAdmin(me);
  const userIsTech = isTech(me);
  const userCanWrite = canWrite(me);

  const visibilityMessage = userIsAdmin
    ? "Showing all samples, including unassigned samples, because you are an admin."
    : userIsTech
      ? "Showing samples from your assigned primary projects, linked projects, plus unassigned samples you created."
      : "Showing samples from your assigned primary or linked projects only.";

  const emptyMessage = userIsAdmin
    ? "No samples found."
    : userIsTech
      ? "No samples found in your assigned primary/linked projects or unassigned samples you created."
      : "No samples found in your assigned primary or linked projects. Ask an admin to add you to a project if you need access.";

  function toggleSelected(id) {
    setSelectedIds((prev) =>
      prev.includes(id)
        ? prev.filter((currentId) => currentId !== id)
        : [...prev, id]
    );
  }

  function toggleSelectAllVisible() {
    if (allVisibleSelected) {
      const visibleIds = new Set(samples.map((sample) => sample.id));
      setSelectedIds((prev) => prev.filter((id) => !visibleIds.has(id)));
    } else {
      setSelectedIds((prev) =>
        Array.from(new Set([...prev, ...samples.map((sample) => sample.id)]))
      );
    }
  }

  function clearSelection() {
    setSelectedIds([]);
  }

  async function createSample(e) {
    e.preventDefault();

    setErr("");
    setSuccess("");

    const id = sampleId.trim();

    if (!id) return;

    try {
      await apiPost("/api/samples/", {
        sample_id: id,
        status: "RECEIVED",
        project: projectId ? Number(projectId) : null,
      });

      setSampleId("");
      setProjectId("");
      setSuccess("Sample created.");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function applyBulkUpdate() {
    setErr("");
    setSuccess("");
    setBulkResult(null);

    if (selectedIds.length === 0) {
      setErr("Select at least one sample.");
      return;
    }

    if (!bulkStatus && !bulkProject && !bulkContainer) {
      setErr("Choose at least one bulk action.");
      return;
    }

    if (bulkStatus && bulkReason.trim().length < 10) {
      setErr("Reason for change is required for bulk status updates and must be at least 10 characters.");
      return;
    }

    try {
      const payload = { ids: selectedIds };

      if (bulkStatus) {
        payload.status = bulkStatus;
        payload.reason = bulkReason.trim();
      }
      if (bulkProject) payload.project = Number(bulkProject);
      if (bulkContainer) payload.container = Number(bulkContainer);

      const result = await apiPost("/api/samples/bulk-update/", payload);

      setBulkResult(result);
      setSuccess(`Updated ${result.updated} sample(s).`);

      setSelectedIds([]);
      setBulkStatus("");
      setBulkProject("");
      setBulkContainer("");
      setBulkReason("");
      setBulkReason("");

      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function archiveSelected() {
    setBulkStatus("ARCHIVED");

    setErr("");
    setSuccess("");
    setBulkResult(null);

    if (selectedIds.length === 0) {
      setErr("Select at least one sample.");
      return;
    }

    if (bulkReason.trim().length < 10) {
      setErr("Reason for change is required to archive selected samples.");
      return;
    }

    try {
      const result = await apiPost("/api/samples/bulk-update/", {
        ids: selectedIds,
        status: "ARCHIVED",
        reason: bulkReason.trim(),
      });

      setBulkResult(result);
      setSuccess(`Archived ${result.updated} sample(s).`);

      setSelectedIds([]);
      setBulkStatus("");
      setBulkProject("");
      setBulkContainer("");

      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function exportSelected() {
    setErr("");
    setSuccess("");
    setExporting(true);

    if (selectedIds.length === 0) {
      setErr("Select at least one sample to export.");
      setExporting(false);
      return;
    }

    try {
      await downloadSelectedSamples(selectedIds);
      setSuccess(`Exported ${selectedIds.length} selected sample(s).`);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Samples</h1>
          <p className="page-subtitle">
            Track sample lifecycle, assignments, storage, and bulk operations.
          </p>
        </div>

        <div className="inline-actions">
          <Badge bg="dark">{selectedIds.length} selected</Badge>
          <Button variant="outline-dark" size="sm" onClick={load}>
            Refresh
          </Button>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}
      {success && <Alert variant="success">{success}</Alert>}

      <Alert variant="info" className="mb-4">
        {visibilityMessage}
      </Alert>

      {userCanWrite && (
      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Create Sample</h5>

          <Form onSubmit={createSample}>
            <Row className="g-2">
              <Col md={6}>
                <Form.Control
                  value={sampleId}
                  onChange={(e) => setSampleId(e.target.value)}
                  placeholder="New sample id, e.g. S-002"
                />
              </Col>

              <Col md={4}>
                <Form.Select
                  value={projectId}
                  onChange={(e) => setProjectId(e.target.value)}
                >
                  <option value="">No project</option>

                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.code} - {project.name}
                    </option>
                  ))}
                </Form.Select>
              </Col>

              <Col md={2}>
                <Button type="submit" variant="dark" className="w-100">
                  Create
                </Button>
              </Col>
            </Row>
          </Form>
        </Card.Body>
      </Card>
      )}

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Filters</h5>

          <Row className="g-3">
            <Col md={4}>
              <Form.Control
                placeholder="Search by sample ID"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </Col>

            <Col md={2}>
              <Form.Select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                <option value="">All statuses</option>

                {STATUS_OPTIONS.filter(Boolean).map((statusValue) => (
                  <option key={statusValue} value={statusValue}>
                    {statusValue}
                  </option>
                ))}
              </Form.Select>
            </Col>

            <Col md={3}>
              <Form.Select
                value={projectFilter}
                onChange={(e) => setProjectFilter(e.target.value)}
              >
                <option value="">All projects</option>

                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.code} - {project.name}
                  </option>
                ))}
              </Form.Select>
            </Col>

            <Col md={3}>
              <Form.Select
                value={containerFilter}
                onChange={(e) => setContainerFilter(e.target.value)}
              >
                <option value="">All containers</option>

                {containers.map((container) => (
                  <option key={container.id} value={container.id}>
                    {container.container_id} - {container.kind}
                  </option>
                ))}
              </Form.Select>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      {userCanWrite && (
      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Bulk Actions</h5>
              <div className="feed-meta">
                Select samples below, then apply batch updates.
              </div>
            </div>

            <Badge bg="dark">{selectedIds.length} selected</Badge>
          </div>

          <Row className="g-2">
            <Col md={3}>
              <Form.Select
                value={bulkStatus}
                onChange={(e) => setBulkStatus(e.target.value)}
              >
                <option value="">Set status...</option>

                {STATUS_OPTIONS.filter(Boolean).map((statusValue) => (
                  <option key={statusValue} value={statusValue}>
                    {statusValue}
                  </option>
                ))}
              </Form.Select>
            </Col>

            <Col md={3}>
              <Form.Select
                value={bulkProject}
                onChange={(e) => setBulkProject(e.target.value)}
              >
                <option value="">Assign project...</option>

                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.code} - {project.name}
                  </option>
                ))}
              </Form.Select>
            </Col>

            <Col md={3}>
              <Form.Select
                value={bulkContainer}
                onChange={(e) => setBulkContainer(e.target.value)}
              >
                <option value="">Assign container...</option>

                {containers.map((container) => (
                  <option key={container.id} value={container.id}>
                    {container.container_id} - {container.kind}
                  </option>
                ))}
              </Form.Select>
            </Col>

            <Col md={3}>
              <Button
                variant="dark"
                className="w-100"
                onClick={applyBulkUpdate}
                disabled={
                  selectedIds.length === 0 ||
                  (bulkStatus && bulkReason.trim().length < 10)
                }
              >
                Apply to {selectedIds.length}
              </Button>
            </Col>
          </Row>

          {bulkStatus && (
            <div className="mt-3">
              <Form.Label>Reason for status change</Form.Label>
              <Form.Control
                as="textarea"
                rows={2}
                value={bulkReason}
                onChange={(e) => setBulkReason(e.target.value)}
                placeholder="Example: Samples completed review and are ready for the next workflow step."
              />
              <div className="feed-meta mt-1">
                Required when changing sample status. This reason is saved in the audit trail.
              </div>
            </div>
          )}

          <div className="inline-actions mt-3">
            <Button
              variant="outline-secondary"
              size="sm"
              onClick={toggleSelectAllVisible}
              disabled={samples.length === 0}
            >
              {allVisibleSelected ? "Unselect Visible" : "Select Visible"}
            </Button>

            <Button
              variant="outline-secondary"
              size="sm"
              onClick={clearSelection}
              disabled={selectedIds.length === 0}
            >
              Clear Selection
            </Button>

            <Button
              variant="outline-warning"
              size="sm"
              onClick={archiveSelected}
              disabled={selectedIds.length === 0 || bulkReason.trim().length < 10}
            >
              Archive Selected
            </Button>

            <Button
              variant="outline-primary"
              size="sm"
              onClick={exportSelected}
              disabled={selectedIds.length === 0 || exporting}
            >
              {exporting ? "Exporting..." : "Export Selected CSV"}
            </Button>
          </div>

          {bulkResult && (
            <div className="mt-3">
              <Alert variant="success" className="mb-2">
                Updated {bulkResult.updated} sample(s).
              </Alert>

              {bulkResult.skipped?.length > 0 && (
                <Alert variant="warning" className="mb-0">
                  <div className="fw-semibold mb-2">
                    Skipped {bulkResult.skipped.length} sample(s):
                  </div>

                  <ul className="mb-0">
                    {bulkResult.skipped.map((sample) => (
                      <li key={sample.id}>
                        {sample.sample_id}: {sample.reason}
                      </li>
                    ))}
                  </ul>
                </Alert>
              )}
            </div>
          )}
        </Card.Body>
      </Card>
      )}

      <Card className="app-card">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div className="feed-meta">
              Showing {samples.length} of {totalCount} samples
            </div>

            <Pagination className="mb-0">
              <Pagination.Prev
                disabled={!previousPageUrl || page === 1}
                onClick={() => setPage((currentPage) => Math.max(1, currentPage - 1))}
              />

              <Pagination.Item active>{page}</Pagination.Item>

              <Pagination.Next
                disabled={!nextPageUrl || page >= totalPages}
                onClick={() => setPage((currentPage) => currentPage + 1)}
              />
            </Pagination>
          </div>

          {samples.length === 0 ? (
            <div className="empty-state">{emptyMessage}</div>
          ) : (
            <Table responsive hover className="app-table align-middle">
              <thead>
                <tr>
                  <th>
                    <Form.Check
                      type="checkbox"
                      checked={allVisibleSelected}
                      onChange={toggleSelectAllVisible}
                    />
                  </th>
                  <th>ID</th>
                  <th>Sample ID</th>
                  <th>Primary Project</th>
                  <th>Linked Projects</th>
                  <th>Status</th>
                  <th>Container</th>
                  <th>Location</th>
                  <th>Created By</th>
                  <th>Created At</th>
                </tr>
              </thead>

              <tbody>
                {samples.map((sample) => (
                  <tr key={sample.id}>
                    <td>
                      <Form.Check
                        type="checkbox"
                        checked={selectedIds.includes(sample.id)}
                        onChange={() => toggleSelected(sample.id)}
                      />
                    </td>

                    <td>{sample.id}</td>

                    <td>
                      <Link to={`/samples/${sample.id}`}>
                        {sample.sample_id}
                      </Link>
                    </td>

                    <td>
                      {sample.project_code ? (
                        <Badge bg="dark">{sample.project_code}</Badge>
                      ) : (
                        "-"
                      )}
                    </td>

                    <td>{linkedProjectBadges(sample)}</td>

                    <td>
                      <Badge bg={statusVariant(sample.status)}>
                        {sample.status}
                      </Badge>
                    </td>

                    <td>{sample.container_code || "-"}</td>
                    <td>{sample.location_name || "-"}</td>
                    <td>{sample.created_by_username || "-"}</td>
                    <td>{formatTimestamp(sample.created_at)}</td>
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