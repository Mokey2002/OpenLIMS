import { useState } from "react";
import { Alert, Badge, Button, Card, Col, Form, Row } from "react-bootstrap";
import { useNavigate } from "react-router-dom";
import { login } from "../api";

const demoAccounts = [
  {
    label: "Admin",
    username: "admin",
    password: "Admin123456!",
    badge: "Full Access",
    variant: "dark",
    description:
      "Full demo access. Can manage users, project teams, imports, samples, sequences, and admin workflows.",
  },
  {
    label: "Tech",
    username: "peter",
    password: "peter123",
    badge: "Lab Workflow",
    variant: "outline-dark",
    description:
      "Lab user access. Can run imports, update samples, add results, upload attachments, and manage sequence workspaces.",
  },
  {
    label: "Viewer",
    username: "viewer",
    password: "viewer123",
    badge: "Read Only",
    variant: "outline-secondary",
    description:
      "Read-only demo access. Can view dashboards, samples, projects, events, analysis, and sequences but cannot make changes.",
  },
];

export default function Login() {
  const nav = useNavigate();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);
  const [demoLoading, setDemoLoading] = useState("");

  async function submit(e) {
    e.preventDefault();

    setErr("");
    setLoading(true);

    try {
      await login(username, password);
      nav("/");
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  async function loginAsDemo(account) {
    setErr("");
    setDemoLoading(account.label);

    try {
      await login(account.username, account.password);
      nav("/");
    } catch (e) {
      setErr(
        `Demo login failed for ${account.label}. Make sure seed_demo has been run.`
      );
    } finally {
      setDemoLoading("");
    }
  }

  return (
    <div
      className="d-flex align-items-center justify-content-center"
      style={{
        minHeight: "100vh",
        background:
          "linear-gradient(135deg, #f8fafc 0%, #eef2ff 45%, #f8fafc 100%)",
      }}
    >
      <div className="w-100 px-3" style={{ maxWidth: "1020px" }}>
        <div className="text-center mb-4">
          <div
            className="mx-auto mb-3 d-flex align-items-center justify-content-center"
            style={{
              width: "64px",
              height: "64px",
              borderRadius: "18px",
              background: "#111827",
              color: "#ffffff",
              fontWeight: "800",
              fontSize: "1.4rem",
              boxShadow: "0 18px 35px rgba(15, 23, 42, 0.18)",
            }}
          >
            OL
          </div>

          <h1 className="fw-bold mb-2">OpenLIMS</h1>

          <p className="text-muted mb-0">
            Demo login for lab users, viewers, and administrators.
          </p>
        </div>

        {err && <Alert variant="danger">{err}</Alert>}

        <Row className="g-4 align-items-stretch">
          <Col lg={5}>
            <Card className="app-card border-0 shadow-sm h-100">
              <Card.Body className="p-4">
                <h4 className="mb-2">Sign in</h4>

                <p className="text-muted">
                  Use your OpenLIMS account or try one of the demo roles.
                </p>

                <Form onSubmit={submit}>
                  <Form.Group className="mb-3">
                    <Form.Label>Username</Form.Label>
                    <Form.Control
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      placeholder="Enter username"
                      autoComplete="username"
                    />
                  </Form.Group>

                  <Form.Group className="mb-4">
                    <Form.Label>Password</Form.Label>
                    <Form.Control
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="Enter password"
                      autoComplete="current-password"
                    />
                  </Form.Group>

                  <Button
                    type="submit"
                    variant="dark"
                    className="w-100"
                    disabled={loading || !username || !password}
                  >
                    {loading ? "Signing in..." : "Sign in"}
                  </Button>
                </Form>

                <Alert variant="light" className="border mt-4 mb-0">
                  <div className="fw-semibold mb-1">Demo recommendation</div>
                  <div className="small text-muted">
                    Start as Viewer to see read-only access, then try Tech or
                    Admin to compare permissions.
                  </div>
                </Alert>
              </Card.Body>
            </Card>
          </Col>

          <Col lg={7}>
            <Card className="app-card border-0 shadow-sm h-100">
              <Card.Body className="p-4">
                <div className="mb-3">
                  <h4 className="mb-1">Demo Accounts</h4>
                  <p className="text-muted mb-0">
                    Choose a role to see how permissions change across the app.
                  </p>
                </div>

                <div className="d-grid gap-3">
                  {demoAccounts.map((account) => (
                    <div key={account.label} className="soft-card">
                      <div className="d-flex justify-content-between align-items-start gap-3 flex-wrap">
                        <div style={{ maxWidth: "440px" }}>
                          <div className="d-flex align-items-center gap-2 mb-1">
                            <strong>{account.label}</strong>
                            <Badge bg="light" text="dark">
                              {account.badge}
                            </Badge>
                          </div>

                          <div className="text-muted small mb-2">
                            {account.description}
                          </div>

                          <div className="small">
                            <code>{account.username}</code>
                            <span className="text-muted"> / </span>
                            <code>{account.password}</code>
                          </div>
                        </div>

                        <Button
                          variant={account.variant}
                          size="sm"
                          onClick={() => loginAsDemo(account)}
                          disabled={Boolean(demoLoading)}
                        >
                          {demoLoading === account.label
                            ? "Signing in..."
                            : `Login as ${account.label}`}
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>

                <Alert variant="info" className="mt-4 mb-0">
                  <strong>Role differences:</strong> Viewer is read-only, Tech
                  can perform lab workflows, and Admin can manage users and
                  project teams.
                </Alert>
              </Card.Body>
            </Card>
          </Col>
        </Row>
      </div>
    </div>
  );
}