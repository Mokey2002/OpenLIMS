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
import { Link } from "react-router-dom";
import { apiGet } from "../api";
import { getAccessToken } from "../auth";

function statusVariant(status) {
  if (status === "COMPLETED") return "success";
  if (status === "FAILED") return "danger";
  if (status === "RUNNING") return "info";
  return "secondary";
}

function formatNumber(value) {
  if (value === null || value === undefined) return "-";
  return Number(value).toFixed(2);
}

export default function MassSpec() {
  const [runs, setRuns] = useState([]);
  const [projects, setProjects] = useState([]);
  const [samples, setSamples] = useState([]);

  const [form, setForm] = useState({
    name: "",
    project: "",
    sample: "",
    uploaded_file: null,
  });

  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [err, setErr] = useState("");

  async function load() {
    setErr("");
    setLoading(true);

    try {
      const [runsData, projectsData, samplesData] = await Promise.all([
        apiGet("/api/mass-spec-runs/"),
        apiGet("/api/projects/"),
        apiGet("/api/samples/"),
      ]);

      setRuns(runsData.results || runsData || []);
      setProjects(projectsData.results || projectsData || []);
      setSamples(samplesData.results || samplesData || []);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const stats = useMemo(() => {
    const completed = runs.filter((run) => run.status === "COMPLETED").length;
    const failed = runs.filter((run) => run.status === "FAILED").length;
    const running = runs.filter((run) => run.status === "RUNNING").length;

    return {
      total: runs.length,
      completed,
      failed,
      running,
      spectra: runs.reduce(
        (total, run) => total + Number(run.spectra_count || 0),
        0
      ),
    };
  }, [runs]);

  function updateForm(field, value) {
    setForm((current) => ({
      ...current,
      [field]: value,
    }));
  }

  async function uploadRun(e) {
    e.preventDefault();
    setErr("");

    if (!form.name.trim()) {
      setErr("Name is required.");
      return;
    }

    if (!form.uploaded_file) {
      setErr("Mass spec file is required.");
      return;
    }

    setUploading(true);

    try {
      const token = getAccessToken();
      const body = new FormData();

      body.append("name", form.name);
      body.append("uploaded_file", form.uploaded_file);

      if (form.project) body.append("project", form.project);
      if (form.sample) body.append("sample", form.sample);

      const response = await fetch("/api/mass-spec-runs/", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
        body,
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || `Upload failed with status ${response.status}`);
      }

      setForm({
        name: "",
        project: "",
        sample: "",
        uploaded_file: null,
      });

      e.target.reset();
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setUploading(false);
    }
  }

  async function reprocessRun(id) {
    setErr("");

    try {
      const token = getAccessToken();

      const response = await fetch(`/api/mass-spec-runs/${id}/reprocess/`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });

      if (!response.ok) {
        throw new Error(`Reprocess failed with status ${response.status}`);
      }

      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Mass Spec</h1>
          <p className="page-subtitle">
            Upload mzML, mzXML, or mzData files and process basic metadata with
            pyOpenMS.
          </p>
        </div>

        <Button variant="outline-dark" size="sm" onClick={load}>
          Refresh
        </Button>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      <div className="stat-grid mb-4">
        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Runs</div>
            <div className="metric-value">{stats.total}</div>
            <div className="metric-note">Total uploaded runs</div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Completed</div>
            <div className="metric-value">{stats.completed}</div>
            <div className="metric-note">Processed successfully</div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Failed</div>
            <div className="metric-value">{stats.failed}</div>
            <div className="metric-note">Needs review or reprocess</div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Spectra</div>
            <div className="metric-value">{stats.spectra}</div>
            <div className="metric-note">Total spectra extracted</div>
          </Card.Body>
        </Card>
      </div>

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Upload Mass Spec Run</h5>

          <Form onSubmit={uploadRun}>
            <Row className="g-3">
              <Col md={4}>
                <Form.Group>
                  <Form.Label>Run Name</Form.Label>
                  <Form.Control
                    value={form.name}
                    onChange={(e) => updateForm("name", e.target.value)}
                    placeholder="Example: LCMS Run 001"
                  />
                </Form.Group>
              </Col>

              <Col md={4}>
                <Form.Group>
                  <Form.Label>Project</Form.Label>
                  <Form.Select
                    value={form.project}
                    onChange={(e) => updateForm("project", e.target.value)}
                  >
                    <option value="">No project</option>
                    {projects.map((project) => (
                      <option key={project.id} value={project.id}>
                        {project.code || project.name}
                      </option>
                    ))}
                  </Form.Select>
                </Form.Group>
              </Col>

              <Col md={4}>
                <Form.Group>
                  <Form.Label>Sample</Form.Label>
                  <Form.Select
                    value={form.sample}
                    onChange={(e) => updateForm("sample", e.target.value)}
                  >
                    <option value="">No sample</option>
                    {samples.map((sample) => (
                      <option key={sample.id} value={sample.id}>
                        {sample.sample_id}
                      </option>
                    ))}
                  </Form.Select>
                </Form.Group>
              </Col>

              <Col md={8}>
                <Form.Group>
                  <Form.Label>Mass Spec File</Form.Label>
                  <Form.Control
                    type="file"
                    accept=".mzML,.mzml,.mzXML,.mzxml,.mzData,.mzdata"
                    onChange={(e) =>
                      updateForm("uploaded_file", e.target.files?.[0] || null)
                    }
                  />
                </Form.Group>
              </Col>

              <Col md={4} className="d-flex align-items-end">
                <Button type="submit" variant="dark" disabled={uploading}>
                  {uploading ? "Uploading..." : "Upload and Process"}
                </Button>
              </Col>
            </Row>
          </Form>
        </Card.Body>
      </Card>

      <Card className="app-card">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Mass Spec Runs</h5>
              <div className="feed-meta">
                pyOpenMS summaries generated from uploaded files.
              </div>
            </div>
          </div>

          {loading ? (
            <div className="d-flex align-items-center gap-2">
              <Spinner animation="border" size="sm" />
              <span>Loading mass spec runs...</span>
            </div>
          ) : runs.length === 0 ? (
            <div className="empty-state">No mass spec runs yet.</div>
          ) : (
            <Table responsive hover className="app-table align-middle">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Project</th>
                  <th>Sample</th>
                  <th>Spectra</th>
                  <th>MS1</th>
                  <th>MS2</th>
                  <th>RT Range</th>
                  <th>m/z Range</th>
                  <th>Error</th>
                  <th></th>
                </tr>
              </thead>

              <tbody>
                {runs.map((run) => (
                  <tr key={run.id}>
                    <td>
                      <div className="fw-semibold">
                        <Link to={`/mass-spec/${run.id}`}>{run.name}</Link>
                      </div>
                      <div className="feed-meta">{run.original_filename}</div>
                    </td>

                    <td>
                      <Badge bg={statusVariant(run.status)}>{run.status}</Badge>
                    </td>

                    <td>{run.project_code || "-"}</td>
                    <td>{run.sample_id_value || "-"}</td>
                    <td>{run.spectra_count}</td>
                    <td>{run.ms1_count}</td>
                    <td>{run.ms2_count}</td>
                    <td>
                      {formatNumber(run.rt_min)} – {formatNumber(run.rt_max)}
                    </td>
                    <td>
                      {formatNumber(run.mz_min)} – {formatNumber(run.mz_max)}
                    </td>
                    <td style={{ maxWidth: "260px" }}>
                      {run.error_message ? (
                        <span className="text-danger">View details</span>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td>
                      <div className="d-flex gap-2">
                        <Button
                          as={Link}
                          to={`/mass-spec/${run.id}`}
                          size="sm"
                          variant="outline-dark"
                        >
                          Details
                        </Button>

                        <Button
                          size="sm"
                          variant="outline-secondary"
                          onClick={() => reprocessRun(run.id)}
                        >
                          Reprocess
                        </Button>
                      </div>
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
