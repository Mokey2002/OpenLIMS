import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  Alert,
  Button,
  Card,
  Form,
  Row,
  Col,
  Table,
  Pagination,
} from "react-bootstrap";
import { apiGet, apiPost } from "../api";

const STATUS_OPTIONS = ["", "RECEIVED", "IN_PROGRESS", "QC", "REPORTED", "ARCHIVED"];

export default function SamplesList() {
  const [samples, setSamples] = useState([]);
  const [projects, setProjects] = useState([]);
  const [err, setErr] = useState("");
  const [bulkResult, setBulkResult] = useState(null);

  const [sampleId, setSampleId] = useState("");
  const [projectId, setProjectId] = useState("");

  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [projectFilter, setProjectFilter] = useState("");

  const [selectedIds, setSelectedIds] = useState([]);
  const [bulkStatus, setBulkStatus] = useState("");
  const [bulkProject, setBulkProject] = useState("");

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
      params.set("page", page);

      const [samplesData, projectsData] = await Promise.all([
        apiGet(`/api/samples/?${params.toString()}`),
        apiGet("/api/projects/"),
      ]);

      setSamples(samplesData.results || []);
      setTotalCount(samplesData.count || 0);
      setNextPageUrl(samplesData.next || null);
      setPreviousPageUrl(samplesData.previous || null);
      setProjects(projectsData.results || projectsData || []);
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  useEffect(() => { load(); }, [search, status, projectFilter, page]);
  useEffect(() => { setPage(1); }, [search, status, projectFilter]);

  function toggleSelected(id) {
    setSelectedIds((prev) => prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]);
  }

  function toggleSelectAll() {
    if (selectedIds.length === samples.length) setSelectedIds([]);
    else setSelectedIds(samples.map((s) => s.id));
  }

  async function createSample(e) {
    e.preventDefault();
    setErr("");
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
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function applyBulkUpdate() {
    setErr("");
    setBulkResult(null);

    try {
      const payload = { ids: selectedIds };
      if (bulkStatus) payload.status = bulkStatus;
      if (bulkProject) payload.project = Number(bulkProject);

      const result = await apiPost("/api/samples/bulk-update/", payload);
      setBulkResult(result);
      setSelectedIds([]);
      setBulkStatus("");
      setBulkProject("");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  const totalPages = Math.max(1, Math.ceil(totalCount / 10));

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Samples</h1>
          <p className="page-subtitle">Track sample lifecycle, assignments, and batch updates.</p>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Create Sample</h5>
          <Form onSubmit={createSample}>
            <Row className="g-2">
              <Col md={6}>
                <Form.Control
                  value={sampleId}
                  onChange={(e) => setSampleId(e.target.value)}
                  placeholder="New sample id (e.g. S-002)"
                />
              </Col>
              <Col md={4}>
                <Form.Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
                  <option value="">No project</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>{p.code} - {p.name}</option>
                  ))}
                </Form.Select>
              </Col>
              <Col md={2}>
                <Button type="submit" variant="dark" className="w-100">Create</Button>
              </Col>
            </Row>
          </Form>
        </Card.Body>
      </Card>

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Filters</h5>
          <Row className="g-3">
            <Col md={5}>
              <Form.Control
                placeholder="Search by sample ID"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </Col>
            <Col md={3}>
              <Form.Select value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">All statuses</option>
                {STATUS_OPTIONS.filter(Boolean).map((s) => <option key={s} value={s}>{s}</option>)}
              </Form.Select>
            </Col>
            <Col md={4}>
              <Form.Select value={projectFilter} onChange={(e) => setProjectFilter(e.target.value)}>
                <option value="">All projects</option>
                {projects.map((p) => <option key={p.id} value={p.id}>{p.code} - {p.name}</option>)}
              </Form.Select>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Bulk Actions</h5>
          <Row className="g-2">
            <Col md={4}>
              <Form.Select value={bulkStatus} onChange={(e) => setBulkStatus(e.target.value)}>
                <option value="">Set status...</option>
                {STATUS_OPTIONS.filter(Boolean).map((s) => <option key={s} value={s}>{s}</option>)}
              </Form.Select>
            </Col>
            <Col md={4}>
              <Form.Select value={bulkProject} onChange={(e) => setBulkProject(e.target.value)}>
                <option value="">Assign project...</option>
                {projects.map((p) => <option key={p.id} value={p.id}>{p.code} - {p.name}</option>)}
              </Form.Select>
            </Col>
            <Col md={4}>
              <Button variant="dark" className="w-100" onClick={applyBulkUpdate} disabled={selectedIds.length === 0}>
                Apply to {selectedIds.length} sample(s)
              </Button>
            </Col>
          </Row>

          {bulkResult && (
            <div className="mt-3">
              <Alert variant="success" className="mb-2">Updated {bulkResult.updated} sample(s).</Alert>
              {bulkResult.skipped?.length > 0 && (
                <Alert variant="warning" className="mb-0">
                  <div className="fw-semibold mb-2">Skipped {bulkResult.skipped.length} sample(s):</div>
                  <ul className="mb-0">
                    {bulkResult.skipped.map((s) => (
                      <li key={s.id}>{s.sample_id}: {s.reason}</li>
                    ))}
                  </ul>
                </Alert>
              )}
            </div>
          )}
        </Card.Body>
      </Card>

      <Card className="app-card">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div className="feed-meta">Showing {samples.length} of {totalCount} samples</div>
            <Pagination className="mb-0">
              <Pagination.Prev disabled={!previousPageUrl || page === 1} onClick={() => setPage((p) => Math.max(1, p - 1))} />
              <Pagination.Item active>{page}</Pagination.Item>
              <Pagination.Next disabled={!nextPageUrl || page >= totalPages} onClick={() => setPage((p) => p + 1)} />
            </Pagination>
          </div>

          {samples.length === 0 ? (
            <div className="empty-state">No samples found.</div>
          ) : (
            <Table responsive hover className="app-table">
              <thead>
                <tr>
                  <th>
                    <Form.Check
                      type="checkbox"
                      checked={samples.length > 0 && selectedIds.length === samples.length}
                      onChange={toggleSelectAll}
                    />
                  </th>
                  <th>ID</th>
                  <th>Sample ID</th>
                  <th>Project</th>
                  <th>Status</th>
                  <th>Container</th>
                  <th>Created At</th>
                </tr>
              </thead>
              <tbody>
                {samples.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <Form.Check
                        type="checkbox"
                        checked={selectedIds.includes(s.id)}
                        onChange={() => toggleSelected(s.id)}
                      />
                    </td>
                    <td>{s.id}</td>
                    <td><Link to={`/samples/${s.id}`}>{s.sample_id}</Link></td>
                    <td>{s.project_code || "-"}</td>
                    <td>{s.status}</td>
                    <td>{s.container_code || "-"}</td>
                    <td>{s.created_at}</td>
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
