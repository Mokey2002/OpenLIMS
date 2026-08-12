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
} from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiDownload, apiGetAll, apiPost } from "../api";
import AssistantChart from "../components/AssistantChart";
import ComparisonTable from "../components/ComparisonTable";
import ConfirmedOperationCard from "../components/ConfirmedOperationCard";
import useConfirmedOperation from "../hooks/useConfirmedOperation";
import { OPENLIMS_VERSION } from "../version";

const ANALYSES = [
  ["compare", "Compare records"],
  ["trend", "Graph result trends"],
  ["outliers", "Find unusual results"],
  ["bottleneck", "Find workflow bottlenecks"],
];

const METRICS = [
  ["overview", "Automatic overview"],
  ["status", "Sample statuses"],
  ["qc", "QC pass/failure rates"],
  ["work", "Open, overdue and unassigned work"],
  ["turnaround", "Turnaround time"],
  ["metadata", "Metadata completeness"],
  ["results", "Numeric results"],
];

function optionValue(kind, row) {
  return kind === "sample" ? row.sample_id : row.code;
}

function optionLabel(kind, row) {
  if (kind === "sample") {
    return `${row.sample_id} — ${row.project_code || "No project"} — ${row.status}`;
  }
  if (kind === "project") {
    return `${row.code} — ${row.name}`;
  }
  return `${row.code}${row.project_code ? ` — ${row.project_code}` : ""}`;
}

function allowedKinds(analysis) {
  if (analysis === "trend") {
    return [["project", "Projects"], ["sample", "Samples"]];
  }
  if (analysis === "bottleneck") {
    return [["project", "Projects"], ["batch", "Batches"]];
  }
  return [
    ["sample", "Samples"],
    ["project", "Projects"],
    ["batch", "Batches"],
  ];
}

export default function Comparisons() {
  const [analysis, setAnalysis] = useState("compare");
  const [kind, setKind] = useState("sample");
  const [selected, setSelected] = useState([]);
  const [days, setDays] = useState("");
  const [metric, setMetric] = useState("overview");
  const [resultKey, setResultKey] = useState("");
  const [search, setSearch] = useState("");
  const [sources, setSources] = useState({ sample: [], project: [], batch: [] });
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  const exportOperation = useConfirmedOperation(async (action) => {
    const downloadUrl = action.result?.download_url;
    if (downloadUrl) {
      await apiDownload(downloadUrl, "openlims-comparison");
    }
  });

  useEffect(() => {
    (async () => {
      try {
        const [samples, projects, batches] = await Promise.all([
          apiGetAll("/api/samples/"),
          apiGetAll("/api/projects/"),
          apiGetAll("/api/sample-batches/"),
        ]);
        setSources({ sample: samples, project: projects, batch: batches });
      } catch (requestError) {
        setError(requestError.message || String(requestError));
      } finally {
        setLoadingOptions(false);
      }
    })();
  }, []);

  const visibleOptions = useMemo(() => {
    const query = search.trim().toLowerCase();
    const rows = sources[kind] || [];
    if (!query) return rows;
    return rows.filter((row) =>
      optionLabel(kind, row).toLowerCase().includes(query)
    );
  }, [kind, search, sources]);

  function changeAnalysis(nextAnalysis) {
    const kinds = allowedKinds(nextAnalysis);
    setAnalysis(nextAnalysis);
    setKind(kinds[0][0]);
    setSelected([]);
    setSearch("");
    setResult(null);
    exportOperation.reset();
    if (nextAnalysis === "trend" || nextAnalysis === "outliers") {
      setDays("90");
    } else if (nextAnalysis === "bottleneck") {
      setDays("7");
    } else {
      setDays("");
    }
  }

  function changeKind(nextKind) {
    setKind(nextKind);
    setSelected([]);
    setSearch("");
    setResult(null);
    exportOperation.reset();
  }

  function changeSelected(event) {
    setSelected(
      Array.from(event.target.selectedOptions, (option) => option.value).slice(0, 10)
    );
  }

  async function runAnalysis(event) {
    event.preventDefault();
    setError("");
    setResult(null);
    exportOperation.reset();

    if (analysis === "compare" && selected.length < 2) {
      setError("Select at least two records to compare.");
      return;
    }
    if (analysis === "trend" && selected.length < 1) {
      setError("Select at least one project or sample for the trend.");
      return;
    }

    setRunning(true);
    try {
      const response = await apiPost("/api/assistant/comparisons/", {
        analysis,
        kind,
        identifiers: selected,
        days: days ? Number(days) : null,
        metric,
        result_key: resultKey.trim(),
      });
      setResult(response);
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    } finally {
      setRunning(false);
    }
  }

  async function proposeExport(format) {
    if (!result?.context) return;
    await exportOperation.propose(
      `Export this comparison as ${format}`,
      result.context
    );
  }

  const kindChoices = allowedKinds(analysis);
  const helpText = analysis === "bottleneck"
    ? "Days is the minimum time a sample must remain in the same non-terminal status."
    : "Days limits work, result, and sample activity to the selected window.";

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Comparisons & Visual Analytics</h1>
          <p className="page-subtitle">
            Compare laboratory records, graph numeric results, identify unusual
            values, and locate workflow bottlenecks using permission-filtered data.
          </p>
        </div>
        <Badge bg="dark">{OPENLIMS_VERSION}</Badge>
      </div>

      {error && <Alert variant="danger">{error}</Alert>}

      <Card className="app-card mb-4">
        <Card.Body>
          <Form onSubmit={runAnalysis}>
            <Row className="g-3">
              <Col lg={4}>
                <Form.Group>
                  <Form.Label>Analysis</Form.Label>
                  <Form.Select
                    value={analysis}
                    onChange={(event) => changeAnalysis(event.target.value)}
                  >
                    {ANALYSES.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Form.Select>
                </Form.Group>
              </Col>
              <Col lg={4}>
                <Form.Group>
                  <Form.Label>Record type</Form.Label>
                  <Form.Select
                    value={kind}
                    onChange={(event) => changeKind(event.target.value)}
                  >
                    {kindChoices.map(([value, label]) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </Form.Select>
                </Form.Group>
              </Col>
              <Col lg={4}>
                <Form.Group>
                  <Form.Label>
                    {analysis === "bottleneck" ? "Stale threshold (days)" : "Date window (days)"}
                  </Form.Label>
                  <Form.Control
                    type="number"
                    min={1}
                    max={3650}
                    value={days}
                    onChange={(event) => setDays(event.target.value)}
                    placeholder={analysis === "compare" ? "All dates" : "90"}
                  />
                  <div className="form-text">{helpText}</div>
                </Form.Group>
              </Col>

              {analysis === "compare" && (
                <Col lg={6}>
                  <Form.Group>
                    <Form.Label>Graph focus</Form.Label>
                    <Form.Select
                      value={metric}
                      onChange={(event) => setMetric(event.target.value)}
                    >
                      {METRICS.map(([value, label]) => (
                        <option key={value} value={value}>{label}</option>
                      ))}
                    </Form.Select>
                  </Form.Group>
                </Col>
              )}

              {(analysis === "trend" || analysis === "outliers") && (
                <Col lg={6}>
                  <Form.Group>
                    <Form.Label>Result name or analyte</Form.Label>
                    <Form.Control
                      value={resultKey}
                      onChange={(event) => setResultKey(event.target.value)}
                      placeholder="Example: glucose or concentration; blank means all numeric results"
                    />
                  </Form.Group>
                </Col>
              )}

              <Col xs={12}>
                <Form.Group>
                  <div className="d-flex justify-content-between align-items-center gap-3 flex-wrap mb-2">
                    <Form.Label className="mb-0">
                      Select {kind}s ({selected.length}/10)
                    </Form.Label>
                    <Form.Control
                      size="sm"
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder={`Filter ${kind}s...`}
                      style={{ maxWidth: "320px" }}
                    />
                  </div>
                  {loadingOptions ? (
                    <div className="d-flex align-items-center gap-2 py-4">
                      <Spinner animation="border" size="sm" />
                      <span>Loading accessible records...</span>
                    </div>
                  ) : (
                    <Form.Select
                      multiple
                      value={selected}
                      onChange={changeSelected}
                      className="comparison-multi-select"
                    >
                      {visibleOptions.map((row) => {
                        const value = optionValue(kind, row);
                        return (
                          <option key={value} value={value}>
                            {optionLabel(kind, row)}
                          </option>
                        );
                      })}
                    </Form.Select>
                  )}
                  <div className="form-text">
                    Hold Ctrl on Windows/Linux or Command on macOS to select multiple records.
                    Outlier and bottleneck analysis may use all accessible projects when none are selected.
                  </div>
                </Form.Group>
              </Col>

              <Col xs={12}>
                <div className="d-flex justify-content-between align-items-center gap-3 flex-wrap border-top pt-3">
                  <div className="text-muted small">
                    OpenLIMS calculates the values; an AI model is not required.
                  </div>
                  <Button type="submit" variant="dark" disabled={running || loadingOptions}>
                    {running ? "Analyzing..." : "Run analysis"}
                  </Button>
                </div>
              </Col>
            </Row>
          </Form>
        </Card.Body>
      </Card>

      {result && (
        <>
          <Alert variant={result.comparison ? "success" : "warning"}>
            <div className="comparison-answer-text">{result.answer}</div>
          </Alert>

          {result.chart && <AssistantChart chart={result.chart} />}
          {result.comparison && (
            <ComparisonTable comparison={result.comparison} />
          )}

          {result.links?.length > 0 && (
            <div className="d-flex gap-2 flex-wrap mt-3">
              {result.links.map((link, index) => (
                <Button
                  key={`${link.url}-${index}`}
                  as={Link}
                  to={link.url}
                  size="sm"
                  variant="outline-dark"
                >
                  {link.label}
                </Button>
              ))}
            </div>
          )}

          {result.comparison && (
            <div className="d-flex justify-content-end gap-2 mt-3">
              <Button
                size="sm"
                variant="outline-dark"
                disabled={exportOperation.busy}
                onClick={() => proposeExport("CSV")}
              >
                Export CSV
              </Button>
              <Button
                size="sm"
                variant="dark"
                disabled={exportOperation.busy}
                onClick={() => proposeExport("PDF")}
              >
                Export PDF with graph
              </Button>
            </div>
          )}
        </>
      )}

      <ConfirmedOperationCard operation={exportOperation} />
    </div>
  );
}
