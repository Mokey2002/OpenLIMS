import { useState } from "react";
import { Alert, Button, Card, Form } from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiPost } from "../api";

export default function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await apiPost("/api/auth/forgot-password/", { email: email.trim() });
      setDone(true);
    } catch {
      setError("Unable to request a reset link. Please wait and try again, or contact your administrator.");
    } finally { setBusy(false); }
  }
  return <main className="container py-5" style={{ maxWidth: 520 }}>
    <Card><Card.Body>
      <h1 className="h4">Reset your password</h1>
      {done ? <Alert variant="success" role="status">If an eligible account exists, you will receive a password reset email. Check your inbox and spam folder.</Alert> :
        <Form onSubmit={submit}>
          <p>Enter the email address associated with your OpenLIMS account.</p>
          {error && <Alert variant="danger">{error}</Alert>}
          <Form.Group className="mb-3" controlId="recovery-email">
            <Form.Label>Email address</Form.Label>
            <Form.Control type="email" autoComplete="email" required maxLength={254} value={email} onChange={event => setEmail(event.target.value)} />
          </Form.Group>
          <Button type="submit" disabled={busy}>{busy ? "Sending..." : "Send reset link"}</Button>
        </Form>}
      <Link to="/login" className="d-block mt-3">Sign in</Link>
    </Card.Body></Card>
  </main>;
}
