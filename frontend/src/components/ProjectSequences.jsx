import { useEffect, useState } from "react";
import { Alert, Badge, Button, Card, Table } from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGet } from "../api";

export default function ProjectSequences({ projectId }) {
  const [sequences, setSequences] = useState([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  async function loadSequences() {
    if (!projectId) return;

    setErr("");
    setLoading(true);

    try {
      const data = await apiGet(`/api/sequences/?project=${projectId}`);
      setSequences(data.results || data || []);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadSequences();
  }, [projectId]);

  return (
    <Card className="app-card mb-4">
      <Card.Body>
        <div className="toolbar-row mb-3">
          <div>
            <h5 className="section-title mb-1">Project Sequences</h5>
            <div className="feed-meta">
              Saved SeqViz workspaces linked to this project.
            </div>
          </div>

          <div className="inline-actions">
            <Badge bg="dark">{sequences.length}</Badge>
            <Button
              variant="outline-dark"
              size="sm"
              onClick={loadSequences}
              disabled={loading}
            >
              {loading ? "Loading..." : "Refresh"}
            </Button>
          </div>
        </div>

        {err && <Alert variant="danger">{err}</Alert>}

        {sequences.length === 0 ? (
          <div className="empty-state">
            No sequence workspaces linked to this project yet.
          </div>
        ) : (
          <Table responsive hover className="app-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Type</th>
                <th>Length</th>
                <th>Features</th>
                <th>Updated</th>
                <th></th>
              </tr>
            </thead>

            <tbody>
              {sequences.map((seq) => (
                <tr key={seq.id}>
                  <td className="fw-semibold">{seq.name}</td>
                  <td>{seq.sequence_type}</td>
                  <td>{seq.sequence?.length ?? 0} bp</td>
                  <td>{seq.features?.length ?? 0}</td>
                  <td>
                    {seq.updated_at
                      ? new Date(seq.updated_at).toLocaleString()
                      : "-"}
                  </td>
                  <td>
                    <Link to={`/sequences?workspace=${seq.id}`}>
                      Open
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card.Body>
    </Card>
  );
}