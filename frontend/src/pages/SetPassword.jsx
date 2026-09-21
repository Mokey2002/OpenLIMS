import { useState } from "react";
import { Alert, Button, Card, Form } from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiPost } from "../api";

export default function SetPassword() {
  const [credentials] = useState(() => {
    const params = new URLSearchParams(window.location.hash.slice(1));
    return { uid: params.get("uid") || "", token: params.get("token") || "" };
  });
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  async function submit(event) {
    event.preventDefault();
    setError("");
    if (password !== confirmation) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await apiPost("/api/auth/set-password/", { ...credentials, password });
      window.history.replaceState(null, "", window.location.pathname);
      setPassword("");
      setConfirmation("");
      setDone(true);
    } catch {
      setError("Unable to set password. Use a strong password or request a new link.");
    } finally {
      setBusy(false);
    }
  }
  return <main className="container py-5" style={{ maxWidth: 520 }}>
    <Card><Card.Body>
      <h1 className="h4">Set your OpenLIMS password</h1>
      {done ? <Alert variant="success">Password saved. You can now sign in.</Alert> :
        !credentials.uid || !credentials.token ? <Alert variant="warning">Invalid password link. Request a new link or contact your administrator.</Alert> :
        <Form onSubmit={submit}>
          <p>Choose your own password to access your account.</p>
          {error && <Alert variant="danger">{error}</Alert>}
          <Form.Group className="mb-3" controlId="new-password">
            <Form.Label>New password</Form.Label>
            <Form.Control type="password" autoComplete="new-password" required maxLength={1024} value={password} onChange={e => setPassword(e.target.value)} />
          </Form.Group>
          <Form.Group className="mb-3" controlId="confirm-password">
            <Form.Label>Confirm password</Form.Label>
            <Form.Control type="password" autoComplete="new-password" required maxLength={1024} value={confirmation} onChange={e => setConfirmation(e.target.value)} />
          </Form.Group>
          <Button type="submit" disabled={busy}>{busy ? "Saving..." : "Save password"}</Button>
        </Form>}
      <Link to="/forgot-password" className="d-block mt-3">Request a new password reset link</Link>
      <Link to="/login" className="d-block mt-3">Sign in</Link>
    </Card.Body></Card>
  </main>;
}
