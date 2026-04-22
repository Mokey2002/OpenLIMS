import { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { Alert, Badge, Button, Card, Form, Row, Col, Table } from "react-bootstrap";
import { apiGet, apiPatch, apiPostForm } from "../api";

function formatTimestamp(ts) {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export default function ProjectDetail() {
  const { id } = useParams();

  const [project, setProject] = useState(null);
  const [samples, setSamples] = useState([]);
  const [posts, setPosts] = useState([]);
  const [users, setUsers] = useState([]);
  const [me, setMe] = useState(null);

  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingMembers, setSavingMembers] = useState(false);

  const [note, setNote] = useState("");
  const [image, setImage] = useState(null);

  const [memberQuery, setMemberQuery] = useState("");
  const [selectedMembers, setSelectedMembers] = useState([]);

  async function load() {
    setErr("");
    setLoading(true);

    try {
      const [projectData, samplesData, postsData, meData] = await Promise.all([
        apiGet(`/api/projects/${id}/`),
        apiGet(`/api/samples/?project=${id}`),
        apiGet(`/api/project-posts/?project=${id}`),
        apiGet(`/api/me/`),
      ]);

      const sampleList = samplesData.results || samplesData || [];
      const postList = postsData.results || postsData || [];

      setProject(projectData);
      setSamples(sampleList);
      setPosts(postList);
      setMe(meData);

      const initialMembers = (projectData.members || []).map((memberId, idx) => ({
        id: memberId,
        username: projectData.member_usernames?.[idx] || `user-${memberId}`,
      }));
      setSelectedMembers(initialMembers);

      if (meData?.roles?.includes("admin")) {
        const usersData = await apiGet("/api/users/");
        setUsers(usersData.results || usersData || []);
      }
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [id]);

  const isAdmin = me?.roles?.includes("admin");

  async function createPost(e) {
    e.preventDefault();
    setErr("");

    try {
      const formData = new FormData();
      formData.append("project", id);
      formData.append("note", note);
      if (image) formData.append("image", image);

      await apiPostForm("/api/project-posts/", formData);

      setNote("");
      setImage(null);
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  function addMember(user) {
    setSelectedMembers((prev) => {
      if (prev.some((m) => m.id === user.id)) return prev;
      return [...prev, { id: user.id, username: user.username }];
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

  async function saveMembers() {
    setErr("");
    setSavingMembers(true);

    try {
      const updated = await apiPatch(`/api/projects/${id}/`, {
        members: selectedMembers.map((m) => m.id),
      });

      setProject(updated);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setSavingMembers(false);
    }
  }

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

          {isAdmin && (
            <Card className="shadow-sm border-0 mb-4">
              <Card.Body>
                <h5 className="mb-3">Manage Team</h5>

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
                    <div className="text-muted small">No team members selected.</div>
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

                <div className="mt-3">
                  <Button variant="dark" onClick={saveMembers} disabled={savingMembers}>
                    {savingMembers ? "Saving..." : "Save Team"}
                  </Button>
                </div>
              </Card.Body>
            </Card>
          )}

          <Card className="shadow-sm border-0 mb-4">
            <Card.Body>
              <h5 className="mb-3">Project Feed</h5>

              <Form onSubmit={createPost} className="mb-4">
                <Row className="g-2">
                  <Col md={8}>
                    <Form.Control
                      as="textarea"
                      rows={3}
                      placeholder="Post a note to this project"
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                    />
                  </Col>
                  <Col md={2}>
                    <Form.Control
                      type="file"
                      accept="image/*"
                      onChange={(e) => setImage(e.target.files?.[0] || null)}
                    />
                  </Col>
                  <Col md={2}>
                    <Button
                      type="submit"
                      variant="dark"
                      className="w-100"
                      disabled={!note && !image}
                    >
                      Post
                    </Button>
                  </Col>
                </Row>
              </Form>

              {posts.length === 0 ? (
                <Alert variant="light" className="mb-0">
                  No posts yet.
                </Alert>
              ) : (
                <div className="d-grid gap-3">
                  {posts.map((post) => (
                    <Card key={post.id} className="bg-light border-0">
                      <Card.Body>
                        <div className="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-2">
                          <div className="fw-semibold">
                            {post.author_username || "Unknown user"}
                          </div>
                          <small className="text-muted">
                            {formatTimestamp(post.created_at)}
                          </small>
                        </div>

                        {post.note && <div className="mb-2">{post.note}</div>}

                        {post.image && (
                          <img
                            src={`http://localhost:8000${post.image}`}
                            alt="Project post"
                            style={{
                              maxWidth: "100%",
                              maxHeight: "320px",
                              borderRadius: "8px",
                              border: "1px solid #ddd",
                            }}
                          />
                        )}
                      </Card.Body>
                    </Card>
                  ))}
                </div>
              )}
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