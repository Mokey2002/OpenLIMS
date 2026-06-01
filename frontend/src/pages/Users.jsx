import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  Row,
  Spinner,
  Table,
} from "react-bootstrap";
import { apiDelete, apiGet, apiPatch, apiPost } from "../api";
import { isAdmin } from "../authz";

function formatTimestamp(value) {
  if (!value) return "-";

  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function roleVariant(role) {
  switch (role) {
    case "admin":
      return "dark";
    case "tech":
      return "primary";
    case "viewer":
      return "secondary";
    default:
      return "light";
  }
}

function statusVariant(user) {
  if (!user.is_active) return "danger";
  if (user.is_superuser) return "dark";
  if (user.is_staff) return "info";
  return "success";
}

function statusLabel(user) {
  if (!user.is_active) return "Disabled";
  if (user.is_superuser) return "Director/Admin";
  if (user.is_staff) return "Staff";
  return "Active";
}

function primaryRole(user) {
  return user.roles?.[0] || "viewer";
}

export default function Users() {
  const [me, setMe] = useState(null);
  const [users, setUsers] = useState([]);

  const [err, setErr] = useState("");
  const [success, setSuccess] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("tech");

  const [editingUserId, setEditingUserId] = useState(null);
  const [editForm, setEditForm] = useState({
    email: "",
    first_name: "",
    last_name: "",
    role: "tech",
    is_active: true,
  });

  async function load() {
    setErr("");
    setLoading(true);

    try {
      const [meData, usersData] = await Promise.all([
        apiGet("/api/me/"),
        apiGet("/api/admin-users/"),
      ]);

      setMe(meData);
      setUsers(usersData.results || usersData || []);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const userIsAdmin = isAdmin(me);

  const stats = useMemo(() => {
    return {
      total: users.length,
      active: users.filter((user) => user.is_active).length,
      disabled: users.filter((user) => !user.is_active).length,
      admins: users.filter((user) => user.roles?.includes("admin")).length,
      techs: users.filter((user) => user.roles?.includes("tech")).length,
      viewers: users.filter((user) => user.roles?.includes("viewer")).length,
    };
  }, [users]);

  async function createUser(e) {
    e.preventDefault();

    setErr("");
    setSuccess("");

    if (!username || !password) {
      setErr("Username and password are required.");
      return;
    }

    setSaving(true);

    try {
      await apiPost("/api/admin-users/", {
        username,
        email,
        first_name: firstName,
        last_name: lastName,
        password,
        role,
      });

      setUsername("");
      setEmail("");
      setFirstName("");
      setLastName("");
      setPassword("");
      setRole("tech");

      setSuccess("User created successfully.");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  function startEdit(user) {
    setEditingUserId(user.id);
    setEditForm({
      email: user.email || "",
      first_name: user.first_name || "",
      last_name: user.last_name || "",
      role: primaryRole(user),
      is_active: Boolean(user.is_active),
    });
    setErr("");
    setSuccess("");
  }

  function cancelEdit() {
    setEditingUserId(null);
    setEditForm({
      email: "",
      first_name: "",
      last_name: "",
      role: "tech",
      is_active: true,
    });
  }

  function updateEditField(field, value) {
    setEditForm((current) => ({
      ...current,
      [field]: value,
    }));
  }

  async function saveUser(userId) {
    setErr("");
    setSuccess("");
    setSaving(true);

    try {
      await apiPatch(`/api/admin-users/${userId}/`, editForm);

      setEditingUserId(null);
      setSuccess("User updated successfully.");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  async function toggleActive(user) {
    setErr("");
    setSuccess("");

    const nextStatus = !user.is_active;

    const confirmed = window.confirm(
      `${nextStatus ? "Activate" : "Disable"} user "${user.username}"?`
    );

    if (!confirmed) return;

    try {
      await apiPatch(`/api/admin-users/${user.id}/`, {
        is_active: nextStatus,
      });

      setSuccess(
        nextStatus
          ? `User "${user.username}" activated.`
          : `User "${user.username}" disabled.`
      );

      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function deleteUser(userId, usernameValue) {
    const confirmed = window.confirm(
      `Are you sure you want to permanently delete user "${usernameValue}"?`
    );

    if (!confirmed) return;

    setErr("");
    setSuccess("");

    try {
      await apiDelete(`/api/admin-users/${userId}/`);

      setSuccess("User deleted successfully.");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  if (loading) {
    return (
      <div className="d-flex align-items-center gap-2">
        <Spinner animation="border" size="sm" />
        <span>Loading users...</span>
      </div>
    );
  }

  if (me && !userIsAdmin) {
    return (
      <div className="w-100">
        <div className="page-header">
          <div>
            <h1 className="page-title">Users</h1>
            <p className="page-subtitle">Manage user access and roles.</p>
          </div>
        </div>

        <Alert variant="warning">
          Admin/director access required. You do not have permission to manage
          users.
        </Alert>
      </div>
    );
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">User Management</h1>
          <p className="page-subtitle">
            Manage users, roles, account status, and access controls.
          </p>
        </div>

        <div className="inline-actions">
          <Badge bg="dark">Admin only</Badge>
          <Button variant="outline-dark" size="sm" onClick={load}>
            Refresh
          </Button>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}
      {success && <Alert variant="success">{success}</Alert>}

      <div className="stat-grid mb-4">
        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Total Users</div>
            <div className="metric-value">{stats.total}</div>
            <div className="metric-note">All user accounts</div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Active</div>
            <div className="metric-value">{stats.active}</div>
            <div className="metric-note">Can login</div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Disabled</div>
            <div className="metric-value">{stats.disabled}</div>
            <div className="metric-note">Access blocked</div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Role Mix</div>
            <div className="metric-value" style={{ fontSize: "1.3rem" }}>
              {stats.admins}/{stats.techs}/{stats.viewers}
            </div>
            <div className="metric-note">Admin / Tech / Viewer</div>
          </Card.Body>
        </Card>
      </div>

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Create User</h5>

          <Form onSubmit={createUser}>
            <Row className="g-3">
              <Col md={3}>
                <Form.Group>
                  <Form.Label>Username</Form.Label>
                  <Form.Control
                    placeholder="username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                  />
                </Form.Group>
              </Col>

              <Col md={3}>
                <Form.Group>
                  <Form.Label>Email</Form.Label>
                  <Form.Control
                    placeholder="email@example.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </Form.Group>
              </Col>

              <Col md={3}>
                <Form.Group>
                  <Form.Label>First Name</Form.Label>
                  <Form.Control
                    placeholder="First"
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                  />
                </Form.Group>
              </Col>

              <Col md={3}>
                <Form.Group>
                  <Form.Label>Last Name</Form.Label>
                  <Form.Control
                    placeholder="Last"
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                  />
                </Form.Group>
              </Col>

              <Col md={4}>
                <Form.Group>
                  <Form.Label>Temporary Password</Form.Label>
                  <Form.Control
                    type="password"
                    placeholder="Temporary password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                </Form.Group>
              </Col>

              <Col md={4}>
                <Form.Group>
                  <Form.Label>Role</Form.Label>
                  <Form.Select
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
                  >
                    <option value="admin">Director/Admin</option>
                    <option value="tech">Lab Tech</option>
                    <option value="viewer">Viewer</option>
                  </Form.Select>
                </Form.Group>
              </Col>

              <Col md={4} className="d-flex align-items-end">
                <Button
                  type="submit"
                  variant="dark"
                  className="w-100"
                  disabled={saving}
                >
                  {saving ? "Creating..." : "Create User"}
                </Button>
              </Col>
            </Row>
          </Form>
        </Card.Body>
      </Card>

      <Card className="app-card">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Existing Users</h5>
              <div className="feed-meta">
                Role and status changes are recorded in the audit log.
              </div>
            </div>

            <Badge bg="dark">{users.length}</Badge>
          </div>

          {users.length === 0 ? (
            <div className="empty-state">No users found.</div>
          ) : (
            <Table responsive hover className="app-table align-middle">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Contact</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Last Login</th>
                  <th>Joined</th>
                  <th style={{ width: "280px" }}>Actions</th>
                </tr>
              </thead>

              <tbody>
                {users.map((user) => {
                  const isEditing = editingUserId === user.id;
                  const roles = user.roles || [];

                  return (
                    <tr key={user.id}>
                      <td>
                        <div className="fw-semibold">{user.username}</div>
                        <div className="feed-meta">
                          {isEditing ? (
                            <Row className="g-2 mt-1">
                              <Col>
                                <Form.Control
                                  size="sm"
                                  placeholder="First name"
                                  value={editForm.first_name}
                                  onChange={(e) =>
                                    updateEditField("first_name", e.target.value)
                                  }
                                />
                              </Col>
                              <Col>
                                <Form.Control
                                  size="sm"
                                  placeholder="Last name"
                                  value={editForm.last_name}
                                  onChange={(e) =>
                                    updateEditField("last_name", e.target.value)
                                  }
                                />
                              </Col>
                            </Row>
                          ) : (
                            user.full_name || `${user.first_name || ""} ${user.last_name || ""}`.trim() || "No name"
                          )}
                        </div>
                      </td>

                      <td>
                        {isEditing ? (
                          <Form.Control
                            size="sm"
                            value={editForm.email}
                            onChange={(e) =>
                              updateEditField("email", e.target.value)
                            }
                          />
                        ) : (
                          user.email || "-"
                        )}
                      </td>

                      <td>
                        {isEditing ? (
                          <Form.Select
                            size="sm"
                            value={editForm.role}
                            onChange={(e) =>
                              updateEditField("role", e.target.value)
                            }
                          >
                            <option value="admin">Director/Admin</option>
                            <option value="tech">Lab Tech</option>
                            <option value="viewer">Viewer</option>
                          </Form.Select>
                        ) : roles.length > 0 ? (
                          <div className="d-flex gap-1 flex-wrap">
                            {roles.map((roleName) => (
                              <Badge
                                key={roleName}
                                bg={roleVariant(roleName)}
                              >
                                {roleName}
                              </Badge>
                            ))}
                          </div>
                        ) : (
                          "-"
                        )}
                      </td>

                      <td>
                        {isEditing ? (
                          <Form.Check
                            type="switch"
                            label={editForm.is_active ? "Active" : "Disabled"}
                            checked={Boolean(editForm.is_active)}
                            onChange={(e) =>
                              updateEditField("is_active", e.target.checked)
                            }
                          />
                        ) : (
                          <Badge bg={statusVariant(user)}>
                            {statusLabel(user)}
                          </Badge>
                        )}
                      </td>

                      <td>{formatTimestamp(user.last_login)}</td>
                      <td>{formatTimestamp(user.date_joined)}</td>

                      <td>
                        {isEditing ? (
                          <div className="inline-actions">
                            <Button
                              size="sm"
                              variant="dark"
                              onClick={() => saveUser(user.id)}
                              disabled={saving}
                            >
                              Save
                            </Button>

                            <Button
                              size="sm"
                              variant="outline-secondary"
                              onClick={cancelEdit}
                              disabled={saving}
                            >
                              Cancel
                            </Button>
                          </div>
                        ) : (
                          <div className="inline-actions">
                            <Button
                              size="sm"
                              variant="outline-dark"
                              onClick={() => startEdit(user)}
                            >
                              Edit
                            </Button>

                            <Button
                              size="sm"
                              variant={
                                user.is_active
                                  ? "outline-warning"
                                  : "outline-success"
                              }
                              onClick={() => toggleActive(user)}
                            >
                              {user.is_active ? "Disable" : "Activate"}
                            </Button>

                            <Button
                              size="sm"
                              variant="outline-danger"
                              onClick={() =>
                                deleteUser(user.id, user.username)
                              }
                            >
                              Delete
                            </Button>
                          </div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>
    </div>
  );
}