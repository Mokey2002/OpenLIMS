import { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  Card,
  Form,
  Row,
  Col,
  Table,
} from "react-bootstrap";
import { apiGet, apiPatch, apiPostForm } from "../api";
import ProjectSequences from "../components/ProjectSequences";

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
  const [savingMembers, setSavingMembers] = useState(false);

  const [note, setNote] = useState("");
  const [image, setImage] = useState(null);

  const [memberQuery, setMemberQuery] = useState("");
  const [selectedMembers, setSelectedMembers] = useState([]);

  async function load() {
    setErr("");

    try {
      const [projectData, samplesData, postsData, meData] = await Promise.all([
        apiGet(`/api/projects/${id}/`),
        apiGet(`/api/samples/?project=${id}`),
        apiGet(`/api/project-posts/?project=${id}`),
        apiGet(`/api/me/`),
      ]);

      setProject(projectData);
      setSamples(samplesData.results || samplesData || []);
      setPosts(postsData.results || postsData || []);
      setMe(meData);

      const initialMembers = (projectData.members || []).map(
        (memberId, idx) => ({
          id: memberId,
          username: projectData.member_usernames?.[idx] || `user-${memberId}`,
        })
      );

      setSelectedMembers(initialMembers);

      if (meData?.roles?.includes("admin")) {
        const usersData = await apiGet("/api/users/");
        setUsers(usersData.results || usersData || []);
      }
    } catch (e) {
      setErr(e.message || String(e));
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

      if (image) {
        formData.append("image", image);
      }

      await apiPostForm("/api/project-posts/", formData);

      setNote("");
      setImage(null);

      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  function addMember(user) {
    setSelectedMembers((prev) =>
      prev.some((member) => member.id === user.id)
        ? prev
        : [...prev, { id: user.id, username: user.username }]
    );

    setMemberQuery("");
  }

  function removeMember(userId) {
    setSelectedMembers((prev) =>
      prev.filter((member) => member.id !== userId)
    );
  }

  const filteredUsers = useMemo(() => {
    const q = memberQuery.trim().toLowerCase();

    if (!q) {
      return [];
    }

    return users
      .filter((user) => !selectedMembers.some((member) => member.id === user.id))
      .filter(
        (user) =>
          (user.username || "").toLowerCase().includes(q) ||
          (user.email || "").toLowerCase().includes(q)
      )
      .slice(0, 10);
  }, [users, memberQuery, selectedMembers]);

  async function saveMembers() {
    setErr("");
    setSavingMembers(true);

    try {
      const updated = await apiPatch(`/api/projects/${id}/`, {
        members: selectedMembers.map((member) => member.id),
      });

      setProject(updated);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setSavingMembers(false);
    }
  }

  return (
    <div className="w-100">
      {project && (
        <>
          <div className="page-header">
            <div>
              <h1 className="page-title">{project.name}</h1>
              <p className="page-subtitle">{project.code}</p>
            </div>

            <Badge bg="dark">{project.sample_count ?? 0} samples</Badge>
          </div>

          {err && <Alert variant="danger">{err}</Alert>}

          <Card className="app-card mb-4">
            <Card.Body>
              <div className="row g-4">
                <div className="col-lg-8">
                  <h5 className="section-title">Project Overview</h5>

                  <div className="soft-card">
                    <div className="mb-3">
                      <div className="feed-meta">Description</div>
                      <div>{project.description || "No description"}</div>
                    </div>

                    <div>
                      <div className="feed-meta">Team Members</div>
                      <div>
                        {project.member_usernames?.length
                          ? project.member_usernames.join(", ")
                          : "No members assigned"}
                      </div>
                    </div>
                  </div>
                </div>

                {isAdmin && (
                  <div className="col-lg-4">
                    <h5 className="section-title">Manage Team</h5>

                    <Form.Control
                      placeholder="Search users by username or email"
                      value={memberQuery}
                      onChange={(e) => setMemberQuery(e.target.value)}
                    />

                    {memberQuery && (
                      <Card className="app-card mt-3">
                        <Card.Body>
                          {filteredUsers.length === 0 ? (
                            <div className="empty-state">
                              No matching users.
                            </div>
                          ) : (
                            <div className="d-grid gap-2">
                              {filteredUsers.map((user) => (
                                <div
                                  key={user.id}
                                  className="d-flex justify-content-between align-items-center soft-card"
                                >
                                  <div>
                                    <div className="fw-semibold">
                                      {user.username}
                                    </div>
                                    <div className="feed-meta">
                                      {user.email || "-"}
                                    </div>
                                  </div>

                                  <Button
                                    size="sm"
                                    variant="outline-dark"
                                    onClick={() => addMember(user)}
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
                          No team members selected.
                        </div>
                      ) : (
                        selectedMembers.map((user) => (
                          <span key={user.id} className="click-chip">
                            {user.username}
                            <button
                              type="button"
                              onClick={() => removeMember(user.id)}
                            >
                              ×
                            </button>
                          </span>
                        ))
                      )}
                    </div>

                    <Button
                      className="mt-3"
                      variant="dark"
                      onClick={saveMembers}
                      disabled={savingMembers}
                    >
                      {savingMembers ? "Saving..." : "Save Team"}
                    </Button>
                  </div>
                )}
              </div>
            </Card.Body>
          </Card>

          <Card className="app-card mb-4">
            <Card.Body>
              <h5 className="section-title">Project Feed</h5>

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
                <div className="empty-state">No posts yet.</div>
              ) : (
                <div className="d-grid gap-3">
                  {posts.map((post) => (
                    <div key={post.id} className="feed-item">
                      <div className="d-flex justify-content-between align-items-start gap-2 flex-wrap mb-2">
                        <div className="fw-semibold">
                          {post.author_username || "Unknown user"}
                        </div>

                        <div className="feed-meta">
                          {formatTimestamp(post.created_at)}
                        </div>
                      </div>

                      {post.note && <div className="mb-2">{post.note}</div>}

                      {post.image && (
                        <img
                          src={post.image}
                          alt="Project post"
                          className="thumbnail"
                        />
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Card.Body>
          </Card>

          <ProjectSequences projectId={project.id} />

          <Card className="app-card">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">Project Samples</h5>
                <div className="feed-meta">{samples.length} linked samples</div>
              </div>

              {samples.length === 0 ? (
                <div className="empty-state">
                  No samples in this project yet.
                </div>
              ) : (
                <Table responsive hover className="app-table">
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
                    {samples.map((sample) => (
                      <tr key={sample.id}>
                        <td>{sample.id}</td>

                        <td>
                          <Link to={`/samples/${sample.id}`}>
                            {sample.sample_id}
                          </Link>
                        </td>

                        <td>{sample.status}</td>
                        <td>{sample.container_code || "-"}</td>
                        <td>{formatTimestamp(sample.created_at)}</td>
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