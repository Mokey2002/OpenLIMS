import { useEffect, useState } from "react";
import { Alert, Button, Card, Col, Form, Row, Table } from "react-bootstrap";
import { apiGet, apiPost } from "../api";

export default function Users() {
  const [users, setUsers] = useState([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("tech");

  async function load() {
    setErr("");
    setLoading(true);
    try {
      const data = await apiGet("/api/admin-users/");
      setUsers(data);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function createUser(e) {
    e.preventDefault();
    setErr("");

    try {
      await apiPost("/api/admin-users/", {
        username,
        email,
        password,
        role,
      });

      setUsername("");
      setEmail("");
      setPassword("");
      setRole("tech");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  return (
    <div className="w-100">
      <h2 className="mb-3">User Management</h2>

      {err && <Alert variant="danger">{err}</Alert>}

      <Card className="shadow-sm border-0 mb-4">
        <Card.Body>
          <h5 className="mb-3">Create User</h5>

          <Form onSubmit={createUser}>
            <Row className="g-2">
              <Col md={3}>
                <Form.Control
                  placeholder="Username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </Col>
              <Col md={3}>
                <Form.Control
                  placeholder="Email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </Col>
              <Col md={3}>
                <Form.Control
                  type="password"
                  placeholder="Password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </Col>
              <Col md={2}>
                <Form.Select
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                >
                  <option value="admin">admin</option>
                  <option value="tech">tech</option>
                  <option value="viewer">viewer</option>
                </Form.Select>
              </Col>
              <Col md={1}>
                <Button
                  type="submit"
                  variant="dark"
                  className="w-100"
                  disabled={!username || !password}
                >
                  Add
                </Button>
              </Col>
            </Row>
          </Form>
        </Card.Body>
      </Card>

      <Card className="shadow-sm border-0">
        <Card.Body>
          <h5 className="mb-3">Existing Users</h5>

          {loading ? (
            <div>Loading...</div>
          ) : users.length === 0 ? (
            <Alert variant="light" className="mb-0">
              No users found.
            </Alert>
          ) : (
            <Table responsive hover className="mb-0">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Username</th>
                  <th>Email</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td>{u.id}</td>
                    <td>{u.username}</td>
                    <td>{u.email || "-"}</td>
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