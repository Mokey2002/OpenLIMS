import { useEffect, useMemo, useRef, useState } from "react";
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
import { apiGet } from "../api";
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Legend,
} from "chart.js";
import { Line } from "react-chartjs-2";

ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Tooltip,
  Legend
);

function formatTimestamp(ts) {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function isNumericResult(result) {
  if (!result) return false;
  if (result.value_type === "NUMBER") return true;
  return result.value !== null && result.value !== "" && !Number.isNaN(Number(result.value));
}

function getResultValue(result) {
  if (!result) return null;
  const value = Number(result.value);
  return Number.isNaN(value) ? null : value;
}

function inferStatus(row) {
  const key = (row.metric || "").toLowerCase();

  if (key.includes("purity") && row.value < 0.8) {
    return "Needs Review";
  }

  if (key.includes("yield") && row.value < 20) {
    return "Needs Review";
  }

  if (key.includes("qc") && String(row.rawValue).toLowerCase().includes("fail")) {
    return "Needs Review";
  }

  return "OK";
}

function SummaryCard({ label, value, note }) {
  return (
    <Card className="app-card metric-card h-100">
      <Card.Body>
        <div className="metric-label">{label}</div>
        <div className="metric-value">{value}</div>
        {note ? <div className="metric-note">{note}</div> : null}
      </Card.Body>
    </Card>
  );
}

export default function Analyze() {
  const chartRef = useRef(null);

  const [samples, setSamples] = useState([]);
  const [projects, setProjects] = useState([]);
  const [workItemsBySample, setWorkItemsBySample] = useState({});

  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [metricKey, setMetricKey] = useState("");
  const [availableMetricKeys, setAvailableMetricKeys] = useState([]);

  const [rows, setRows] = useState([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  async function loadInitial() {
    setErr("");

    try {
      const [samplesData, projectsData] = await Promise.all([
        apiGet("/api/samples/"),
        apiGet("/api/projects/"),
      ]);

      const loadedSamples = samplesData.results || samplesData || [];
      const loadedProjects = projectsData.results || projectsData || [];

      setSamples(loadedSamples);
      setProjects(loadedProjects);

      if (loadedProjects.length > 0) {
        setSelectedProjectId(String(loadedProjects[0].id));
      }
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  useEffect(() => {
    loadInitial();
  }, []);

  const selectedProject = useMemo(() => {
    return projects.find((project) => String(project.id) === String(selectedProjectId));
  }, [projects, selectedProjectId]);

  const projectSamples = useMemo(() => {
    if (!selectedProjectId) return [];

    return samples
      .filter((sample) => String(sample.project_id) === String(selectedProjectId))
      .sort((a, b) => {
        const aId = a.sample_id || "";
        const bId = b.sample_id || "";
        return aId.localeCompare(bId, undefined, { numeric: true });
      });
  }, [samples, selectedProjectId]);

  async function loadWorkItemsForProject() {
    setErr("");
    setLoading(true);

    try {
      if (projectSamples.length === 0) {
        setWorkItemsBySample({});
        setAvailableMetricKeys([]);
        setMetricKey("");
        setRows([]);
        return;
      }

      const responses = await Promise.all(
        projectSamples.map((sample) => apiGet(`/api/work-items/?sample=${sample.id}`))
      );

      const nextWorkItemsBySample = {};
      const metricKeys = new Set();

      for (let i = 0; i < projectSamples.length; i++) {
        const sample = projectSamples[i];
        const workItems = responses[i].results || responses[i] || [];

        nextWorkItemsBySample[sample.id] = workItems;

        for (const workItem of workItems) {
          for (const result of workItem.results || []) {
            if (isNumericResult(result)) {
              metricKeys.add(result.key);
            }
          }
        }
      }

      const sortedKeys = [...metricKeys].sort();

      setWorkItemsBySample(nextWorkItemsBySample);
      setAvailableMetricKeys(sortedKeys);

      if (!sortedKeys.includes(metricKey)) {
        setMetricKey(sortedKeys[0] || "");
      }
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadWorkItemsForProject();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProjectId, projectSamples.length]);

  function runAnalysis() {
    setErr("");

    if (!selectedProjectId) {
      setRows([]);
      setErr("Select a project first.");
      return;
    }

    if (projectSamples.length === 0) {
      setRows([]);
      setErr("No samples found for this project.");
      return;
    }

    if (!metricKey) {
      setRows([]);
      setErr("No numeric metrics found for this project.");
      return;
    }

    const extracted = [];

    for (const sample of projectSamples) {
      const workItems = workItemsBySample[sample.id] || [];

      for (const workItem of workItems) {
        const metricResult = (workItem.results || []).find(
          (result) => result.key === metricKey
        );

        if (!metricResult) continue;

        const value = getResultValue(metricResult);

        if (value === null) continue;

        extracted.push({
          sampleId: sample.id,
          sampleCode: sample.sample_id,
          sampleStatus: sample.status,
          projectId: sample.project_id,
          projectCode: sample.project_code,
          workItemName: workItem.name,
          metric: metricKey,
          value,
          rawValue: metricResult.value,
          unit: metricResult.unit || "",
          createdAt: sample.created_at,
        });
      }
    }

    const sortedRows = extracted.sort((a, b) =>
      a.sampleCode.localeCompare(b.sampleCode, undefined, { numeric: true })
    );

    setRows(sortedRows);

    if (sortedRows.length === 0) {
      setErr(`No numeric "${metricKey}" values were found for this project.`);
    }
  }

  useEffect(() => {
    if (metricKey && Object.keys(workItemsBySample).length > 0) {
      runAnalysis();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metricKey, workItemsBySample]);

  const sampleTrendRows = useMemo(() => {
    const grouped = {};

    for (const row of rows) {
      if (!grouped[row.sampleCode]) {
        grouped[row.sampleCode] = [];
      }

      grouped[row.sampleCode].push(row.value);
    }

    return Object.entries(grouped).map(([sampleCode, values]) => ({
      sampleCode,
      value: values.reduce((sum, value) => sum + value, 0) / values.length,
    }));
  }, [rows]);

  const labels = sampleTrendRows.map((row) => row.sampleCode);

  const chartData = useMemo(() => {
    return {
      labels,
      datasets: [
        {
          label: metricKey || "Metric",
          data: sampleTrendRows.map((row) => row.value),
          borderWidth: 3,
          pointRadius: 5,
          pointHoverRadius: 7,
          tension: 0.3,
          fill: false,
        },
      ],
    };
  }, [labels, metricKey, sampleTrendRows]);

  const chartOptions = useMemo(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: true,
          position: "top",
        },
        tooltip: {
          callbacks: {
            label: (context) => `${metricKey}: ${context.parsed.y}`,
          },
        },
      },
      scales: {
        y: {
          beginAtZero: true,
          title: {
            display: true,
            text: metricKey || "Value",
          },
        },
        x: {
          title: {
            display: true,
            text: "Sample",
          },
        },
      },
    }),
    [metricKey]
  );

  const numericValues = rows.map((row) => row.value);
  const averageValue =
    numericValues.length > 0
      ? numericValues.reduce((sum, value) => sum + value, 0) / numericValues.length
      : 0;

  const minValue = numericValues.length > 0 ? Math.min(...numericValues) : 0;
  const maxValue = numericValues.length > 0 ? Math.max(...numericValues) : 0;

  const qcRows = useMemo(() => {
    return rows
      .map((row) => ({
        ...row,
        reviewStatus: inferStatus(row),
      }))
      .filter((row) => row.reviewStatus === "Needs Review");
  }, [rows]);

  function downloadChart() {
    const chart = chartRef.current;

    if (!chart) return;

    const url = chart.toBase64Image();
    const link = document.createElement("a");

    link.href = url;
    link.download = `openlims-${metricKey || "analysis"}-trend.png`;
    link.click();
  }

  function downloadCsv() {
    if (rows.length === 0) return;

    const csvRows = [
      ["sample_id", "project_code", "work_item_name", "metric", "value", "unit", "created_at"],
      ...rows.map((row) => [
        row.sampleCode,
        row.projectCode || "",
        row.workItemName,
        row.metric,
        row.value,
        row.unit,
        row.createdAt,
      ]),
    ];

    const csv = csvRows
      .map((row) =>
        row
          .map((cell) => `"${String(cell ?? "").replaceAll('"', '""')}"`)
          .join(",")
      )
      .join("\n");

    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");

    link.href = url;
    link.download = `openlims-${metricKey || "analysis"}-data.csv`;
    link.click();

    URL.revokeObjectURL(url);
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Analyze</h1>
          <p className="page-subtitle">
            Review result trends across samples in a project.
          </p>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      <Card className="app-card mb-4">
        <Card.Body>
          <Row className="g-3 align-items-end">
            <Col lg={5}>
              <Form.Group>
                <Form.Label>Project</Form.Label>
                <Form.Select
                  value={selectedProjectId}
                  onChange={(e) => {
                    setSelectedProjectId(e.target.value);
                    setRows([]);
                  }}
                >
                  <option value="">Select project</option>

                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.code} — {project.name}
                    </option>
                  ))}
                </Form.Select>
              </Form.Group>
            </Col>

            <Col lg={4}>
              <Form.Group>
                <Form.Label>Metric</Form.Label>
                <Form.Select
                  value={metricKey}
                  onChange={(e) => setMetricKey(e.target.value)}
                  disabled={availableMetricKeys.length === 0}
                >
                  {availableMetricKeys.length === 0 ? (
                    <option value="">No numeric metrics found</option>
                  ) : (
                    availableMetricKeys.map((key) => (
                      <option key={key} value={key}>
                        {key}
                      </option>
                    ))
                  )}
                </Form.Select>
              </Form.Group>
            </Col>

            <Col lg={3}>
              <Button
                className="w-100"
                variant="dark"
                onClick={runAnalysis}
                disabled={loading || !selectedProjectId || !metricKey}
              >
                {loading ? "Loading..." : "Run Analysis"}
              </Button>
            </Col>
          </Row>

          <div className="feed-meta mt-3">
            {selectedProject ? (
              <>
                Analyzing {projectSamples.length} samples from{" "}
                <strong>{selectedProject.code}</strong>.
              </>
            ) : (
              "Select a project to begin."
            )}
          </div>
        </Card.Body>
      </Card>

      <div className="stat-grid mb-4">
        <SummaryCard
          label="Samples"
          value={projectSamples.length}
          note={selectedProject?.code || "No project selected"}
        />

        <SummaryCard
          label="Data Points"
          value={rows.length}
          note={metricKey || "No metric selected"}
        />

        <SummaryCard
          label="Average"
          value={rows.length ? averageValue.toFixed(2) : "-"}
          note={`Min ${rows.length ? minValue.toFixed(2) : "-"} / Max ${
            rows.length ? maxValue.toFixed(2) : "-"
          }`}
        />

        <SummaryCard
          label="QC Review"
          value={qcRows.length}
          note="Values below demo thresholds"
        />
      </div>

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">
                {metricKey ? `${metricKey} Trend` : "Metric Trend"}
              </h5>
              <div className="feed-meta">
                Line chart across sample IDs, making the trend easier to see.
              </div>
            </div>

            <div className="inline-actions">
              <Button
                variant="outline-dark"
                size="sm"
                onClick={downloadChart}
                disabled={rows.length === 0}
              >
                Download Chart
              </Button>

              <Button
                variant="outline-secondary"
                size="sm"
                onClick={downloadCsv}
                disabled={rows.length === 0}
              >
                Download CSV
              </Button>
            </div>
          </div>

          {rows.length === 0 ? (
            <div className="empty-state">
              No analysis data yet. Select a project and metric, then run
              analysis.
            </div>
          ) : (
            <div style={{ height: "380px" }}>
              <Line ref={chartRef} data={chartData} options={chartOptions} />
            </div>
          )}
        </Card.Body>
      </Card>

      <div className="row g-4 mb-4">
        <div className="col-lg-5">
          <Card className="app-card h-100">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">QC Review</h5>
                <Badge bg={qcRows.length ? "warning" : "success"}>
                  {qcRows.length}
                </Badge>
              </div>

              {qcRows.length === 0 ? (
                <div className="empty-state">
                  No QC review items detected for the selected metric.
                </div>
              ) : (
                <Table responsive hover className="app-table">
                  <thead>
                    <tr>
                      <th>Sample</th>
                      <th>Metric</th>
                      <th>Value</th>
                      <th>Status</th>
                    </tr>
                  </thead>

                  <tbody>
                    {qcRows.map((row, index) => (
                      <tr key={`${row.sampleCode}-${row.metric}-${index}`}>
                        <td>{row.sampleCode}</td>
                        <td>{row.metric}</td>
                        <td>
                          {row.value}
                          {row.unit ? ` ${row.unit}` : ""}
                        </td>
                        <td>
                          <Badge bg="warning" text="dark">
                            Needs Review
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </div>

        <div className="col-lg-7">
          <Card className="app-card h-100">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">Samples in Project</h5>
                <Badge bg="dark">{projectSamples.length}</Badge>
              </div>

              {projectSamples.length === 0 ? (
                <div className="empty-state">
                  No samples found for the selected project.
                </div>
              ) : (
                <Table responsive hover className="app-table">
                  <thead>
                    <tr>
                      <th>Sample</th>
                      <th>Status</th>
                      <th>Project</th>
                      <th>Created</th>
                    </tr>
                  </thead>

                  <tbody>
                    {projectSamples.map((sample) => (
                      <tr key={sample.id}>
                        <td>{sample.sample_id}</td>
                        <td>{sample.status}</td>
                        <td>{sample.project_code || "-"}</td>
                        <td>{formatTimestamp(sample.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </div>
      </div>

      <Card className="app-card">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <h5 className="section-title mb-0">Result Values</h5>
            <Badge bg="dark">{rows.length}</Badge>
          </div>

          {rows.length === 0 ? (
            <div className="empty-state">No result values found.</div>
          ) : (
            <Table responsive hover className="app-table">
              <thead>
                <tr>
                  <th>Sample</th>
                  <th>Project</th>
                  <th>Work Item</th>
                  <th>Metric</th>
                  <th>Value</th>
                  <th>Unit</th>
                  <th>Created</th>
                </tr>
              </thead>

              <tbody>
                {rows.map((row, index) => (
                  <tr key={`${row.sampleCode}-${row.workItemName}-${index}`}>
                    <td>{row.sampleCode}</td>
                    <td>{row.projectCode || "-"}</td>
                    <td>{row.workItemName}</td>
                    <td>{row.metric}</td>
                    <td>{row.value}</td>
                    <td>{row.unit || "-"}</td>
                    <td>{formatTimestamp(row.createdAt)}</td>
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