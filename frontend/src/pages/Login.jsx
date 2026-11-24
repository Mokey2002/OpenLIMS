import { useRef, useState } from "react";
import { Alert, Badge, Button, Card, Col, Form, Row } from "react-bootstrap";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { login } from "../api";
import { isRequesterOnly } from "../authz";
import { OPENLIMS_VERSION } from "../version";

const demoRequesterUsername = "demo-requester";

const demoAccounts = [
  {
    label: "Director",
    username: "director",
    password: "Director123!",
    badge: "Admin Access",
    variant: "dark",
    description:
      "Lab director access. Can manage users, project teams, admin settings, imports, samples, sequences, alignments, and audit workflows.",
  },
  {
    label: "Tech Peter",
    username: "peter",
    password: "peter123",
    badge: "Lab Tech",
    variant: "outline-dark",
    description:
      "Lab workflow access. Can run imports, update samples, add results, upload attachments, and manage sequence workspaces.",
  },
  {
    label: "Tech Maria",
    username: "maria",
    password: "maria123",
    badge: "Lab Tech",
    variant: "outline-dark",
    description:
      "Lab workflow access focused on sequencing QC, FASTA imports, sequence workspaces, and alignment review.",
  },
  {
    label: "Tech Michael",
    username: "michael",
    password: "michael123",
    badge: "Lab Tech",
    variant: "outline-dark",
    description:
      "Lab workflow access focused on endotoxin review, instrument results, sample QC, and project updates.",
  },
  {
    label: "Viewer",
    username: "viewer",
    password: "viewer123",
    badge: "Read Only",
    variant: "outline-secondary",
    description:
      "Read-only demo access. Can view dashboards, samples, projects, events, analysis, sequences, and alignments but cannot make changes.",
  },
];

function SignInCard({ id, title, hint, buttonLabel, recoveryLabel, pending, submitting, error, onSignIn, initialUsername = "" }) {
  const [username, setUsername] = useState(initialUsername);
  const [password, setPassword] = useState("");

  function submit(event) {
    event.preventDefault();
    if (username && password) onSignIn({ username, password });
  }

  return (
    <Card className="app-card border-0 shadow-sm">
      <Card.Body className="p-4">
        <h2 id={`${id}-title`} className="h4 mb-2">{title}</h2>
        <p className="text-muted">{hint}</p>
        <Form aria-labelledby={`${id}-title`} aria-busy={submitting} onSubmit={submit}>
          {error && <Alert variant="danger" role="alert">{error}</Alert>}
          <Form.Group className="mb-3" controlId={`${id}-username`}>
            <Form.Label>Username</Form.Label>
            <Form.Control name="username" autoComplete="username" required
              value={username} onChange={event => setUsername(event.target.value)} />
          </Form.Group>
          <Form.Group className="mb-3" controlId={`${id}-password`}>
            <Form.Label>Password</Form.Label>
            <Form.Control type="password" name="password" autoComplete="current-password" required
              value={password} onChange={event => setPassword(event.target.value)} />
          </Form.Group>
          <Button type="submit" variant="dark" className="w-100" disabled={pending || !username || !password}>
            {submitting ? "Signing in..." : buttonLabel}
          </Button>
        </Form>
        <Link to="/forgot-password" className="d-block mt-3">{recoveryLabel}</Link>
      </Card.Body>
    </Card>
  );
}

export default function Login() {
  const nav = useNavigate();
  const { state } = useLocation();
  const [search] = useSearchParams();
  const returnTo = search.get("return_to") || "";
  const portalReturn = /^\/requester(?:\/[a-f0-9-]{36})?\/?$/.test(returnTo) ? returnTo : "";
  const useDemoRequester = portalReturn === "/requester" && search.get("demo") === "requester";
  const sessionCheckStatus = state?.sessionCheckStatus;

  const signingIn = useRef(false);
  const [pending, setPending] = useState(null);
  const [error, setError] = useState(null);

  async function signIn({ section, username, password, destination, demoLabel }) {
    if (signingIn.current) return;
    signingIn.current = true;
    setPending(demoLabel ?? section);
    setError(null);

    try {
      const session = await login(username, password);
      nav(destination ?? (isRequesterOnly(session?.user) ? "/requester" : "/"), { replace: true });
    } catch (failure) {
      setError({
        section,
        message: demoLabel
          ? `Demo login failed for ${demoLabel}. Make sure seed_demo has been run.`
          : failure.message || String(failure),
      });
    } finally {
      signingIn.current = false;
      setPending(null);
    }
  }

  return (
    <div
      className="min-vh-100 d-flex flex-column"
      style={{ background: "linear-gradient(135deg, #f8fafc 0%, #eef2ff 45%, #f8fafc 100%)" }}
    >
      <main className="w-100 px-3 py-4 mx-auto my-auto" style={{ maxWidth: "1120px" }}>
        <div className="text-center mb-4">
          <div
            aria-hidden="true"
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
          {!portalReturn && <Link className="btn btn-outline-dark btn-sm mt-2"
            to="/login?return_to=%2Frequester" state={state}>
            Requester sign-in
          </Link>}
        </div>

        {typeof sessionCheckStatus === "number" && <Alert variant="warning" role="alert">
          {sessionCheckStatus === 400
            ? "The server rejected the sign-in check (HTTP 400). Check the OpenLIMS address or contact your lab."
            : "OpenLIMS could not verify your sign-in. Try signing in again."}
        </Alert>}

        <Row className="g-4 justify-content-center">
          <Col lg={5} className="d-flex flex-column gap-4">
            {!portalReturn && <SignInCard
              id="openlims"
              title="Lab sign-in"
              hint="Use your OpenLIMS account or try one of the demo roles."
              buttonLabel="Sign in"
              recoveryLabel="Forgot password?"
              pending={pending !== null}
              submitting={pending === "lab"}
              error={error?.section === "lab" ? error.message : null}
              onSignIn={credentials => signIn({ section: "lab", ...credentials })}
            />}
            <SignInCard
              key={useDemoRequester ? demoRequesterUsername : "requester"}
              id="openlims-requester"
              title="Requester sign-in"
              hint={useDemoRequester
                ? "Enter the password set for this demo account."
                : "Use the account provided by your lab to submit and track test requests."}
              buttonLabel="Continue to requester portal"
              recoveryLabel="Reset requester password"
              initialUsername={useDemoRequester ? demoRequesterUsername : ""}
              pending={pending !== null}
              submitting={pending === "requester"}
              error={error?.section === "requester" ? error.message : null}
              onSignIn={credentials => signIn({
                section: "requester", ...credentials, destination: portalReturn || "/requester",
              })}
            />
            {portalReturn && <Link className="text-center" to="/login">All sign-in options</Link>}
          </Col>

          {!portalReturn && <Col lg={7}>
            <Card className="app-card border-0 shadow-sm">
              <Card.Body className="p-4">
                <div className="mb-3">
                  <h2 className="h4 mb-1">Demo Accounts</h2>
                  <p className="text-muted mb-0">
                    Start with Director for the full demo, then compare with Tech
                    and Viewer permissions.
                  </p>
                </div>

                {error?.section === "demo" && <Alert variant="danger" role="alert">{error.message}</Alert>}
                <div className="d-grid gap-3">
                  {demoAccounts.map((account) => (
                    <div key={account.label} className="soft-card">
                      <div className="d-flex justify-content-between align-items-start gap-3 flex-wrap">
                        <div style={{ maxWidth: "520px" }}>
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
                          onClick={() => signIn({
                            section: "demo", username: account.username, password: account.password, demoLabel: account.label,
                          })}
                          disabled={pending !== null}
                        >
                          {pending === account.label
                            ? "Signing in..."
                            : `Login as ${account.label}`}
                        </Button>
                      </div>
                    </div>
                  ))}
                  <div className="soft-card">
                    <div className="d-flex justify-content-between align-items-start gap-3 flex-wrap">
                      <div>
                        <div className="d-flex align-items-center gap-2 mb-1">
                          <strong>Requester demo</strong>
                          <Badge bg="light" text="dark">Requester portal</Badge>
                        </div>
                        <div className="text-muted small mb-2">
                          Try example test requests, printable labels, and a released report.
                        </div>
                        <code className="small">{demoRequesterUsername}</code>
                      </div>
                      <Link to="/login?return_to=%2Frequester&demo=requester"
                        className="btn btn-outline-secondary btn-sm">
                        Open requester demo
                      </Link>
                    </div>
                  </div>
                </div>

                <Alert variant="info" className="mt-4 mb-0">
                  <strong>Role differences:</strong> Viewer is read-only, Lab
                  Techs can perform lab workflows, and Director can manage users,
                  settings, and admin workflows.
                </Alert>
              </Card.Body>
            </Card>
          </Col>}
        </Row>
      </main>
      <footer className="app-footer-version">OpenLIMS {OPENLIMS_VERSION}</footer>
    </div>
  );
}
