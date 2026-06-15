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

function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";
  return number.toFixed(2);
}

function formatShort(value) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return "-";

  if (Math.abs(number) >= 1000000) return number.toExponential(2);
  return number.toFixed(2);
}

function statusVariant(status) {
  if (status === "COMPLETED") return "success";
  if (status === "FAILED") return "danger";
  if (status === "RUNNING") return "info";
  return "secondary";
}

function featureMzSet(run, digits = 1) {
  const values = new Set();

  for (const feature of run.detected_features || []) {
    const mz = Number(feature.mz);

    if (Number.isFinite(mz)) {
      values.add(Number(mz.toFixed(digits)));
    }
  }

  return values;
}

function buildManualComparison(selectedRuns) {
  const featureSets = {};
  const allFeatureMz = new Set();

  for (const run of selectedRuns) {
    const values = featureMzSet(run);
    featureSets[String(run.id)] = values;

    for (const value of values) {
      allFeatureMz.add(value);
    }
  }

  let sharedFeatureMz = [];

  if (selectedRuns.length > 0) {
    const [firstRun, ...restRuns] = selectedRuns;
    const shared = new Set(featureSets[String(firstRun.id)] || []);

    for (const run of restRuns) {
      const current = featureSets[String(run.id)] || new Set();

      for (const value of Array.from(shared)) {
        if (!current.has(value)) {
          shared.delete(value);
        }
      }
    }

    sharedFeatureMz = Array.from(shared).sort((a, b) => a - b);
  }

  const uniqueFeatureMzByRun = {};

  for (const run of selectedRuns) {
    const current = featureSets[String(run.id)] || new Set();
    const others = new Set();

    for (const otherRun of selectedRuns) {
      if (otherRun.id === run.id) continue;

      for (const value of featureSets[String(otherRun.id)] || []) {
        others.add(value);
      }
    }

    uniqueFeatureMzByRun[String(run.id)] = Array.from(current)
      .filter((value) => !others.has(value))
      .sort((a, b) => a - b);
  }

  const totalIonCurrents = selectedRuns
    .map((run) => run.total_ion_current)
    .filter((value) => value !== null && value !== undefined)
    .map(Number)
    .filter(Number.isFinite);

  return {
    count: selectedRuns.length,
    filters: {
      mode: "manual",
    },
    runs: selectedRuns.map((run) => ({
      id: run.id,
      name: run.name,
      status: run.status,
      original_filename: run.original_filename,
      project: run.project,
      project_code: run.project_code,
      sample: run.sample,
      sample_id_value: run.sample_id_value,
      spectra_count: run.spectra_count,
      peak_count: run.peak_count,
      feature_count: run.feature_count,
      protein_count: run.protein_count,
      peptide_count: run.peptide_count,
      base_peak_mz: run.base_peak_mz,
      base_peak_intensity: run.base_peak_intensity,
      total_ion_current: run.total_ion_current,
      mean_total_intensity: run.mean_total_intensity,
      max_total_intensity: run.max_total_intensity,
      rt_span: run.rt_span,
      mz_span: run.mz_span,
      created_at: run.created_at,
      processed_at: run.processed_at,
    })),
    summary: {
      run_count: selectedRuns.length,
      spectra_count_min: Math.min(...selectedRuns.map((run) => Number(run.spectra_count || 0))),
      spectra_count_max: Math.max(...selectedRuns.map((run) => Number(run.spectra_count || 0))),
      peak_count_min: Math.min(...selectedRuns.map((run) => Number(run.peak_count || 0))),
      peak_count_max: Math.max(...selectedRuns.map((run) => Number(run.peak_count || 0))),
      feature_count_min: Math.min(...selectedRuns.map((run) => Number(run.feature_count || 0))),
      feature_count_max: Math.max(...selectedRuns.map((run) => Number(run.feature_count || 0))),
      protein_count_max: Math.max(...selectedRuns.map((run) => Number(run.protein_count || 0))),
      peptide_count_max: Math.max(...selectedRuns.map((run) => Number(run.peptide_count || 0))),
      total_ion_current_min: totalIonCurrents.length ? Math.min(...totalIonCurrents) : null,
      total_ion_current_max: totalIonCurrents.length ? Math.max(...totalIonCurrents) : null,
    },
    feature_overlap: {
      mz_rounding_digits: 1,
      shared_feature_mz: sharedFeatureMz,
      shared_feature_count: sharedFeatureMz.length,
      all_feature_count: allFeatureMz.size,
      unique_feature_mz_by_run: uniqueFeatureMzByRun,
    },
  };
}

function MetricCard({ label, value, note }) {
  return (
    <Card className="app-card metric-card h-100">
      <Card.Body>
        <div className="metric-label">{label}</div>
        <div className="metric-value">{value}</div>
        <div className="metric-note">{note}</div>
      </Card.Body>
    </Card>
  );
}

export default function MassSpecCompare() {
  const [runs, setRuns] = useState([]);
  const [projects, setProjects] = useState([]);
  const [samples, setSamples] = useState([]);

  const [mode, setMode] = useState("project");
  const [project, setProject] = useState("");
  const [sample, setSample] = useState("");
  const [selectedRunIds, setSelectedRunIds] = useState([]);

  const [comparison, setComparison] = useState(null);
  const [loading, setLoading] = useState(true);
  const [comparing, setComparing] = useState(false);
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

  const completedRuns = useMemo(
    () => runs.filter((run) => run.status === "COMPLETED"),
    [runs]
  );

  const selectedRuns = useMemo(() => {
    const selected = new Set(selectedRunIds.map(String));
    return completedRuns.filter((run) => selected.has(String(run.id)));
  }, [completedRuns, selectedRunIds]);

  function toggleRun(id) {
    setSelectedRunIds((current) => {
      const value = String(id);

      if (current.includes(value)) {
        return current.filter((item) => item !== value);
      }

      return [...current, value];
    });
  }

  async function compareRuns() {
    setErr("");
    setComparing(true);

    try {
      if (mode === "project") {
        if (!project) {
          throw new Error("Choose a project to compare.");
        }

        const data = await apiGet(
          `/api/mass-spec-runs/compare/?project=${encodeURIComponent(project)}`
        );
        setComparison(data);
      } else if (mode === "sample") {
        if (!sample) {
          throw new Error("Choose a sample to compare.");
        }

        const data = await apiGet(
          `/api/mass-spec-runs/compare/?sample=${encodeURIComponent(sample)}`
        );
        setComparison(data);
      } else {
        if (selectedRuns.length < 2) {
          throw new Error("Choose at least 2 completed runs for manual comparison.");
        }

        setComparison(buildManualComparison(selectedRuns));
      }
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setComparing(false);
    }
  }

  const rows = comparison?.runs || [];
  const summary = comparison?.summary || {};
  const overlap = comparison?.feature_overlap || {};

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Compare Mass Spec Runs</h1>
          <p className="page-subtitle">
            Compare completed runs by project, sample, or manually selected run sets.
          </p>
        </div>

        <div className="inline-actions">
          <Button as={Link} to="/mass-spec" variant="outline-secondary" size="sm">
            Back to Mass Spec
          </Button>

          <Button variant="outline-dark" size="sm" onClick={load}>
            Refresh
          </Button>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Comparison Setup</h5>
              <div className="feed-meta">
                Choose how users should compare run-level QC, features, and identification results.
              </div>
            </div>

            <Badge bg="dark">{completedRuns.length} completed runs</Badge>
          </div>

          {loading ? (
            <div className="d-flex align-items-center gap-2">
              <Spinner animation="border" size="sm" />
              <span>Loading comparison inputs...</span>
            </div>
          ) : (
            <>
              <Row className="g-3 mb-3">
                <Col md={4}>
                  <Form.Group>
                    <Form.Label>Compare Mode</Form.Label>
                    <Form.Select
                      value={mode}
                      onChange={(e) => {
                        setMode(e.target.value);
                        setComparison(null);
                      }}
                    >
                      <option value="project">By Project</option>
                      <option value="sample">By Sample</option>
                      <option value="manual">Manual Run Selection</option>
                    </Form.Select>
                  </Form.Group>
                </Col>

                {mode === "project" && (
                  <Col md={5}>
                    <Form.Group>
                      <Form.Label>Project</Form.Label>
                      <Form.Select
                        value={project}
                        onChange={(e) => setProject(e.target.value)}
                      >
                        <option value="">Choose project</option>
                        {projects.map((item) => (
                          <option key={item.id} value={item.id}>
                            {item.code || item.name || `Project ${item.id}`}
                          </option>
                        ))}
                      </Form.Select>
                    </Form.Group>
                  </Col>
                )}

                {mode === "sample" && (
                  <Col md={5}>
                    <Form.Group>
                      <Form.Label>Sample</Form.Label>
                      <Form.Select
                        value={sample}
                        onChange={(e) => setSample(e.target.value)}
                      >
                        <option value="">Choose sample</option>
                        {samples.map((item) => (
                          <option key={item.id} value={item.id}>
                            {item.sample_id || `Sample ${item.id}`}
                          </option>
                        ))}
                      </Form.Select>
                    </Form.Group>
                  </Col>
                )}

                <Col md={3} className="d-flex align-items-end">
                  <Button variant="dark" onClick={compareRuns} disabled={comparing}>
                    {comparing ? "Comparing..." : "Run Comparison"}
                  </Button>
                </Col>
              </Row>

              {mode === "manual" && (
                <Card className="border-0 bg-light">
                  <Card.Body>
                    <div className="fw-semibold mb-2">Select Completed Runs</div>

                    {completedRuns.length === 0 ? (
                      <div className="empty-state">No completed runs available.</div>
                    ) : (
                      <div style={{ maxHeight: "280px", overflow: "auto" }}>
                        <Table responsive hover className="app-table align-middle mb-0">
                          <thead>
                            <tr>
                              <th></th>
                              <th>Run</th>
                              <th>Project</th>
                              <th>Sample</th>
                              <th>Features</th>
                              <th>Proteins</th>
                              <th>Peptides</th>
                            </tr>
                          </thead>

                          <tbody>
                            {completedRuns.map((run) => (
                              <tr key={run.id}>
                                <td>
                                  <Form.Check
                                    checked={selectedRunIds.includes(String(run.id))}
                                    onChange={() => toggleRun(run.id)}
                                  />
                                </td>
                                <td>
                                  <Link to={`/mass-spec/${run.id}`}>
                                    {run.name}
                                  </Link>
                                  <div className="feed-meta">
                                    {run.original_filename || "-"}
                                  </div>
                                </td>
                                <td>{run.project_code || "-"}</td>
                                <td>{run.sample_id_value || "-"}</td>
                                <td>{run.feature_count || 0}</td>
                                <td>{run.protein_count || 0}</td>
                                <td>{run.peptide_count || 0}</td>
                              </tr>
                            ))}
                          </tbody>
                        </Table>
                      </div>
                    )}
                  </Card.Body>
                </Card>
              )}
            </>
          )}
        </Card.Body>
      </Card>

      {comparison && (
        <>
          <div className="stat-grid mb-4">
            <MetricCard
              label="Runs Compared"
              value={summary.run_count || comparison.count || 0}
              note="Completed runs in scope"
            />
            <MetricCard
              label="Shared Features"
              value={overlap.shared_feature_count || 0}
              note="Rounded shared m/z values"
            />
            <MetricCard
              label="Max Features"
              value={summary.feature_count_max || 0}
              note="Highest feature count"
            />
            <MetricCard
              label="Max IDs"
              value={`${summary.protein_count_max || 0} / ${
                summary.peptide_count_max || 0
              }`}
              note="Protein / peptide max"
            />
          </div>

          <Card className="app-card mb-4">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <div>
                  <h5 className="section-title mb-0">Run Comparison</h5>
                  <div className="feed-meta">
                    High-level run, peak, feature, and identification comparison.
                  </div>
                </div>

                <Badge bg="dark">{rows.length} runs</Badge>
              </div>

              {rows.length === 0 ? (
                <div className="empty-state">No completed runs found for this comparison.</div>
              ) : (
                <Table responsive hover className="app-table align-middle">
                  <thead>
                    <tr>
                      <th>Run</th>
                      <th>Status</th>
                      <th>Project</th>
                      <th>Sample</th>
                      <th>Spectra</th>
                      <th>Peaks</th>
                      <th>Features</th>
                      <th>Proteins</th>
                      <th>Peptides</th>
                    </tr>
                  </thead>

                  <tbody>
                    {rows.map((run) => (
                      <tr key={run.id}>
                        <td>
                          <Link to={`/mass-spec/${run.id}`}>{run.name}</Link>
                          <div className="feed-meta">
                            {run.original_filename || "-"}
                          </div>
                        </td>
                        <td>
                          <Badge bg={statusVariant(run.status)}>{run.status}</Badge>
                        </td>
                        <td>{run.project_code || "-"}</td>
                        <td>{run.sample_id_value || "-"}</td>
                        <td>{run.spectra_count || 0}</td>
                        <td>{run.peak_count || 0}</td>
                        <td>{run.feature_count || 0}</td>
                        <td>{run.protein_count || 0}</td>
                        <td>{run.peptide_count || 0}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>

          <Card className="app-card mb-4">
            <Card.Body>
              <h5 className="section-title">Quality Metrics</h5>

              <Table responsive hover className="app-table align-middle">
                <thead>
                  <tr>
                    <th>Run</th>
                    <th>Base Peak m/z</th>
                    <th>Base Peak Intensity</th>
                    <th>Total Ion Current</th>
                    <th>Mean Total Intensity</th>
                    <th>Max Total Intensity</th>
                    <th>RT Span</th>
                    <th>m/z Span</th>
                  </tr>
                </thead>

                <tbody>
                  {rows.map((run) => (
                    <tr key={run.id}>
                      <td>
                        <Link to={`/mass-spec/${run.id}`}>{run.name}</Link>
                      </td>
                      <td>{formatNumber(run.base_peak_mz)}</td>
                      <td>{formatShort(run.base_peak_intensity)}</td>
                      <td>{formatShort(run.total_ion_current)}</td>
                      <td>{formatShort(run.mean_total_intensity)}</td>
                      <td>{formatShort(run.max_total_intensity)}</td>
                      <td>{formatNumber(run.rt_span)}</td>
                      <td>{formatNumber(run.mz_span)}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Card.Body>
          </Card>

          <Row className="g-4 mb-4">
            <Col lg={6}>
              <Card className="app-card h-100">
                <Card.Body>
                  <h5 className="section-title">Shared Feature m/z</h5>
                  <div className="feed-meta mb-3">
                    Feature m/z values rounded to {overlap.mz_rounding_digits ?? 1} decimal place.
                  </div>

                  {(overlap.shared_feature_mz || []).length === 0 ? (
                    <div className="empty-state">No shared feature m/z values found.</div>
                  ) : (
                    <div className="d-flex flex-wrap gap-2">
                      {overlap.shared_feature_mz.map((mz) => (
                        <Badge bg="secondary" key={mz}>
                          {mz}
                        </Badge>
                      ))}
                    </div>
                  )}
                </Card.Body>
              </Card>
            </Col>

            <Col lg={6}>
              <Card className="app-card h-100">
                <Card.Body>
                  <h5 className="section-title">Unique Feature m/z by Run</h5>

                  {rows.map((run) => {
                    const values =
                      overlap.unique_feature_mz_by_run?.[String(run.id)] || [];

                    return (
                      <div key={run.id} className="mb-3">
                        <div className="fw-semibold">{run.name}</div>
                        {values.length === 0 ? (
                          <div className="feed-meta">No unique rounded features.</div>
                        ) : (
                          <div className="d-flex flex-wrap gap-2 mt-1">
                            {values.slice(0, 40).map((mz) => (
                              <Badge bg="light" text="dark" key={`${run.id}-${mz}`}>
                                {mz}
                              </Badge>
                            ))}
                            {values.length > 40 && (
                              <Badge bg="secondary">+{values.length - 40} more</Badge>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </Card.Body>
              </Card>
            </Col>
          </Row>
        </>
      )}
    </div>
  );
}
