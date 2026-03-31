import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Alert, Badge, Card, Table } from "react-bootstrap";
import { apiGet } from "../api";

export default function ProjectDetail() {
  const { id } = useParams();

  const [project, setProject] = useState(null);
  const [samples, setSamples] = useState([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setErr("");
    setLoading(true);

    try {
      const [projectData, samplesData] = await Promise.all([
        apiGet(`/api/projects/${id}/`),
        apiGet(`/api/samples/?project=${id}`),
      ]);

      setProject(projectData);
      setSamples(samplesData);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [id]);

  if (loading) return <div>Loading...</div>;

  return (
    <div className="w-100">
      {err && <Alert variant="danger">{err}</Alert>}

      {project && (
        <>
          <Card className="shadow-sm border-0 mb-4">
            <Card.Body>
              <div className="d-flex justify-content-between align-items-start flex-wrap gap-2">
                <div>
                  <h2 className="mb-1">{project.name}</h2>
                  <div className="text-muted">{project.code}</div>
                </div>
                <Badge bg="dark">{project.sample_count ?? 0} samples</Badge>
              </div>

              <hr />

              <div className="mb-3">
                <strong>Description:</strong>
                <div>{project.description || "No description"}</div>
              </div>

              <div>
                <strong>Team Members:</strong>
                <div>
                  {project.member_usernames?.length
                    ? project.member_usernames.join(", ")
                    : "No members assigned"}
                </div>
              </div>
            </Card.Body>
          </Card>

          <Card className="shadow-sm border-0">
            <Card.Body>
              <h5 className="mb-3">Project Samples</h5>

              {samples.length === 0 ? (
                <Alert variant="light" className="mb-0">
                  No samples in this project yet.
                </Alert>
              ) : (
                <Table responsive hover className="mb-0">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Sample ID</th>
                      <th>Status</th>
                      <th>Container</th>
                      <th>Created</th>
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
                        <td>{s.container_code || "-"}</td>
                        <td>{s.created_at}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </>
      )}
    </div>
  );
}