import { useEffect, useMemo, useState } from "react";
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

export default function Analyze() {
  const [samples, setSamples] = useState([]);
  const [selectedSampleIds, setSelectedSampleIds] = useState([]);
  const [mode, setMode] = useState("time");
  const [points, setPoints] = useState([]);
  const [loading, setLoading] = useState(true);
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

  async function runAnalysis() {
    setErr("");
    try {
      const selected = samples.filter((s) => selectedSampleIds.includes(String(s.id)));

      const workItemLists = await Promise.all(
        selected.map((s) => apiGet(`/api/work-items/?sample=${s.id}`))
      );

      const extracted = [];

      for (let i = 0; i < selected.length; i++) {
        const sample = selected[i];
        const workItems = workItemLists[i];

        for (const wi of workItems) {
          const concentrationResult = wi.results?.find((r) => r.key === "Concentration");
          if (concentrationResult && concentrationResult.value != null) {
            extracted.push({
              sample_id: sample.sample_id,
              created_at: sample.created_at,
              x_time: new Date(sample.created_at).toLocaleDateString(),
              x_days: daysBetween(sample.created_at, new Date()),
              y: Number(concentrationResult.value),
            });
          }
        }
      }

      setPoints(extracted);
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  const chartData = useMemo(() => {
    return {
      labels: points.map((p) => (mode === "time" ? p.x_time : p.x_days)),
      datasets: [
        {
          label: mode === "time" ? "Concentration vs Time" : "Concentration vs Days",
          data: points.map((p) => p.y),
        },
      ],
    };
  }, [points, mode]);

  const chartOptions = useMemo(() => {
    return {
      responsive: true,
      plugins: {
        legend: { display: true },
      },
      scales: {
        y: {
          beginAtZero: true,
          title: {
            display: true,
            text: "Concentration",
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
  }, [mode]);

  function toggleSample(id) {
    setSelectedSampleIds((prev) =>
      prev.includes(String(id))
        ? prev.filter((x) => x !== String(id))
        : [...prev, String(id)]
    );
  }

  return (
    <div className="w-100">
      <h2 className="mb-3">Analyze</h2>

      {err && <Alert variant="danger">{err}</Alert>}

      {loading ? (
        <Spinner animation="border" />
      ) : (
        <>
          <Card className="shadow-sm border-0 mb-4">
            <Card.Body>
              <Row className="g-3">
                <Col md={8}>
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

                <Col md={4}>
                  <div className="fw-semibold mb-2">Chart Mode</div>
                  <Form.Select value={mode} onChange={(e) => setMode(e.target.value)}>
                    <option value="time">Concentration vs Time</option>
                    <option value="days">Concentration vs Days</option>
                  </Form.Select>

                  <Button className="mt-3 w-100" variant="dark" onClick={runAnalysis}>
                    Run Analysis
                  </Button>
                </Col>
              </Row>
            </Card.Body>
          </Card>

          <Card className="shadow-sm border-0 mb-4">
            <Card.Body>
              <h5 className="mb-3">Chart</h5>
              {points.length === 0 ? (
                <Alert variant="light" className="mb-0">
                  No analysis data yet. Select samples and run analysis.
                </Alert>
              ) : (
                <Line data={chartData} options={chartOptions} />
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
                      <th>Created</th>
                      <th>Days</th>
                      <th>Concentration</th>
                    </tr>
                  </thead>
                  <tbody>
                    {points.map((p, idx) => (
                      <tr key={`${p.sample_id}-${idx}`}>
                        <td>{p.sample_id}</td>
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
        </>
      )}
    </div>
  );
}