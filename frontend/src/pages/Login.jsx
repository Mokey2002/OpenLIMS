import { useState } from "react";
import { Alert, Button, Card, Form } from "react-bootstrap";
import { useNavigate } from "react-router-dom";
import { login } from "../api";

export default function Login() {
  const navigate = useNavigate();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleLogin(e) {
    e.preventDefault();
    setErr("");
    setLoading(true);

    try {
      await login(username, password);
      navigate("/");
    } catch (e) {
      setErr(e.message || "Login failed");
    } finally {
      setLoading(false);
    }
  }

  function useDemoLogin() {
    setUsername("peter");
    setPassword("peter123");
  }

  return (
    <div
      className="d-flex align-items-center justify-content-center"
      style={{
        minHeight: "100vh",
        background:
          "linear-gradient(135deg, #f8fafc 0%, #eef2f7 45%, #e5e7eb 100%)",
        padding: "24px",
      }}
    >
      <Card
        className="shadow-sm border-0"
        style={{
          width: "100%",
          maxWidth: "440px",
          borderRadius: "18px",
        }}
      >
        <Card.Body className="p-4">
          <div className="mb-4 text-center">
            <div
              className="mx-auto mb-3 d-flex align-items-center justify-content-center"
              style={{
                width: "56px",
                height: "56px",
                borderRadius: "16px",
                background: "#111827",
                color: "white",
                fontWeight: "800",
                fontSize: "22px",
              }}
            >
              OL
            </div>

            <h2 className="mb-1 fw-bold">OpenLIMS</h2>
            <p className="text-muted mb-0">
              Laboratory workflow and sample tracking demo
            </p>
          </div>

          <Alert variant="info" className="mb-4">
            <div className="fw-semibold mb-1">Demo Login</div>
            <div>
              Username: <strong>peter</strong>
            </div>
            <div>
              Password: <strong>peter123</strong>
            </div>

            <Button
              variant="outline-primary"
              size="sm"
              className="mt-3"
              onClick={useDemoLogin}
            >
              Use demo credentials
            </Button>
          </Alert>

          {err && <Alert variant="danger">{err}</Alert>}

          <Form onSubmit={handleLogin}>
            <Form.Group className="mb-3">
              <Form.Label>Username</Form.Label>
              <Form.Control
                autoFocus
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="Enter username"
              />
            </Form.Group>

            <Form.Group className="mb-4">
              <Form.Label>Password</Form.Label>
              <Form.Control
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Enter password"
              />
            </Form.Group>

            <Button
              type="submit"
              variant="dark"
              className="w-100"
              disabled={!username || !password || loading}
            >
              {loading ? "Signing in..." : "Sign in"}
            </Button>
          </Form>

          <div className="text-center text-muted mt-4 small">
            Demo environment for OpenLIMS
          </div>
        </Card.Body>
      </Card>
    </div>
  );
}