import { useEffect, useMemo, useState } from "react";
import { Alert, Badge, Button, Card, Col, Form, Row, Table } from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGet, apiGetAll, apiPost } from "../api";
import { canWrite } from "../authz";

function emptyDerivation() {
  return {
    sample_id: "",
    sample_type: "",
    relationship_type: "ALIQUOT",
    quantity: "",
    unit: "",
    reason: "",
  };
}

export default function Traceability() {
  const [samples, setSamples] = useState([]);
  const [relationships, setRelationships] = useState([]);
  const [custodyEvents, setCustodyEvents] = useState([]);
  const [me, setMe] = useState(null);
  const [selectedSample, setSelectedSample] = useState("");
  const [form, setForm] = useState(emptyDerivation);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [saving, setSaving] = useState(false);

  async function load() {
    setError("");
    try {
      const [sampleRows, relationshipRows, custodyRows, meData] = await Promise.all([
        apiGetAll("/api/samples/"),
        apiGetAll("/api/sample-relationships/"),
        apiGetAll("/api/sample-custody-events/"),
        apiGet("/api/me/"),
      ]);
      setSamples(sampleRows);
      setRelationships(relationshipRows);
      setCustodyEvents(custodyRows);
      setMe(meData);
      setSelectedSample((current) => current || (sampleRows[0] ? String(sampleRows[0].id) : ""));
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, []);

  const selected = samples.find((sample) => String(sample.id) === String(selectedSample));
  const lineage = useMemo(
    () => relationships.filter((row) =>
      String(row.source_sample) === String(selectedSample) ||
      String(row.derived_sample) === String(selectedSample)
    ),
    [relationships, selectedSample]
  );
  const custody = useMemo(
    () => custodyEvents.filter((row) => String(row.sample) === String(selectedSample)),
    [custodyEvents, selectedSample]
  );

  async function createDerivedSample(event) {
    event.preventDefault();
    if (!selectedSample) return;
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const payload = {
        ...form,
        quantity: form.quantity ? form.quantity : null,
      };
      const result = await apiPost(`/api/samples/${selectedSample}/derive/`, payload);
      setSuccess(`${result.sample.sample_id} was created and linked to ${selected.sample_id}.`);
      setForm(emptyDerivation());
      await load();
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Sample Traceability</h1>
          <p className="page-subtitle">
            Create aliquots and derived samples, review parent/child lineage, and inspect custody history.
          </p>
        </div>
        <Button size="sm" variant="outline-dark" onClick={load}>Refresh</Button>
      </div>

      {error && <Alert variant="danger">{error}</Alert>}
      {success && <Alert variant="success">{success}</Alert>}

      <Card className="app-card mb-4">
        <Card.Body>
          <Form.Group>
            <Form.Label>Sample</Form.Label>
            <Form.Select value={selectedSample} onChange={(event) => setSelectedSample(event.target.value)}>
              <option value="">Select a sample</option>
              {samples.map((sample) => (
                <option key={sample.id} value={sample.id}>
                  {sample.sample_id} — {sample.project_code || "No project"}
                </option>
              ))}
            </Form.Select>
          </Form.Group>
          {selected && (
            <div className="feed-meta mt-2">
              Type: {selected.sample_type} · Status: {selected.status} · Storage: {selected.container_code || "Not assigned"} · Custodian: {selected.custodian_username || "Lab storage"}
            </div>
          )}
        </Card.Body>
      </Card>

      {canWrite(me) && selected && (
        <Card className="app-card mb-4">
          <Card.Body>
            <h5 className="section-title">Create aliquot or derived sample</h5>
            <Form onSubmit={createDerivedSample}>
              <Row className="g-3">
                <Col md={3}><Form.Label>New sample ID</Form.Label><Form.Control required value={form.sample_id} onChange={(event) => setForm({ ...form, sample_id: event.target.value })} placeholder={`${selected.sample_id}-A1`} /></Col>
                <Col md={2}><Form.Label>Relationship</Form.Label><Form.Select value={form.relationship_type} onChange={(event) => setForm({ ...form, relationship_type: event.target.value })}><option value="ALIQUOT">Aliquot</option><option value="DERIVED">Derived sample</option><option value="SPLIT">Split</option><option value="POOL_COMPONENT">Pool component</option></Form.Select></Col>
                <Col md={2}><Form.Label>Sample type</Form.Label><Form.Control value={form.sample_type} onChange={(event) => setForm({ ...form, sample_type: event.target.value })} placeholder={selected.sample_type} /></Col>
                <Col md={2}><Form.Label>Quantity</Form.Label><Form.Control type="number" min="0" step="any" value={form.quantity} onChange={(event) => setForm({ ...form, quantity: event.target.value })} /></Col>
                <Col md={1}><Form.Label>Unit</Form.Label><Form.Control value={form.unit} onChange={(event) => setForm({ ...form, unit: event.target.value })} placeholder="mL" /></Col>
                <Col md={2} className="d-flex align-items-end"><Button className="w-100" type="submit" variant="dark" disabled={saving || !form.sample_id || form.reason.trim().length < 10}>{saving ? "Creating..." : "Create"}</Button></Col>
                <Col xs={12}><Form.Label>Reason</Form.Label><Form.Control required minLength={10} value={form.reason} onChange={(event) => setForm({ ...form, reason: event.target.value })} placeholder="Describe why this aliquot or derived sample is being created" /></Col>
              </Row>
            </Form>
          </Card.Body>
        </Card>
      )}

      <Row className="g-4">
        <Col lg={6}>
          <Card className="app-card h-100"><Card.Body>
            <h5 className="section-title">Lineage</h5>
            <Table responsive className="app-table mb-0">
              <thead><tr><th>Source</th><th>Relationship</th><th>Derived sample</th><th>Amount</th></tr></thead>
              <tbody>
                {lineage.map((row) => <tr key={row.id}><td><Link to={`/samples/${row.source_sample}`}>{row.source_sample_code}</Link></td><td><Badge bg="info">{row.relationship_type}</Badge></td><td><Link to={`/samples/${row.derived_sample}`}>{row.derived_sample_code}</Link></td><td>{row.quantity ? `${row.quantity} ${row.unit}` : "—"}</td></tr>)}
                {!lineage.length && <tr><td colSpan={4} className="text-muted">No lineage relationships recorded.</td></tr>}
              </tbody>
            </Table>
          </Card.Body></Card>
        </Col>
        <Col lg={6}>
          <Card className="app-card h-100"><Card.Body>
            <div className="toolbar-row"><h5 className="section-title mb-0">Custody history</h5><Link to="/labels">Scan barcode</Link></div>
            <Table responsive className="app-table mb-0 mt-3">
              <thead><tr><th>Time</th><th>Action</th><th>Storage / custodian</th><th>Performed by</th></tr></thead>
              <tbody>
                {custody.map((row) => <tr key={row.id}><td>{new Date(row.occurred_at).toLocaleString()}</td><td><Badge bg="dark">{row.action}</Badge></td><td>{row.to_container_code || "—"}<div className="feed-meta">{row.to_custodian_username || "Lab storage"}</div></td><td>{row.performed_by_username}</td></tr>)}
                {!custody.length && <tr><td colSpan={4} className="text-muted">No custody scans recorded.</td></tr>}
              </tbody>
            </Table>
          </Card.Body></Card>
        </Col>
      </Row>
    </div>
  );
}
