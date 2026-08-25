import { useEffect, useState } from "react";
import { Alert, Button, Card, Col, Form, Row, Table } from "react-bootstrap";
import { apiGet, apiGetAll, apiPost } from "../api";
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
  const [containers, setContainers] = useState([]);
  const [users, setUsers] = useState([]);
  const [custodyEvents, setCustodyEvents] = useState([]);
  const [scan, setScan] = useState({
    barcode: "",
    action: "RECEIVE",
    container: "",
    custodian: "",
    reason: "",
  });
  const [scanSuccess, setScanSuccess] = useState("");

  async function load() {
    setError("");
    try {
      const [batchRows, sampleRows, containerRows, userRows, custodyRows, meData] = await Promise.all([
        apiGetAll("/api/sample-batches/"),
        apiGetAll("/api/samples/"),
        apiGetAll("/api/containers/"),
        apiGetAll("/api/users/"),
        apiGetAll("/api/sample-custody-events/"),
        apiGet("/api/me/"),
      ]);
      setBatches(batchRows);
      setSamples(sampleRows);
      setContainers(containerRows);
      setUsers(userRows);
      setCustodyEvents(custodyRows.slice(0, 20));
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

  async function submitScan(event) {
    event.preventDefault();
    setError("");
    setScanSuccess("");
    try {
      const payload = {
        barcode: scan.barcode.trim(),
        action: scan.action,
        reason: scan.reason.trim(),
      };
      if (["RECEIVE", "MOVE"].includes(scan.action) && scan.container) {
        payload.container = Number(scan.container);
      }
      if (scan.action === "TRANSFER" && scan.custodian) {
        payload.custodian = Number(scan.custodian);
      }
      const result = await apiPost("/api/sample-custody-events/scan/", payload);
      setScanSuccess(`${result.sample_code}: ${result.action} recorded.`);
      setScan((current) => ({ ...current, barcode: "", reason: "" }));
      await load();
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    }
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
      {scanSuccess && <Alert variant="success">{scanSuccess}</Alert>}
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

      {writable && (
        <Card className="app-card mt-4">
          <Card.Body>
            <h5 className="section-title">Scan chain of custody</h5>
            <p className="feed-meta">Scan the Code 128 label or enter the sample ID. Every action requires a reason and is added to the audit trail.</p>
            <Form onSubmit={submitScan}>
              <Row className="g-3">
                <Col md={4}><Form.Label>Barcode or sample ID</Form.Label><Form.Control autoFocus required value={scan.barcode} onChange={(event) => setScan({ ...scan, barcode: event.target.value })} placeholder="Scan label" /></Col>
                <Col md={3}><Form.Label>Action</Form.Label><Form.Select value={scan.action} onChange={(event) => setScan({ ...scan, action: event.target.value })}><option value="RECEIVE">Receive into lab</option><option value="CHECK_OUT">Check out to me</option><option value="CHECK_IN">Check in</option><option value="TRANSFER">Transfer custody</option><option value="MOVE">Move storage</option><option value="PROCESS">Record processing</option><option value="DISPOSE">Dispose and archive</option></Form.Select></Col>
                <Col md={3}>
                  {["RECEIVE", "MOVE"].includes(scan.action) && <><Form.Label>Destination container</Form.Label><Form.Select required={scan.action === "MOVE"} value={scan.container} onChange={(event) => setScan({ ...scan, container: event.target.value })}><option value="">No container</option>{containers.map((container) => <option key={container.id} value={container.id}>{container.container_id} — {container.location_name}</option>)}</Form.Select></>}
                  {scan.action === "TRANSFER" && <><Form.Label>New custodian</Form.Label><Form.Select required value={scan.custodian} onChange={(event) => setScan({ ...scan, custodian: event.target.value })}><option value="">Select user</option>{users.map((user) => <option key={user.id} value={user.id}>{user.username}</option>)}</Form.Select></>}
                </Col>
                <Col md={2} className="d-flex align-items-end"><Button type="submit" variant="dark" className="w-100" disabled={!scan.barcode || scan.reason.trim().length < 10}>Record scan</Button></Col>
                <Col xs={12}><Form.Label>Reason / handling note</Form.Label><Form.Control required minLength={10} value={scan.reason} onChange={(event) => setScan({ ...scan, reason: event.target.value })} placeholder="Why is this sample being moved or transferred?" /></Col>
              </Row>
            </Form>
          </Card.Body>
        </Card>
      )}

      <Card className="app-card mt-4">
        <Card.Body>
          <h5 className="section-title">Recent custody scans</h5>
          <Table responsive className="app-table mb-0">
            <thead><tr><th>Time</th><th>Sample</th><th>Action</th><th>Destination</th><th>Performed by</th></tr></thead>
            <tbody>{custodyEvents.map((row) => <tr key={row.id}><td>{new Date(row.occurred_at).toLocaleString()}</td><td>{row.sample_code}</td><td>{row.action}</td><td>{row.to_container_code || row.to_custodian_username || "Lab storage"}</td><td>{row.performed_by_username}</td></tr>)}{!custodyEvents.length && <tr><td colSpan={5} className="text-muted">No custody scans recorded.</td></tr>}</tbody>
          </Table>
        </Card.Body>
      </Card>

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
