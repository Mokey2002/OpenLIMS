import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, Col, Form, Row, Table } from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGet, apiPost } from "../api";

async function apiGetAllPages(basePath) {
  const separator = basePath.includes("?") ? "&" : "?";
  let page = 1;
  let results = [];

  while (page <= 100) {
    const data = await apiGet(`${basePath}${separator}page=${page}`);

    if (!data?.results) {
      return data || [];
    }

    results = [...results, ...data.results];

    if (!data.next) break;

    page += 1;
  }

  return results;
}

export default function Projects() {
  const [projects, setProjects] = useState([]);
  const [users, setUsers] = useState([]);
  const [me, setMe] = useState(null);
  const [err, setErr] = useState("");
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [description, setDescription] = useState("");
  const [memberQuery, setMemberQuery] = useState("");
  const [projectQuery, setProjectQuery] = useState("");
  const [selectedMembers, setSelectedMembers] = useState([]);

  async function load() {
    setErr("");

    try {
      const [projectsData, meData] = await Promise.all([
        apiGetAllPages("/api/projects/"),
        apiGet("/api/me/"),
      ]);

      setProjects(projectsData);
      setMe(meData);

      if (meData?.roles?.includes("admin")) {
        const usersData = await apiGetAllPages("/api/users/");
        setUsers(usersData);
      }
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  useEffect(() => {
    load();
  }, []);

  const isAdmin = me?.roles?.includes("admin");

  function addMember(user) {
    setSelectedMembers((prev) =>
      prev.some((m) => m.id === user.id) ? prev : [...prev, user]
    );

    setMemberQuery("");
  }

  function removeMember(userId) {
    setSelectedMembers((prev) => prev.filter((m) => m.id !== userId));
  }

  const filteredUsers = useMemo(() => {
    const q = memberQuery.trim().toLowerCase();

    if (!q) return [];

    return users
      .filter((u) => !selectedMembers.some((m) => m.id === u.id))
      .filter(
        (u) =>
          (u.username || "").toLowerCase().includes(q) ||
          (u.email || "").toLowerCase().includes(q)
      )
      .slice(0, 10);
  }, [users, memberQuery, selectedMembers]);

  const filteredProjects = useMemo(() => {
    const q = projectQuery.trim().toLowerCase();

    if (!q) return projects;

    return projects.filter((project) =>
      [
        project.id,
        project.code,
        project.name,
        project.description,
        ...(project.member_usernames || []),
      ]
        .join(" ")
        .toLowerCase()
        .includes(q)
    );
  }, [projects, projectQuery]);

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
      <div className="page-header">
        <div>
          <h1 className="page-title">Projects</h1>
          <p className="page-subtitle">
            Organize work, teams, and project-specific samples.
          </p>
        </div>

        <Button variant="outline-dark" size="sm" onClick={load}>
          Refresh
        </Button>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      {isAdmin && (
        <Card className="app-card mb-4">
          <Card.Body>
            <h5 className="section-title">Create Project</h5>

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
                <div className="feed-meta mb-2">Team Members</div>

                <Form.Control
                  placeholder="Search users by username or email"
                  value={memberQuery}
                  onChange={(e) => setMemberQuery(e.target.value)}
                />

                {memberQuery && (
                  <Card className="app-card mt-3">
                    <Card.Body>
                      {filteredUsers.length === 0 ? (
                        <div className="empty-state">No matching users.</div>
                      ) : (
                        <div className="d-grid gap-2">
                          {filteredUsers.map((u) => (
                            <div
                              key={u.id}
                              className="d-flex justify-content-between align-items-center soft-card"
                            >
                              <div>
                                <div className="fw-semibold">{u.username}</div>
                                <div className="feed-meta">{u.email || "-"}</div>
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

                <div className="mt-3 d-flex flex-wrap gap-2">
                  {selectedMembers.length === 0 ? (
                    <div className="empty-state">
                      No team members selected yet.
                    </div>
                  ) : (
                    selectedMembers.map((u) => (
                      <span key={u.id} className="click-chip">
                        {u.username}
                        <button
                          type="button"
                          onClick={() => removeMember(u.id)}
                        >
                          ×
                        </button>
                      </span>
                    ))
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
      )}

      <Card className="app-card">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Existing Projects</h5>
              <div className="feed-meta">
                Showing {filteredProjects.length} of {projects.length} projects
              </div>
            </div>

            <Form.Control
              style={{ maxWidth: 320 }}
              placeholder="Search projects by code, name, or member"
              value={projectQuery}
              onChange={(e) => setProjectQuery(e.target.value)}
            />
          </div>

          {filteredProjects.length === 0 ? (
            <div className="empty-state">No projects found.</div>
          ) : (
            <Table responsive hover className="app-table">
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
                {filteredProjects.map((p) => (
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
