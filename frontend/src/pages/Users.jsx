import { useEffect, useState } from "react";
import { Alert, Button, Card, Col, Form, Row, Table } from "react-bootstrap";
import { apiDelete, apiGet, apiPatch, apiPost } from "../api";

export default function Users() {
  const [users, setUsers] = useState([]);
  const [err, setErr] = useState("");
  const [success, setSuccess] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("tech");
  const [editingUserId, setEditingUserId] = useState(null);
  const [editRole, setEditRole] = useState("tech");

  async function load() {
    setErr("");
    try {
      const data = await apiGet("/api/admin-users/");
      setUsers(data.results || data || []);
    } catch (e) {
      setErr(e.message || String(e));
    }
  }
  useEffect(() => { load(); }, []);

  async function createUser(e) {
    e.preventDefault();
    setErr(""); setSuccess("");
    if (!username || !password) { setErr("Username and password are required."); return; }
    try {
      await apiPost("/api/admin-users/", { username, email, password, role });
      setUsername(""); setEmail(""); setPassword(""); setRole("tech");
      setSuccess("User created successfully.");
      await load();
    } catch (e) { setErr(e.message || String(e)); }
  }

  function startEdit(user) { setEditingUserId(user.id); setEditRole(user.roles?.[0] || "tech"); setErr(""); setSuccess(""); }
  function cancelEdit() { setEditingUserId(null); setEditRole("tech"); }

  async function saveRole(userId) {
    setErr(""); setSuccess("");
    try {
      await apiPatch(`/api/admin-users/${userId}/`, { role: editRole });
      setEditingUserId(null); setEditRole("tech");
      setSuccess("User role updated successfully.");
      await load();
    } catch (e) { setErr(e.message || String(e)); }
  }

  async function deleteUser(userId, usernameValue) {
    if (!window.confirm(`Are you sure you want to delete user "${usernameValue}"?`)) return;
    setErr(""); setSuccess("");
    try {
      await apiDelete(`/api/admin-users/${userId}/`);
      setSuccess("User deleted successfully.");
      await load();
    } catch (e) { setErr(e.message || String(e)); }
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div><h1 className="page-title">Users</h1><p className="page-subtitle">Manage user access and roles.</p></div>
      </div>
      {err && <Alert variant="danger">{err}</Alert>}
      {success && <Alert variant="success">{success}</Alert>}

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Create User</h5>
          <Form onSubmit={createUser}>
            <Row className="g-2">
              <Col md={3}><Form.Control placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} /></Col>
              <Col md={3}><Form.Control placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} /></Col>
              <Col md={3}><Form.Control type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} /></Col>
              <Col md={2}>
                <Form.Select value={role} onChange={(e) => setRole(e.target.value)}>
                  <option value="admin">admin</option><option value="tech">tech</option><option value="viewer">viewer</option>
                </Form.Select>
              </Col>
              <Col md={1}><Button type="submit" variant="dark" className="w-100">Add</Button></Col>
            </Row>
          </Form>
        </Card.Body>
      </Card>

      <Card className="app-card">
        <Card.Body>
          <h5 className="section-title">Existing Users</h5>
          {users.length === 0 ? (
            <div className="empty-state">No users found.</div>
          ) : (
            <Table responsive hover className="app-table">
              <thead><tr><th>ID</th><th>Username</th><th>Email</th><th>Role</th><th style={{ width: "220px" }}>Actions</th></tr></thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td>{u.id}</td>
                    <td>{u.username}</td>
                    <td>{u.email || "-"}</td>
                    <td>
                      {editingUserId === u.id ? (
                        <Form.Select size="sm" value={editRole} onChange={(e) => setEditRole(e.target.value)}>
                          <option value="admin">admin</option><option value="tech">tech</option><option value="viewer">viewer</option>
                        </Form.Select>
                      ) : u.roles?.join(", ") || "-"}
                    </td>
                    <td>
                      {editingUserId === u.id ? (
                        <div className="inline-actions">
                          <Button size="sm" variant="dark" onClick={() => saveRole(u.id)}>Save</Button>
                          <Button size="sm" variant="outline-secondary" onClick={cancelEdit}>Cancel</Button>
                        </div>
                      ) : (
                        <div className="inline-actions">
                          <Button size="sm" variant="outline-dark" onClick={() => startEdit(u)}>Edit</Button>
                          <Button size="sm" variant="outline-danger" onClick={() => deleteUser(u.id, u.username)}>Delete</Button>
                        </div>
                      )}
                    </td>
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
