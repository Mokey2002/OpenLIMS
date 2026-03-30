import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Card, Col, Form, Row, Spinner, Table } from "react-bootstrap";
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

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend);

function daysBetween(start, end) {
  return Math.round((new Date(end) - new Date(start)) / (1000 * 60 * 60 * 24));
}

function isNumericResult(result) {
  if (!result) return false;
  if (result.value_type === "NUMBER") return true;
  return typeof result.value === "number";
}

export default function Analyze() {
  const chartRef = useRef(null);

  const [samples, setSamples] = useState([]);
  const [selectedSampleIds, setSelectedSampleIds] = useState([]);
  const [mode, setMode] = useState("time");
  const [metricKey, setMetricKey] = useState("");
  const [availableMetricKeys, setAvailableMetricKeys] = useState([]);
  const [points, setPoints] = useState([]);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const data = await apiGet("/api/samples/");
        setSamples(data);
      } catch (e) {
        setErr(e.message || String(e));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  function toggleSample(id) {
    setSelectedSampleIds((prev) =>
      prev.includes(String(id))
        ? prev.filter((x) => x !== String(id))
        : [...prev, String(id)]
    );
  }

  async function loadAvailableMetrics() {
    setErr("");

    try {
      const selected = samples.filter((s) => selectedSampleIds.includes(String(s.id)));

      if (selected.length === 0) {
        setAvailableMetricKeys([]);
        setMetricKey("");
        return;
      }

      const workItemLists = await Promise.all(
        selected.map((s) => apiGet(`/api/work-items/?sample=${s.id}`))
      );

      const keys = new Set();

      for (const workItems of workItemLists) {
        for (const wi of workItems) {
          for (const result of wi.results || []) {
            if (isNumericResult(result)) {
              keys.add(result.key);
            }
          }
        }
      }

      const sortedKeys = [...keys].sort();
      setAvailableMetricKeys(sortedKeys);

      if (!sortedKeys.includes(metricKey)) {
        setMetricKey(sortedKeys[0] || "");
      }
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  useEffect(() => {
    loadAvailableMetrics();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedSampleIds, samples]);

  async function runAnalysis() {
    setErr("");
    setAnalyzing(true);

    try {
      const selected = samples.filter((s) => selectedSampleIds.includes(String(s.id)));

      if (selected.length === 0) {
        setPoints([]);
        setErr("Select at least one sample.");
        return;
      }

      if (!metricKey) {
        setPoints([]);
        setErr("No numeric result key found for the selected samples.");
        return;
      }

      const workItemLists = await Promise.all(
        selected.map((s) => apiGet(`/api/work-items/?sample=${s.id}`))
      );

      const extracted = [];

      for (let i = 0; i < selected.length; i++) {
        const sample = selected[i];
        const workItems = workItemLists[i];

        for (const wi of workItems) {
          const metricResult = wi.results?.find((r) => r.key === metricKey);

          if (metricResult && metricResult.value != null && !Number.isNaN(Number(metricResult.value))) {
            extracted.push({
              sample_id: sample.sample_id,
              sample_db_id: sample.id,
              work_item_name: wi.name,
              created_at: sample.created_at,
              x_time: new Date(sample.created_at).toLocaleDateString(),
              x_days: daysBetween(sample.created_at, new Date()),
              y: Number(metricResult.value),
            });
          }
        }
      }

      if (mode === "time") {
        extracted.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
      } else {
        extracted.sort((a, b) => a.x_days - b.x_days);
      }

      setPoints(extracted);

      if (extracted.length === 0) {
        setErr(`No numeric "${metricKey}" values were found for the selected samples.`);
      }
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setAnalyzing(false);
    }
  }

  function downloadChart() {
    const chart = chartRef.current;
    if (!chart) return;

    const url = chart.toBase64Image();
    const link = document.createElement("a");
    link.href = url;
    link.download = `openlims-${metricKey || "analysis"}-chart.png`;
    link.click();
  }

  function downloadCsv() {
    if (points.length === 0) return;

    const rows = [
      ["sample_id", "sample_db_id", "work_item_name", "created_at", "days_since_created", metricKey],
      ...points.map((p) => [
        p.sample_id,
        p.sample_db_id,
        p.work_item_name,
        p.created_at,
        p.x_days,
        p.y,
      ]),
    ];

    const csv = rows.map((row) => row.map(String).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);

    const link = document.createElement("a");
    link.href = url;
    link.download = `openlims-${metricKey || "analysis"}-data.csv`;
    link.click();

    URL.revokeObjectURL(url);
  }

  const chartData = useMemo(() => {
    return {
      labels: points.map((p) => (mode === "time" ? p.x_time : p.x_days)),
      datasets: [
        {
          label:
            mode === "time"
              ? `${metricKey || "Metric"} vs Time`
              : `${metricKey || "Metric"} vs Days`,
          data: points.map((p) => p.y),
        },
      ],
    };
  }, [points, mode, metricKey]);

  const chartOptions = useMemo(() => {
    return {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: true },
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
            text: mode === "time" ? "Created Date" : "Days Since Created",
          },
        },
      },
    };
  }, [mode, metricKey]);

  if (loading) {
    return <Spinner animation="border" />;
  }

  return (
    <div className="w-100">
      <h2 className="mb-3">Analyze</h2>

      {err && <Alert variant="danger">{err}</Alert>}

      <Card className="shadow-sm border-0 mb-4">
        <Card.Body>
          <Row className="g-3">
            <Col md={6}>
              <div className="fw-semibold mb-2">Select Samples</div>
              <div style={{ maxHeight: 220, overflowY: "auto" }}>
                {samples.map((s) => (
                  <Form.Check
                    key={s.id}
                    type="checkbox"
                    label={`${s.sample_id} (${s.status})`}
                    checked={selectedSampleIds.includes(String(s.id))}
                    onChange={() => toggleSample(s.id)}
                  />
                ))}
              </div>
            </Col>

            <Col md={3}>
              <div className="fw-semibold mb-2">Metric</div>
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
            </Col>

            <Col md={3}>
              <div className="fw-semibold mb-2">Chart Mode</div>
              <Form.Select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="time">Metric vs Time</option>
                <option value="days">Metric vs Days</option>
              </Form.Select>

              <Button
                className="mt-3 w-100"
                variant="dark"
                onClick={runAnalysis}
                disabled={analyzing}
              >
                {analyzing ? "Running..." : "Run Analysis"}
              </Button>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      <Card className="shadow-sm border-0 mb-4">
        <Card.Body>
          <div className="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
            <h5 className="mb-0">
              {metricKey
                ? mode === "time"
                  ? `${metricKey} vs Time`
                  : `${metricKey} vs Days`
                : "Chart"}
            </h5>

            <div className="d-flex gap-2">
              <Button variant="outline-dark" size="sm" onClick={downloadChart} disabled={points.length === 0}>
                Download Chart
              </Button>
              <Button variant="outline-secondary" size="sm" onClick={downloadCsv} disabled={points.length === 0}>
                Download CSV
              </Button>
            </div>
          </div>

          {points.length === 0 ? (
            <Alert variant="light" className="mb-0">
              No analysis data yet. Select samples and run analysis.
            </Alert>
          ) : (
            <div style={{ height: "300px" }}>
              <Line ref={chartRef} data={chartData} options={chartOptions} />
            </div>
          )}
        </Card.Body>
      </Card>

      <Card className="shadow-sm border-0">
        <Card.Body>
          <h5 className="mb-3">Data Points</h5>
          {points.length === 0 ? (
            <Alert variant="light" className="mb-0">
              No data points found.
            </Alert>
          ) : (
            <Table responsive hover className="mb-0">
              <thead>
                <tr>
                  <th>Sample</th>
                  <th>Work Item</th>
                  <th>Created</th>
                  <th>Days</th>
                  <th>{metricKey}</th>
                </tr>
              </thead>
              <tbody>
                {points.map((p, idx) => (
                  <tr key={`${p.sample_id}-${p.work_item_name}-${idx}`}>
                    <td>{p.sample_id}</td>
                    <td>{p.work_item_name}</td>
                    <td>{p.x_time}</td>
                    <td>{p.x_days}</td>
                    <td>{p.y}</td>
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