import { useEffect, useMemo, useState } from "react";
import { Alert, Badge, Button, Card, Col, Form, Row, Table } from "react-bootstrap";
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

  const [memberQuery, setMemberQuery] = useState("");
  const [selectedMembers, setSelectedMembers] = useState([]);

  async function load() {
    setErr("");
    setLoading(true);

    try {
      const [projectsData, usersData] = await Promise.all([
        apiGet("/api/projects/"),
        apiGet("/api/users/"),
      ]);
      console.log(usersData)
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

  function addMember(user) {
    setSelectedMembers((prev) => {
      if (prev.some((m) => m.id === user.id)) return prev;
      return [...prev, user];
    });
    setMemberQuery("");
  }

  function removeMember(userId) {
    setSelectedMembers((prev) => prev.filter((m) => m.id !== userId));
  }

  const filteredUsers = useMemo(() => {
    const q = memberQuery.trim().toLowerCase();
    if (!q) return [];

    return users
      .filter((u) => {
        const alreadySelected = selectedMembers.some((m) => m.id === u.id);
        if (alreadySelected) return false;

        const username = (u.username || "").toLowerCase();
        const email = (u.email || "").toLowerCase();
        return username.includes(q) || email.includes(q);
      })
      .slice(0, 10);
  }, [users, memberQuery, selectedMembers]);

  async function createProject(e) {
    e.preventDefault();
    setErr("");

    try {
      await apiPost("/api/projects/", {
        name,
        code,
        description,
        members: selectedMembers.map((m) => m.id),
      });

      setName("");
      setCode("");
      setDescription("");
      setMemberQuery("");
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

            <div className="mt-4">
              <div className="fw-semibold mb-2">Team Members</div>

              <Form.Control
                placeholder="Search users by username or email"
                value={memberQuery}
                onChange={(e) => setMemberQuery(e.target.value)}
              />

              {memberQuery && (
                <Card className="mt-2 border">
                  <Card.Body className="py-2">
                    {filteredUsers.length === 0 ? (
                      <div className="text-muted small">No matching users.</div>
                    ) : (
                      <div className="d-grid gap-2">
                        {filteredUsers.map((u) => (
                          <div
                            key={u.id}
                            className="d-flex justify-content-between align-items-center"
                          >
                            <div>
                              <div className="fw-semibold">{u.username}</div>
                              <div className="text-muted small">{u.email || "-"}</div>
                            </div>
                            <Button
                              size="sm"
                              variant="outline-dark"
                              onClick={() => addMember(u)}
                            >
                              Add
                            </Button>
                          </div>
                        ))}
                      </div>
                    )}
                  </Card.Body>
                </Card>
              )}

              <div className="mt-3">
                {selectedMembers.length === 0 ? (
                  <div className="text-muted small">No team members selected yet.</div>
                ) : (
                  <div className="d-flex flex-wrap gap-2">
                    {selectedMembers.map((u) => (
                      <Badge
                        key={u.id}
                        bg="secondary"
                        className="d-flex align-items-center gap-2 px-3 py-2"
                      >
                        <span>{u.username}</span>
                        <button
                          type="button"
                          onClick={() => removeMember(u.id)}
                          style={{
                            background: "transparent",
                            border: "none",
                            color: "white",
                            fontWeight: "bold",
                            cursor: "pointer",
                            padding: 0,
                            lineHeight: 1,
                          }}
                        >
                          ×
                        </button>
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            </div>

            <div className="mt-4">
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