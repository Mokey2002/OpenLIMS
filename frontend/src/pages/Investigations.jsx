import { useEffect, useState } from "react";
import { Alert, Badge, Button, Card, Col, Form, Row } from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiDownload, apiGetAll, apiPost } from "../api";
import AssistantChart from "../components/AssistantChart";
import ConfirmedOperationCard from "../components/ConfirmedOperationCard";
import InvestigationPanel from "../components/InvestigationPanel";
import useConfirmedOperation from "../hooks/useConfirmedOperation";
import { OPENLIMS_VERSION } from "../version";

const GROUPS = [
  ["overview", "QC failures by result"],
  ["operator", "Failures by result entrant"],
  ["workflow", "Failures by work type"],
  ["instrument", "Instrument import context"],
  ["reagent", "Reagent reservation context"],
];

export default function Investigations() {
  const [subjectType, setSubjectType] = useState("sample");
  const [identifier, setIdentifier] = useState("");
  const [days, setDays] = useState("90");
  const [resultKey, setResultKey] = useState("");
  const [groupBy, setGroupBy] = useState("overview");
  const [samples, setSamples] = useState([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  const exportOperation = useConfirmedOperation(async (action) => {
    if (action.result?.download_url) {
      await apiDownload(action.result.download_url, "openlims-investigation");
    }
  });

  useEffect(() => {
    apiGetAll("/api/samples/").then(setSamples).catch(() => setSamples([]));
  }, []);

  async function runInvestigation(event) {
    event.preventDefault();
    setError("");
    setResult(null);
    exportOperation.reset();
    if (!identifier.trim()) {
      setError(`Enter a ${subjectType === "sample" ? "sample ID" : "result ID"}.`);
      return;
    }
    setRunning(true);
    try {
      const response = await apiPost("/api/assistant/investigations/", {
        subject_type: subjectType,
        identifier: identifier.trim(),
        days: Number(days),
        result_key: resultKey.trim(),
        group_by: groupBy,
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
    await exportOperation.propose(`Export this investigation as ${format}`, result.context);
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Investigation Workbench</h1>
          <p className="page-subtitle">
            Trace QC failures across results, peer samples, workflows, instrument imports,
            reagent lots, and audit history with explicit confidence levels.
          </p>
        </div>
        <Badge bg="dark">{OPENLIMS_VERSION}</Badge>
      </div>

      {error && <Alert variant="danger">{error}</Alert>}

      <Card className="app-card mb-4">
        <Card.Body>
          <Form onSubmit={runInvestigation}>
            <Row className="g-3">
              <Col lg={3}>
                <Form.Group>
                  <Form.Label>Investigate</Form.Label>
                  <Form.Select value={subjectType} onChange={(event) => { setSubjectType(event.target.value); setIdentifier(""); }}>
                    <option value="sample">Sample</option>
                    <option value="result">Result</option>
                  </Form.Select>
                </Form.Group>
              </Col>
              <Col lg={5}>
                <Form.Group>
                  <Form.Label>{subjectType === "sample" ? "Sample ID" : "Result ID"}</Form.Label>
                  <Form.Control
                    list={subjectType === "sample" ? "investigation-samples" : undefined}
                    value={identifier}
                    onChange={(event) => setIdentifier(event.target.value)}
                    placeholder={subjectType === "sample" ? "Example: S-ALPHA-003" : "Example: result ID or R-ID"}
                  />
                  <datalist id="investigation-samples">
                    {samples.map((sample) => <option key={sample.id} value={sample.sample_id} />)}
                  </datalist>
                </Form.Group>
              </Col>
              <Col lg={4}>
                <Form.Group>
                  <Form.Label>Evidence window (days)</Form.Label>
                  <Form.Control type="number" min={1} max={3650} value={days} onChange={(event) => setDays(event.target.value)} />
                </Form.Group>
              </Col>
              <Col lg={6}>
                <Form.Group>
                  <Form.Label>Optional result/analyte filter</Form.Label>
                  <Form.Control value={resultKey} onChange={(event) => setResultKey(event.target.value)} placeholder="Example: glucose" />
                </Form.Group>
              </Col>
              <Col lg={6}>
                <Form.Group>
                  <Form.Label>Graph</Form.Label>
                  <Form.Select value={groupBy} onChange={(event) => setGroupBy(event.target.value)}>
                    {GROUPS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </Form.Select>
                </Form.Group>
              </Col>
              <Col xs={12}>
                <div className="d-flex justify-content-between align-items-center gap-3 flex-wrap border-top pt-3">
                  <div className="small text-muted">Calculations are deterministic; an optional AI model may summarize the evidence.</div>
                  <Button type="submit" variant="dark" disabled={running}>{running ? "Investigating..." : "Run investigation"}</Button>
                </div>
              </Col>
            </Row>
          </Form>
        </Card.Body>
      </Card>

      {result && (
        <>
          <Alert variant={result.investigation ? "success" : "warning"}>{result.answer}</Alert>
          {result.chart && <AssistantChart chart={result.chart} />}
          {result.investigation && <InvestigationPanel investigation={result.investigation} />}
          {result.links?.length > 0 && (
            <div className="d-flex gap-2 flex-wrap mt-3">
              {result.links.map((link) => <Button key={link.url} as={Link} to={link.url} size="sm" variant="outline-dark">{link.label}</Button>)}
            </div>
          )}
          {result.investigation && (
            <div className="d-flex justify-content-end gap-2 mt-3">
              <Button size="sm" variant="outline-dark" disabled={exportOperation.busy} onClick={() => proposeExport("CSV")}>Export CSV</Button>
              <Button size="sm" variant="dark" disabled={exportOperation.busy} onClick={() => proposeExport("PDF")}>Export PDF evidence package</Button>
            </div>
          )}
        </>
      )}

      <ConfirmedOperationCard operation={exportOperation} />
    </div>
  );
}
