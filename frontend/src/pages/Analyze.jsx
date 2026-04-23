import { useEffect, useMemo, useRef, useState } from "react";
import { Alert, Button, Card, Col, Form, Row, Table } from "react-bootstrap";
import { apiGet } from "../api";
import { Chart as ChartJS, CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend } from "chart.js";
import { Line } from "react-chartjs-2";

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Tooltip, Legend);

function daysBetween(start, end) { return Math.round((new Date(end) - new Date(start)) / (1000 * 60 * 60 * 24)); }
function isNumericResult(result) { if (!result) return false; if (result.value_type === "NUMBER") return true; return typeof result.value === "number"; }
function colorForIndex(i) {
  const palette = ["rgb(54,162,235)","rgb(255,99,132)","rgb(75,192,192)","rgb(255,159,64)","rgb(153,102,255)","rgb(255,205,86)","rgb(201,203,207)"];
  return palette[i % palette.length];
}

export default function Analyze() {
  const chartRef = useRef(null);
  const [samples, setSamples] = useState([]);
  const [projects, setProjects] = useState([]);
  const [projectQuery, setProjectQuery] = useState("");
  const [sampleQuery, setSampleQuery] = useState("");
  const [selectedProjects, setSelectedProjects] = useState([]);
  const [selectedSamples, setSelectedSamples] = useState([]);
  const [mode, setMode] = useState("time");
  const [metricKey, setMetricKey] = useState("");
  const [availableMetricKeys, setAvailableMetricKeys] = useState([]);
  const [points, setPoints] = useState([]);
  const [err, setErr] = useState("");

  async function loadInitial() {
    setErr("");
    try {
      const [samplesData, projectsData] = await Promise.all([apiGet("/api/samples/"), apiGet("/api/projects/")]);
      setSamples(samplesData.results || samplesData || []);
      setProjects(projectsData.results || projectsData || []);
    } catch (e) { setErr(e.message || String(e)); }
  }
  useEffect(() => { loadInitial(); }, []);

  function addProject(project) { setSelectedProjects((prev) => prev.some((p) => p.id === project.id) ? prev : [...prev, project]); setProjectQuery(""); }
  function removeProject(projectId) { setSelectedProjects((prev) => prev.filter((p) => p.id !== projectId)); setSelectedSamples((prev) => prev.filter((s) => s.project_id !== projectId)); }
  function addSample(sample) { setSelectedSamples((prev) => prev.some((s) => s.id === sample.id) ? prev : [...prev, sample]); setSampleQuery(""); }
  function removeSample(sampleId) { setSelectedSamples((prev) => prev.filter((s) => s.id !== sampleId)); }

  const filteredProjects = useMemo(() => {
    const q = projectQuery.trim().toLowerCase();
    if (!q) return [];
    return projects.filter((p) => !selectedProjects.some((sp) => sp.id === p.id)).filter((p) => (p.code || "").toLowerCase().includes(q) || (p.name || "").toLowerCase().includes(q)).slice(0, 10);
  }, [projects, projectQuery, selectedProjects]);

  const projectIdSet = useMemo(() => new Set(selectedProjects.map((p) => p.id)), [selectedProjects]);
  const samplesWithinSelectedProjects = useMemo(() => {
    if (selectedProjects.length === 0) return [];
    return samples.filter((s) => s.project_id && projectIdSet.has(s.project_id));
  }, [samples, selectedProjects, projectIdSet]);

  const filteredSamples = useMemo(() => {
    const q = sampleQuery.trim().toLowerCase();
    if (!q) return [];
    return samplesWithinSelectedProjects.filter((s) => !selectedSamples.some((ss) => ss.id === s.id)).filter((s) => (s.sample_id || "").toLowerCase().includes(q) || (s.project_code || "").toLowerCase().includes(q)).slice(0, 12);
  }, [samplesWithinSelectedProjects, sampleQuery, selectedSamples]);

  async function loadAvailableMetrics() {
    setErr("");
    try {
      if (selectedSamples.length === 0) { setAvailableMetricKeys([]); setMetricKey(""); return; }
      const workItemLists = await Promise.all(selectedSamples.map((s) => apiGet(`/api/work-items/?sample=${s.id}`)));
      const keys = new Set();
      for (const resp of workItemLists) {
        const workItems = resp.results || resp || [];
        for (const wi of workItems) {
          for (const result of wi.results || []) if (isNumericResult(result)) keys.add(result.key);
        }
      }
      const sorted = [...keys].sort();
      setAvailableMetricKeys(sorted);
      if (!sorted.includes(metricKey)) setMetricKey(sorted[0] || "");
    } catch (e) { setErr(e.message || String(e)); }
  }
  useEffect(() => { loadAvailableMetrics(); }, [selectedSamples]);

  async function runAnalysis() {
    setErr("");
    try {
      if (selectedSamples.length === 0) { setPoints([]); setErr("Select at least one sample."); return; }
      if (!metricKey) { setPoints([]); setErr("No numeric result key found for the selected samples."); return; }
      const workItemLists = await Promise.all(selectedSamples.map((s) => apiGet(`/api/work-items/?sample=${s.id}`)));
      const extracted = [];
      for (let i = 0; i < selectedSamples.length; i++) {
        const sample = selectedSamples[i];
        const workItems = workItemLists[i].results || workItemLists[i] || [];
        for (const wi of workItems) {
          const metricResult = wi.results?.find((r) => r.key === metricKey);
          if (metricResult && metricResult.value != null && !Number.isNaN(Number(metricResult.value))) {
            extracted.push({ sample_id: sample.sample_id, project_id: sample.project_id, project_code: sample.project_code, work_item_name: wi.name, created_at: sample.created_at, x_time: new Date(sample.created_at).toLocaleDateString(), x_days: daysBetween(sample.created_at, new Date()), y: Number(metricResult.value) });
          }
        }
      }
      if (mode === "time") extracted.sort((a, b) => new Date(a.created_at) - new Date(b.created_at)); else extracted.sort((a, b) => a.x_days - b.x_days);
      setPoints(extracted);
      if (extracted.length === 0) setErr(`No numeric "${metricKey}" values were found.`);
    } catch (e) { setErr(e.message || String(e)); }
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
    const rows = [["sample_id","project_code","work_item_name","created_at","days_since_created",metricKey], ...points.map((p) => [p.sample_id,p.project_code,p.work_item_name,p.created_at,p.x_days,p.y])];
    const csv = rows.map((r) => r.map(String).join(",")).join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `openlims-${metricKey || "analysis"}-data.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  const chartData = useMemo(() => {
    const grouped = {};
    for (const p of points) {
      const projectKey = p.project_code || "NO_PROJECT";
      const xKey = mode === "time" ? p.x_time : String(p.x_days);
      if (!grouped[projectKey]) grouped[projectKey] = {};
      if (!grouped[projectKey][xKey]) grouped[projectKey][xKey] = [];
      grouped[projectKey][xKey].push(p.y);
    }
    const datasets = Object.entries(grouped).map(([projectCode, xBuckets], idx) => {
      const color = colorForIndex(idx);
      const data = Object.entries(xBuckets).map(([x, ys]) => ({ x: mode === "time" ? x : Number(x), y: ys.reduce((sum, v) => sum + v, 0) / ys.length })).sort((a, b) => mode === "time" ? new Date(a.x) - new Date(b.x) : a.x - b.x);
      return { label: projectCode, data, borderColor: color, backgroundColor: color, tension: 0.2, fill: false };
    });
    return { datasets };
  }, [points, mode]);

  const chartOptions = useMemo(() => ({
    responsive: true, maintainAspectRatio: false, parsing: true,
    plugins: { legend: { display: true } },
    scales: {
      y: { beginAtZero: true, title: { display: true, text: metricKey || "Value" } },
      x: { type: mode === "days" ? "linear" : "category", title: { display: true, text: mode === "time" ? "Created Date" : "Days Since Created" } },
    },
  }), [mode, metricKey]);

  return (
    <div className="w-100">
      <div className="page-header"><div><h1 className="page-title">Analyze</h1><p className="page-subtitle">Compare sample metrics across projects and time.</p></div></div>
      {err && <Alert variant="danger">{err}</Alert>}

      <div className="row g-4 mb-4">
        <div className="col-lg-6">
          <Card className="app-card h-100"><Card.Body>
            <h5 className="section-title">Select Projects</h5>
            <Form.Control placeholder="Search project by name or code" value={projectQuery} onChange={(e) => setProjectQuery(e.target.value)} />
            {projectQuery && (
              <Card className="app-card mt-3"><Card.Body>
                {filteredProjects.length === 0 ? <div className="empty-state">No matching projects.</div> : (
                  <div className="d-grid gap-2">
                    {filteredProjects.map((p) => (
                      <div key={p.id} className="d-flex justify-content-between align-items-center soft-card">
                        <div><div className="fw-semibold">{p.code} - {p.name}</div><div className="feed-meta">{p.description || "-"}</div></div>
                        <Button size="sm" variant="outline-dark" onClick={() => addProject(p)}>Add</Button>
                      </div>
                    ))}
                  </div>
                )}
              </Card.Body></Card>
            )}
            <div className="mt-3 d-flex flex-wrap gap-2">
              {selectedProjects.length === 0 ? <div className="empty-state">No projects selected yet.</div> : selectedProjects.map((p) => <span key={p.id} className="click-chip">{p.code}<button type="button" onClick={() => removeProject(p.id)}>×</button></span>)}
            </div>
          </Card.Body></Card>
        </div>

        <div className="col-lg-6">
          <Card className="app-card h-100"><Card.Body>
            <h5 className="section-title">Select Samples</h5>
            <Form.Control placeholder="Search sample by ID within selected projects" value={sampleQuery} onChange={(e) => setSampleQuery(e.target.value)} disabled={selectedProjects.length === 0} />
            {sampleQuery && selectedProjects.length > 0 && (
              <Card className="app-card mt-3"><Card.Body>
                {filteredSamples.length === 0 ? <div className="empty-state">No matching samples.</div> : (
                  <div className="d-grid gap-2">
                    {filteredSamples.map((s) => (
                      <div key={s.id} className="d-flex justify-content-between align-items-center soft-card">
                        <div><div className="fw-semibold">{s.sample_id}</div><div className="feed-meta">{s.project_code || "No Project"} • {s.status}</div></div>
                        <Button size="sm" variant="outline-dark" onClick={() => addSample(s)}>Add</Button>
                      </div>
                    ))}
                  </div>
                )}
              </Card.Body></Card>
            )}
            <div className="mt-3 d-flex flex-wrap gap-2">
              {selectedSamples.length === 0 ? <div className="empty-state">No samples selected yet.</div> : selectedSamples.map((s) => <span key={s.id} className="click-chip">{s.sample_id}<button type="button" onClick={() => removeSample(s.id)}>×</button></span>)}
            </div>
          </Card.Body></Card>
        </div>
      </div>

      <Card className="app-card mb-4"><Card.Body>
        <Row className="g-3">
          <Col md={4}><div className="feed-meta mb-2">Metric</div><Form.Select value={metricKey} onChange={(e) => setMetricKey(e.target.value)} disabled={availableMetricKeys.length === 0}>{availableMetricKeys.length === 0 ? <option value="">No numeric metrics found</option> : availableMetricKeys.map((key) => <option key={key} value={key}>{key}</option>)}</Form.Select></Col>
          <Col md={4}><div className="feed-meta mb-2">Chart Mode</div><Form.Select value={mode} onChange={(e) => setMode(e.target.value)}><option value="time">Metric vs Time</option><option value="days">Metric vs Days</option></Form.Select></Col>
          <Col md={4} className="d-flex align-items-end"><Button className="w-100" variant="dark" onClick={runAnalysis}>Run Analysis</Button></Col>
        </Row>
      </Card.Body></Card>

      <Card className="app-card mb-4"><Card.Body>
        <div className="toolbar-row mb-3">
          <h5 className="section-title mb-0">{metricKey ? `${metricKey} Analysis` : "Chart"}</h5>
          <div className="inline-actions">
            <Button variant="outline-dark" size="sm" onClick={downloadChart} disabled={points.length === 0}>Download Chart</Button>
            <Button variant="outline-secondary" size="sm" onClick={downloadCsv} disabled={points.length === 0}>Download CSV</Button>
          </div>
        </div>
        {points.length === 0 ? <div className="empty-state">No analysis data yet. Select projects, select samples, and run analysis.</div> : <div style={{ height: "320px" }}><Line ref={chartRef} data={chartData} options={chartOptions} /></div>}
      </Card.Body></Card>

      <Card className="app-card"><Card.Body>
        <h5 className="section-title">Data Points</h5>
        {points.length === 0 ? <div className="empty-state">No data points found.</div> : (
          <Table responsive hover className="app-table">
            <thead><tr><th>Sample</th><th>Project</th><th>Work Item</th><th>Created</th><th>Days</th><th>{metricKey}</th></tr></thead>
            <tbody>
              {points.map((p, idx) => (
                <tr key={`${p.sample_id}-${p.work_item_name}-${idx}`}>
                  <td>{p.sample_id}</td><td>{p.project_code || "-"}</td><td>{p.work_item_name}</td><td>{p.x_time}</td><td>{p.x_days}</td><td>{p.y}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card.Body></Card>
    </div>
  );
}
