import { useEffect, useId, useState } from "react";
import { Alert, Badge, Button, Card, Col, Form, Row } from "react-bootstrap";
import { apiDownload, apiGet, apiPost } from "../api";

const activeStatuses = ["QUEUED", "RUNNING"];
const runLabels = { QUEUED: "Queued", RUNNING: "Running", FAILED: "Failed" };

function countLabel(count, singular, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function RunResult({ run, onDownload }) {
  const summary = run.summary;
  const downloadHintId = useId();
  return (
    <div>
      <p role="status" className="mb-2">
        <strong>Run #{run.id}</strong>{" "}
        {summary ? (
          <Badge bg={summary.outcome === "PASS" ? "success" : "warning"}
            text={summary.outcome === "PASS" ? undefined : "dark"}>
            {summary.outcome === "PASS" ? "Passed" : "Needs review"}
          </Badge>
        ) : (
          <>
            <Badge bg={run.status === "FAILED" ? "danger" : "secondary"}>{runLabels[run.status]}</Badge>
            {" "}{run.message}
          </>
        )}
      </p>
      {summary && (
        <>
          <p className="mb-2">
            {countLabel(summary.rows_checked, "row")} checked · {countLabel(summary.invalid_readings, "invalid reading")}
            {run.parameters.plate_size && [
              countLabel(summary.missing_wells, "missing well"),
              countLabel(summary.duplicate_wells, "duplicate well entry", "duplicate well entries"),
              countLabel(summary.invalid_wells, "invalid well entry", "invalid well entries"),
            ].map((label) => ` · ${label}`).join("")}
          </p>
          <Button size="sm" variant="outline-primary" aria-describedby={downloadHintId}
            onClick={() => onDownload(run)}>
            Download QC report
          </Button>
          <p id={downloadHintId} className="small text-body-secondary mt-1 mb-0">
            Download a CSV of flagged rows and wells.
          </p>
        </>
      )}
      <details className="mt-2 small">
        <summary>Run details</summary>
        <div>{run.filename}{run.sheet ? ` · Sheet ${run.sheet}` : ""}</div>
        <div>Reading column: {run.parameters.reading_column}</div>
        {run.parameters.well_column && (
          <div>Well column: {run.parameters.well_column} · {run.parameters.plate_size}-well plate</div>
        )}
        <div>Workflow v{run.workflow_version}{run.engine_version ? ` · Snakemake ${run.engine_version}` : ""}</div>
        <div className="text-break">Input SHA-256: {run.input_sha256}</div>
        {run.retry_of && <div>Retry of run #{run.retry_of}</div>}
      </details>
    </div>
  );
}

export default function ImportAnalysis({ importId, canRun }) {
  const runHintId = useId();
  const path = `/api/import-jobs/${importId}/qc-runs/`;
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const workflow = data?.workflow;
  const latest = data?.runs[0];
  const active = activeStatuses.includes(latest?.status);

  useEffect(() => {
    const controller = new AbortController();
    function refresh() {
      apiGet(path, { signal: controller.signal }).then(
        (result) => {
          if (!controller.signal.aborted) {
            setData(result);
            setError("");
          }
        },
        (error) => {
          if (!controller.signal.aborted) setError(error.message);
        },
      );
    }
    refresh();
    const timer = setInterval(refresh, active ? 2500 : 10000);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [path, active]);

  function showForm() {
    setForm({
      reading_column: workflow.default_reading_column,
      well_column: workflow.default_well_column === workflow.default_reading_column
        ? "" : workflow.default_well_column,
      plate_size: 96,
    });
  }

  async function queue(url, parameters) {
    setBusy(true);
    setError("");
    try {
      const run = await apiPost(url, parameters);
      setData((current) => ({ ...current, runs: [run, ...current.runs].slice(0, 10) }));
      setForm(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function download(run) {
    try {
      await apiDownload(`${path}${run.id}/report/`, `instrument-qc-${run.id}.csv`);
    } catch (err) {
      setError(err.message);
    }
  }

  if (!workflow && !latest && !error) return null;

  return (
    <Card className="app-card mb-4">
      <Card.Body>
        <div className="toolbar-row mb-3">
          <h2 className="h5 section-title mb-0">Instrument export QC</h2>
          {canRun && workflow && !form && (
            <div>
              <Button size="sm" disabled={active || busy} aria-describedby={runHintId} onClick={showForm}>
                Run analysis
              </Button>
              <p id={runHintId} className="small text-body-secondary mt-1 mb-0">
                Choose columns to check readings and, optionally, well coverage.
              </p>
            </div>
          )}
        </div>
        {error && <Alert variant="danger">{error}</Alert>}

        {form && (
          <Form className="mb-3" onSubmit={(event) => {
            event.preventDefault();
            queue(path, { ...form, plate_size: form.well_column ? form.plate_size : null });
          }}>
            <p className="mb-2">
              <strong>Export</strong> {workflow.filename}{workflow.sheet && ` · Sheet ${workflow.sheet}`}
            </p>
            <Row className="g-2 mb-3">
              <Col md>
                <Form.Group controlId="qc-reading-column">
                  <Form.Label>Numeric reading column</Form.Label>
                  <Form.Select value={form.reading_column} required disabled={busy}
                    onChange={(event) => {
                      const readingColumn = event.target.value;
                      setForm({
                        ...form,
                        reading_column: readingColumn,
                        well_column: form.well_column === readingColumn ? "" : form.well_column,
                      });
                    }}>
                    <option value="">Select column</option>
                    {workflow.columns.map((name) => <option key={name} value={name}>{name}</option>)}
                  </Form.Select>
                </Form.Group>
              </Col>
              <Col md>
                <Form.Group controlId="qc-well-column">
                  <Form.Label>Well column</Form.Label>
                  <Form.Select value={form.well_column} disabled={busy}
                    onChange={(event) => setForm({ ...form, well_column: event.target.value })}>
                    <option value="">Check readings only</option>
                    {workflow.columns.filter((name) => name !== form.reading_column)
                      .map((name) => <option key={name} value={name}>{name}</option>)}
                  </Form.Select>
                </Form.Group>
              </Col>
              {form.well_column && (
                <Col md>
                  <Form.Group controlId="qc-plate-size">
                    <Form.Label>Plate size</Form.Label>
                    <Form.Select value={form.plate_size} disabled={busy}
                      onChange={(event) => setForm({ ...form, plate_size: Number(event.target.value) })}>
                      <option value={96}>96 wells</option>
                      <option value={384}>384 wells</option>
                    </Form.Select>
                  </Form.Group>
                </Col>
              )}
            </Row>
            <Button type="submit" size="sm" disabled={busy || !form.reading_column}>
              {busy ? "Queueing…" : "Run instrument QC"}
            </Button>
            <Button type="button" size="sm" variant="link" disabled={busy} onClick={() => setForm(null)}>Cancel</Button>
          </Form>
        )}

        {latest && (
          <>
            <RunResult run={latest} onDownload={download} />
            {latest.status === "FAILED" && canRun && (
              <Button className="mt-2" size="sm" variant="outline-primary" disabled={busy}
                onClick={() => queue(`${path}${latest.id}/retry/`, {})}>
                Retry analysis
              </Button>
            )}
            {data.runs.length > 1 && (
              <details className="mt-3">
                <summary>Recent runs</summary>
                <ul className="list-unstyled mb-0">
                  {data.runs.slice(1).map((run) => (
                    <li className="border-top py-2" key={run.id}>
                      <RunResult run={run} onDownload={download} />
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </>
        )}
      </Card.Body>
    </Card>
  );
}
