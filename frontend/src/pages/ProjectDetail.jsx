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
import { canWrite, isAdmin, readOnlyMessage } from "../authz";

function formatTimestamp(ts) {
  if (!ts) return "-";

  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function sampleStatusVariant(status) {
  switch (status) {
    case "RECEIVED":
      return "secondary";
    case "IN_PROGRESS":
      return "primary";
    case "QC":
      return "warning";
    case "REPORTED":
      return "success";
    case "ARCHIVED":
      return "dark";
    default:
      return "light";
  }
}

function qcVariant(status) {
  switch (status) {
    case "APPROVED":
      return "success";
    case "REJECTED":
      return "danger";
    case "RERUN_REQUIRED":
      return "warning";
    case "PENDING_REVIEW":
      return "secondary";
    default:
      return "light";
  }
}

function qcLabel(status) {
  switch (status) {
    case "APPROVED":
      return "Approved";
    case "REJECTED":
      return "Rejected";
    case "RERUN_REQUIRED":
      return "Re-run Required";
    case "PENDING_REVIEW":
      return "Pending Review";
    default:
      return status || "Pending Review";
  }
}

function jobVariant(status) {
  switch (status) {
    case "COMPLETED":
      return "success";
    case "FAILED":
      return "danger";
    case "RUNNING":
      return "primary";
    case "PENDING":
      return "warning";
    default:
      return "secondary";
  }
}

function countBy(items, field) {
  return items.reduce((acc, item) => {
    const key = item[field] || "UNKNOWN";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
}

export default function ProjectDetail() {
  const { id } = useParams();

  const [project, setProject] = useState(null);
  const [samples, setSamples] = useState([]);
  const [workItems, setWorkItems] = useState([]);
  const [posts, setPosts] = useState([]);
  const [users, setUsers] = useState([]);
  const [imports, setImports] = useState([]);
  const [sequences, setSequences] = useState([]);
  const [alignments, setAlignments] = useState([]);
  const [events, setEvents] = useState([]);
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
      const [
        projectData,
        samplesData,
        workItemsData,
        postsData,
        importsData,
        sequencesData,
        alignmentsData,
        eventsData,
        meData,
      ] = await Promise.all([
        apiGet(`/api/projects/${id}/`),
        apiGet(`/api/samples/?project=${id}`),
        apiGet(`/api/work-items/?project=${id}`),
        apiGet(`/api/project-posts/?project=${id}`),
        apiGet(`/api/import-jobs/`),
        apiGet(`/api/sequences/?project=${id}`),
        apiGet(`/api/alignment-jobs/?project=${id}`),
        apiGet(`/api/events/`),
        apiGet(`/api/me/`),
      ]);

      const sampleList = samplesData.results || samplesData || [];
      const workItemList = workItemsData.results || workItemsData || [];
      const postList = postsData.results || postsData || [];
      const importList = importsData.results || importsData || [];
      const sequenceList = sequencesData.results || sequencesData || [];
      const alignmentList = alignmentsData.results || alignmentsData || [];
      const eventList = eventsData.results || eventsData || [];

      setProject(projectData);
      setSamples(sampleList);
      setWorkItems(workItemList);
      setPosts(postList);
      setSequences(sequenceList);
      setAlignments(alignmentList);
      setMe(meData);

      setImports(
        importList.filter((job) => String(job.project) === String(id))
      );

      setEvents(
        eventList.filter((event) => {
          const payload = event.payload || {};

          return (
            String(payload.project_id) === String(id) ||
            String(payload.project) === String(id) ||
            payload.project_code === projectData.code ||
            (
              event.entity_type === "Project" &&
              String(event.entity_id) === String(id)
            )
          );
        })
      );

      const initialMembers = (projectData.members || []).map(
        (memberId, idx) => ({
          id: memberId,
          username: projectData.member_usernames?.[idx] || `user-${memberId}`,
        })
      );

      setSelectedMembers(initialMembers);

      if (isAdmin(meData)) {
        const usersData = await apiGet("/api/users/");
        setUsers(usersData.results || usersData || []);
      }
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const userIsAdmin = isAdmin(me);
  const userCanWrite = canWrite(me);
  const readOnlyText = readOnlyMessage(me);

  const filteredUsers = useMemo(() => {
    const q = memberQuery.trim().toLowerCase();

    if (!q) return [];

    return users
      .filter((user) => !selectedMembers.some((member) => member.id === user.id))
      .filter(
        (user) =>
          (user.username || "").toLowerCase().includes(q) ||
          (user.email || "").toLowerCase().includes(q)
      )
      .slice(0, 10);
  }, [users, memberQuery, selectedMembers]);

  const sampleStatusCounts = useMemo(() => {
    return countBy(samples, "status");
  }, [samples]);

  const qcStats = useMemo(() => {
    return {
      pending: workItems.filter((item) => item.qc_status === "PENDING_REVIEW")
        .length,
      approved: workItems.filter((item) => item.qc_status === "APPROVED")
        .length,
      rejected: workItems.filter((item) => item.qc_status === "REJECTED")
        .length,
      rerun: workItems.filter((item) => item.qc_status === "RERUN_REQUIRED")
        .length,
    };
  }, [workItems]);

  const openReviewItems = useMemo(() => {
    return workItems.filter((item) =>
      ["PENDING_REVIEW", "REJECTED", "RERUN_REQUIRED"].includes(item.qc_status)
    );
  }, [workItems]);

  const recentImports = useMemo(() => {
    return [...imports]
      .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
      .slice(0, 5);
  }, [imports]);

  const recentAlignments = useMemo(() => {
    return [...alignments]
      .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
      .slice(0, 5);
  }, [alignments]);

  const recentEvents = useMemo(() => {
    return [...events]
      .sort((a, b) => new Date(b.timestamp || b.created_at) - new Date(a.timestamp || a.created_at))
      .slice(0, 8);
  }, [events]);

  async function createPost(e) {
    e.preventDefault();
    setErr("");

    if (!userCanWrite) return;

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

  async function saveMembers() {
    setErr("");
    setSavingMembers(true);

    if (!userIsAdmin) {
      setSavingMembers(false);
      return;
    }

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

  if (!project) {
    return (
      <div className="w-100">
        {err ? (
          <Alert variant="danger">{err}</Alert>
        ) : (
          <Card className="app-card">
            <Card.Body>Loading project...</Card.Body>
          </Card>
        )}
      </div>
    );
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">{project.name}</h1>
          <p className="page-subtitle">
            {project.code} · Project dashboard, QC review, imports, sequences,
            alignments, and team activity.
          </p>
        </div>

        <div className="inline-actions">
          <Badge bg="dark">{project.sample_count ?? samples.length} samples</Badge>
          <Button variant="outline-dark" size="sm" onClick={load}>
            Refresh
          </Button>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}
      {readOnlyText && <Alert variant="info">{readOnlyText}</Alert>}

      <div className="stat-grid mb-4">
        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Samples</div>
            <div className="metric-value">{samples.length}</div>
            <div className="metric-note">Linked to this project</div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">QC Pending</div>
            <div className="metric-value">{qcStats.pending}</div>
            <div className="metric-note">
              Approved: {qcStats.approved} · Re-run: {qcStats.rerun}
            </div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Import Jobs</div>
            <div className="metric-value">{imports.length}</div>
            <div className="metric-note">
              Failed: {imports.filter((job) => job.status === "FAILED").length}
            </div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Sequences</div>
            <div className="metric-value">{sequences.length}</div>
            <div className="metric-note">
              Alignments: {alignments.length}
            </div>
          </Card.Body>
        </Card>
      </div>

      <Row className="g-4 mb-4">
        <Col lg={8}>
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Project Overview</h5>

              <div className="soft-card mb-3">
                <div className="feed-meta">Description</div>
                <div>{project.description || "No description"}</div>
              </div>

              <div className="soft-card">
                <div className="feed-meta">Team Members</div>
                <div>
                  {project.member_usernames?.length
                    ? project.member_usernames.join(", ")
                    : "No members assigned"}
                </div>
              </div>
            </Card.Body>
          </Card>
        </Col>

        {userIsAdmin && (
          <Col lg={4}>
            <Card className="app-card h-100">
              <Card.Body>
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
                        <div className="empty-state">No matching users.</div>
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
              </Card.Body>
            </Card>
          </Col>
        )}
      </Row>

      <Row className="g-4 mb-4">
        <Col lg={6}>
          <Card className="app-card h-100">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">Samples by Status</h5>
                <Badge bg="dark">{samples.length}</Badge>
              </div>

              {Object.keys(sampleStatusCounts).length === 0 ? (
                <div className="empty-state">No samples yet.</div>
              ) : (
                <div className="d-grid gap-2">
                  {Object.entries(sampleStatusCounts).map(([status, count]) => (
                    <div
                      key={status}
                      className="d-flex justify-content-between align-items-center soft-card"
                    >
                      <Badge bg={sampleStatusVariant(status)}>{status}</Badge>
                      <strong>{count}</strong>
                    </div>
                  ))}
                </div>
              )}
            </Card.Body>
          </Card>
        </Col>

        <Col lg={6}>
          <Card className="app-card h-100">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">QC Review Queue</h5>
                <Badge bg="dark">{openReviewItems.length}</Badge>
              </div>

              {openReviewItems.length === 0 ? (
                <div className="empty-state">No open QC review items.</div>
              ) : (
                <Table responsive hover className="app-table">
                  <thead>
                    <tr>
                      <th>Work Item</th>
                      <th>Sample</th>
                      <th>QC</th>
                    </tr>
                  </thead>

                  <tbody>
                    {openReviewItems.slice(0, 8).map((item) => (
                      <tr key={item.id}>
                        <td>{item.name}</td>
                        <td>
                          <Link to={`/samples/${item.sample}`}>
                            Sample #{item.sample}
                          </Link>
                        </td>
                        <td>
                          <Badge bg={qcVariant(item.qc_status)}>
                            {qcLabel(item.qc_status)}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="g-4 mb-4">
        <Col lg={6}>
          <Card className="app-card h-100">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">Recent Imports</h5>
                <Badge bg="dark">{imports.length}</Badge>
              </div>

              {recentImports.length === 0 ? (
                <div className="empty-state">No import jobs for this project.</div>
              ) : (
                <Table responsive hover className="app-table">
                  <thead>
                    <tr>
                      <th>Instrument</th>
                      <th>Status</th>
                      <th>Created</th>
                    </tr>
                  </thead>

                  <tbody>
                    {recentImports.map((job) => (
                      <tr key={job.id}>
                        <td>
                          <Link to={`/imports/${job.id}`}>
                            {job.instrument_code || job.instrument_name || `Import #${job.id}`}
                          </Link>
                        </td>
                        <td>
                          <Badge bg={jobVariant(job.status)}>
                            {job.status}
                          </Badge>
                        </td>
                        <td>{formatTimestamp(job.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </Col>

        <Col lg={6}>
          <Card className="app-card h-100">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">Recent Alignments</h5>
                <Badge bg="dark">{alignments.length}</Badge>
              </div>

              {recentAlignments.length === 0 ? (
                <div className="empty-state">No alignments for this project.</div>
              ) : (
                <Table responsive hover className="app-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Status</th>
                      <th>Created</th>
                    </tr>
                  </thead>

                  <tbody>
                    {recentAlignments.map((job) => (
                      <tr key={job.id}>
                        <td>{job.name}</td>
                        <td>
                          <Badge bg={jobVariant(job.status)}>
                            {job.status}
                          </Badge>
                        </td>
                        <td>{formatTimestamp(job.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <ProjectSequences projectId={project.id} />

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Project Feed</h5>

          {userCanWrite && (
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
          )}

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

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <h5 className="section-title mb-0">Recent Project Activity</h5>
            <Badge bg="dark">{recentEvents.length}</Badge>
          </div>

          {recentEvents.length === 0 ? (
            <div className="empty-state">No project activity found.</div>
          ) : (
            <Table responsive hover className="app-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Actor</th>
                  <th>Entity</th>
                  <th>Action</th>
                </tr>
              </thead>

              <tbody>
                {recentEvents.map((event) => (
                  <tr key={event.id}>
                    <td>{formatTimestamp(event.timestamp || event.created_at)}</td>
                    <td>{event.actor_username || event.actor || "-"}</td>
                    <td>{event.entity_type}</td>
                    <td>
                      <Badge bg="secondary">{event.action}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>

      <Card className="app-card">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <h5 className="section-title mb-0">Project Samples</h5>
            <div className="feed-meta">{samples.length} linked samples</div>
          </div>

          {samples.length === 0 ? (
            <div className="empty-state">No samples in this project yet.</div>
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

                    <td>
                      <Badge bg={sampleStatusVariant(sample.status)}>
                        {sample.status}
                      </Badge>
                    </td>
                    <td>{sample.container_code || "-"}</td>
                    <td>{formatTimestamp(sample.created_at)}</td>
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