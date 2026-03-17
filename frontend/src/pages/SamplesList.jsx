import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Button, Card, Form, Table } from "react-bootstrap";
import { apiGet, apiPost } from "../api";

export default function SamplesList() {
  const [samples, setSamples] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [sampleId, setSampleId] = useState("");

  async function load() {
    setErr("");
    setLoading(true);
    try {
      const data = await apiGet("/api/samples/");
      setSamples(data);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

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
