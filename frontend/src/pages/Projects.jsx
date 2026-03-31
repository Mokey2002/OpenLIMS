import { useEffect, useState } from "react";
import { Alert, Button, Card, Col, Form, Row, Table } from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGet, apiPost } from "../api";

export default function Projects() {
  const [projects, setProjects] = useState([]);
  const [users, setUsers] = useState([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [description, setDescription] = useState("");
  const [selectedMembers, setSelectedMembers] = useState([]);

  async function load() {
    setErr("");
    setLoading(true);

    try {
      const [projectsData, usersData] = await Promise.all([
        apiGet("/api/projects/"),
        apiGet("/api/users/"),
      ]);
      setProjects(projectsData);
      setUsers(usersData);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  function toggleMember(id) {
    setSelectedMembers((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }

  async function createProject(e) {
    e.preventDefault();
    setErr("");

    try {
      await apiPost("/api/projects/", {
        name,
        code,
        description,
        members: selectedMembers,
      });

      setName("");
      setCode("");
      setDescription("");
      setSelectedMembers([]);
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  return (
    <div className="w-100">
      <h2 className="mb-3">Projects</h2>

      {err && <Alert variant="danger">{err}</Alert>}

      <Card className="shadow-sm border-0 mb-4">
        <Card.Body>
          <h5 className="mb-3">Create Project</h5>

          <Form onSubmit={createProject}>
            <Row className="g-3">
              <Col md={4}>
                <Form.Control
                  placeholder="Project name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </Col>
              <Col md={3}>
                <Form.Control
                  placeholder="Project code"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                />
              </Col>
              <Col md={5}>
                <Form.Control
                  placeholder="Description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </Col>
            </Row>

            <div className="mt-3">
              <div className="fw-semibold mb-2">Team Members</div>
              <Row>
                {users.map((u) => (
                  <Col md={4} key={u.id}>
                    <Form.Check
                      type="checkbox"
                      label={u.username}
                      checked={selectedMembers.includes(u.id)}
                      onChange={() => toggleMember(u.id)}
                    />
                  </Col>
                ))}
              </Row>
            </div>

            <div className="mt-3">
              <Button type="submit" variant="dark" disabled={!name || !code}>
                Create Project
              </Button>
            </div>
          </Form>
        </Card.Body>
      </Card>

      <Card className="shadow-sm border-0">
        <Card.Body>
          <h5 className="mb-3">Existing Projects</h5>

          {loading ? (
            <div>Loading...</div>
          ) : projects.length === 0 ? (
            <Alert variant="light" className="mb-0">
              No projects yet.
            </Alert>
          ) : (
            <Table responsive hover className="mb-0">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Code</th>
                  <th>Name</th>
                  <th>Description</th>
                  <th>Members</th>
                  <th>Samples</th>
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => (
                  <tr key={p.id}>
                    <td>{p.id}</td>
                    <td>{p.code}</td>
                    <td>
                      <Link to={`/projects/${p.id}`}>{p.name}</Link>
                    </td>
                    <td>{p.description || "-"}</td>
                    <td>{p.member_usernames?.join(", ") || "-"}</td>
                    <td>{p.sample_count ?? 0}</td>
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