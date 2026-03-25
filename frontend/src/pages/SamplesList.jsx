import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Button, Card, Form, Row, Col, Table } from "react-bootstrap";
import { apiGet, apiPost } from "../api";

const STATUS_OPTIONS = [
  "",
  "RECEIVED",
  "IN_PROGRESS",
  "QC",
  "REPORTED",
  "ARCHIVED",
];

export default function SamplesList() {
  const [samples, setSamples] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const [sampleId, setSampleId] = useState("");

  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");

  async function load() {
    setErr("");
    setLoading(true);

    try {
      const params = new URLSearchParams();

      if (search.trim()) {
        params.set("search", search.trim());
      }

      if (status) {
        params.set("status", status);
      }

      const query = params.toString() ? `?${params.toString()}` : "";
      const data = await apiGet(`/api/samples/${query}`);
      setSamples(data);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [search, status]);

  async function createSample(e) {
    e.preventDefault();
    setErr("");
    const id = sampleId.trim();
    if (!id) return;

    try {
      await apiPost("/api/samples/", { sample_id: id, status: "RECEIVED" });
      setSampleId("");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  return (
    <div className="w-100">
      <h2 className="mb-3">Samples</h2>

      <Card className="shadow-sm border-0 mb-4">
        <Card.Body>
          <Form onSubmit={createSample} className="d-flex gap-2">
            <Form.Control
              value={sampleId}
              onChange={(e) => setSampleId(e.target.value)}
              placeholder="New sample id (e.g. S-002)"
            />
            <Button type="submit" variant="dark">
              Create
            </Button>
          </Form>
        </Card.Body>
      </Card>

      <Card className="shadow-sm border-0 mb-4">
        <Card.Body>
          <Row className="g-3">
            <Col md={8}>
              <Form.Control
                placeholder="Search by sample ID"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </Col>
            <Col md={4}>
              <Form.Select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                <option value="">All statuses</option>
                {STATUS_OPTIONS.filter(Boolean).map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </Form.Select>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      {err && <Alert variant="danger">{err}</Alert>}

      <Card className="shadow-sm border-0">
        <Card.Body>
          {loading ? (
            <div>Loading...</div>
          ) : (
            <Table responsive hover>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Sample ID</th>
                  <th>Status</th>
                  <th>Container</th>
                  <th>Created At</th>
                </tr>
              </thead>
              <tbody>
                {samples.map((s) => (
                  <tr key={s.id}>
                    <td>{s.id}</td>
                    <td>
                      <Link to={`/samples/${s.id}`}>{s.sample_id}</Link>
                    </td>
                    <td>{s.status}</td>
                    <td>{s.container ?? "-"}</td>
                    <td>{s.created_at}</td>
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
