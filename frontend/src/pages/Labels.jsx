import { useEffect, useState } from "react";
import { Alert, Button, Card, Col, Form, Row, Table } from "react-bootstrap";
import { apiGet, apiGetAll } from "../api";
import { canWrite } from "../authz";
import ConfirmedOperationCard from "../components/ConfirmedOperationCard";
import useConfirmedOperation from "../hooks/useConfirmedOperation";

export default function Labels() {
  const [batches, setBatches] = useState([]);
  const [samples, setSamples] = useState([]);
  const [me, setMe] = useState(null);
  const [error, setError] = useState("");
  const [mode, setMode] = useState("BATCH");
  const [batchId, setBatchId] = useState("");
  const [sampleId, setSampleId] = useState("");

  async function load() {
    setError("");
    try {
      const [batchRows, sampleRows, meData] = await Promise.all([
        apiGetAll("/api/sample-batches/"),
        apiGetAll("/api/samples/"),
        apiGet("/api/me/"),
      ]);
      setBatches(batchRows);
      setSamples(sampleRows);
      setMe(meData);
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    }
  }

  const operation = useConfirmedOperation(load);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, []);

  async function proposeLabels(event) {
    event.preventDefault();
    if (mode === "BATCH") {
      const batch = batches.find((row) => String(row.id) === String(batchId));
      if (!batch) return;
      await operation.propose(`Create barcode labels for batch ${batch.code}`);
      return;
    }
    const sample = samples.find((row) => String(row.id) === String(sampleId));
    if (!sample) return;
    await operation.propose(`Regenerate the barcode label for sample ${sample.sample_id}`);
  }

  const writable = canWrite(me);

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Barcode Labels</h1>
          <p className="page-subtitle">
            Generate Code 128 sample labels as a downloadable PDF. Existing labels
            are automatically identified and audited as reprints.
          </p>
        </div>
        <Button variant="outline-dark" size="sm" onClick={load}>Refresh</Button>
      </div>

      {error && <Alert variant="danger">{error}</Alert>}
      {!writable && me && (
        <Alert variant="info">Label generation requires a Tech or Director role.</Alert>
      )}

      {writable && (
        <Card className="app-card mb-4">
          <Card.Body>
            <h5 className="section-title">Generate label PDF</h5>
            <Form onSubmit={proposeLabels}>
              <Row className="g-3 align-items-end">
                <Col md={3}>
                  <Form.Label>Label scope</Form.Label>
                  <Form.Select value={mode} onChange={(event) => setMode(event.target.value)}>
                    <option value="BATCH">Entire batch</option>
                    <option value="SAMPLE">Single sample / reprint</option>
                  </Form.Select>
                </Col>
                <Col md={7}>
                  {mode === "BATCH" ? (
                    <>
                      <Form.Label>Batch</Form.Label>
                      <Form.Select value={batchId} onChange={(event) => setBatchId(event.target.value)}>
                        <option value="">Select a batch</option>
                        {batches.map((batch) => (
                          <option key={batch.id} value={batch.id}>
                            {batch.code} — {batch.project_code} ({batch.sample_count} labels)
                          </option>
                        ))}
                      </Form.Select>
                    </>
                  ) : (
                    <>
                      <Form.Label>Sample</Form.Label>
                      <Form.Select value={sampleId} onChange={(event) => setSampleId(event.target.value)}>
                        <option value="">Select a sample</option>
                        {samples.map((sample) => (
                          <option key={sample.id} value={sample.id}>
                            {sample.sample_id} — {sample.project_code || "No project"}
                          </option>
                        ))}
                      </Form.Select>
                    </>
                  )}
                </Col>
                <Col md={2}>
                  <Button
                    type="submit"
                    variant="dark"
                    className="w-100"
                    disabled={mode === "BATCH" ? !batchId : !sampleId}
                  >
                    Preview
                  </Button>
                </Col>
              </Row>
            </Form>
          </Card.Body>
        </Card>
      )}

      <ConfirmedOperationCard operation={operation} />

      <Card className="app-card mt-4">
        <Card.Body>
          <h5 className="section-title">PDF contents</h5>
          <Table responsive className="app-table mb-0">
            <tbody>
              <tr><th>Barcode format</th><td>Code 128</td></tr>
              <tr><th>Label fields</th><td>Sample ID, project code, barcode, and readable barcode text</td></tr>
              <tr><th>Page layout</th><td>10 labels per US Letter page</td></tr>
              <tr><th>Reprints</th><td>Marked REPRINT and recorded in the audit trail</td></tr>
              <tr><th>Maximum</th><td>100 labels per generated PDF</td></tr>
            </tbody>
          </Table>
        </Card.Body>
      </Card>
    </div>
  );
}
