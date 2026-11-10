import { useEffect, useRef, useState } from "react";
import { Alert, Button, Form, Modal, Spinner, Table } from "react-bootstrap";
import { apiGet, apiPostResponse } from "../api";
import { useLanguage } from "../i18n";

const categories = {
  samples: "Sample assignments", custody: "Physical sample custody", work_items: "Outstanding work items",
  qc_results: "Pending QC reviews", notebooks: "Notebook ownership", experiments: "Experiment assignments",
  workflow_steps: "Pending notebook steps", comments: "Unresolved notebook tasks",
  registry_records: "Registry ownership", registry_reviews: "Pending registry reviews",
};

function errorMessage(data, fallback) {
  if (data?.blockers?.length) return data.blockers.join(" ");
  if (typeof data?.detail === "string") return data.detail;
  return fallback;
}

function ResponsibilityReview({ snapshot, t }) {
  return <>
    <h6>{t("Responsibilities to transfer")}: {snapshot.total_responsibilities}</h6>
    {snapshot.total_responsibilities === 0 && <p>{t("No outstanding responsibilities were found.")}</p>}
    {Object.entries(snapshot.responsibilities).map(([category, rows]) => <details key={category} className="mb-2">
      <summary>{t(categories[category] || category)} ({rows.length})</summary>
      <Table size="sm" responsive><thead><tr><th>{t("Record")}</th><th>{t("Status")}</th></tr></thead>
        <tbody>{rows.map(row => <tr key={row.id}><td>{row.label}</td><td>{row.status || "—"}</td></tr>)}</tbody>
      </Table>
    </details>)}
    <h6 className="mt-3">{t("Access to remove")}</h6>
    <ul>
      <li>{t("Project memberships")}: {snapshot.projects.length}{snapshot.projects.length > 0 && ` (${snapshot.projects.map(project => project.code).join(", ")})`}</li>
      <li>{t("Notebook access grants")}: {Object.values(snapshot.notebook_grants).reduce((total, rows) => total + rows.length, 0)}</li>
      <li>{t("Application roles and direct permissions")}: {snapshot.user.roles.join(", ") || "—"}</li>
      <li>{t("Pending access requests")}: {snapshot.pending_access_requests.length}</li>
      <li>{t("Unconfirmed assistant actions")}: {snapshot.proposed_actions.length}</li>
      <li>{t("Personal notification subscriptions")}: {snapshot.subscriptions.length}</li>
    </ul>
    <p>{t("The account will be disabled, staff and administrator access removed, and browser, API and Django sessions revoked.")}</p>
    <p>{t("Authorship, completed work, approvals and scientific history keep their original attribution. Ownership transfers grant the replacement access to the listed notebooks and registry records. Other project and notebook permissions must already be in place.")}</p>
    {(snapshot.continuing_jobs.length > 0 || snapshot.open_requests.length > 0 || snapshot.future_bookings.length > 0) && <Alert variant="info">
      <strong>{t("Review continuing activity")}</strong>
      <p>{t("Already queued jobs, submitted requests and instrument bookings are preserved. Offboarding does not stop instrument runs or cancel these records. Review their existing controls if cancellation is needed.")}</p>
      <ul>
        {snapshot.continuing_jobs.map(row => <li key={`job-${row.id}`}>{row.summary}</li>)}
        {snapshot.open_requests.map(row => <li key={`request-${row.id}`}>{row.request_number}: {row.title}</li>)}
        {snapshot.future_bookings.map(row => <li key={`booking-${row.id}`}>{t("Instrument booking")}: {new Date(row.starts_at).toLocaleString()} – {new Date(row.ends_at).toLocaleString()}</li>)}
      </ul>
    </Alert>}
  </>;
}

export default function UserOffboarding({ user, onClose }) {
  const { t } = useLanguage();
  const [review, setReview] = useState(null);
  const [preview, setPreview] = useState(null);
  const [receipt, setReceipt] = useState(null);
  const [successor, setSuccessor] = useState("");
  const [reason, setReason] = useState("");
  const [custodyConfirmed, setCustodyConfirmed] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [forbidden, setForbidden] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const inFlight = useRef(false);
  const base = `/api/admin-users/${user.id}/offboarding`;

  useEffect(() => {
    const controller = new AbortController();
    apiGet(`${base}/`, { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) { setReview(data); setLoading(false); }
    }).catch(() => {
      if (!controller.signal.aborted) { setError("Could not load the offboarding review. Close and try again."); setLoading(false); }
    });
    return () => controller.abort();
  }, [base]);

  async function prepare(event) {
    event.preventDefault();
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError("");
    try {
      const response = await apiPostResponse(`${base}/preview/`, {
        successor_id: successor ? Number(successor) : null, reason: reason.trim(), custody_confirmed: custodyConfirmed,
      });
      const data = await response.json().catch(() => null);
      if (!response.ok) {
        if (response.status === 403) setForbidden(true);
        setError(errorMessage(data, "The preview was not accepted. Check the replacement, reason and administrator access."));
        return;
      }
      setPreview(data); setConfirmed(false); setUncertain(false);
    } catch {
      setError("Could not prepare the preview. No offboarding changes were requested; try again.");
    } finally { inFlight.current = false; setBusy(false); }
  }

  async function complete() {
    if (!preview || !confirmed || inFlight.current) return;
    inFlight.current = true; setBusy(true); setError("");
    try {
      const response = await apiPostResponse(`${base}/confirm/`, { preview_id: preview.preview_id, confirmed: true });
      const data = await response.json().catch(() => null);
      if (response.status >= 500 || (response.ok && !data?.offboarding_id)) throw new Error("Uncertain offboarding response");
      if (!response.ok) {
        if (response.status === 403) setForbidden(true);
        if (response.status === 409) {
          setPreview(null); setConfirmed(false); setUncertain(false);
          setReview(await apiGet(`${base}/`));
        }
        setError(errorMessage(data, "Offboarding could not be confirmed. Retry the same confirmation to check its receipt."));
        return;
      }
      setReceipt(data); setUncertain(false);
    } catch {
      setUncertain(true);
      setError("The completion response was lost. Retry the same confirmation to retrieve its receipt; the handover will not run twice.");
    } finally { inFlight.current = false; setBusy(false); }
  }

  const snapshot = preview?.snapshot || review?.snapshot;
  const needsReplacement = Boolean(snapshot?.total_responsibilities);
  const custodyCount = snapshot?.counts?.custody || 0;
  const blocked = forbidden || Boolean(review?.blockers?.length);

  return <Modal show onHide={() => onClose(Boolean(receipt))} size="lg" backdrop="static" keyboard={!busy} aria-labelledby="offboarding-title">
    <Modal.Header closeButton={!busy}><Modal.Title id="offboarding-title">{t("Coordinated offboarding")}: {user.username}</Modal.Title></Modal.Header>
    <Modal.Body>
      {loading && <div role="status"><Spinner size="sm" animation="border" /> {t("Loading offboarding review...")}</div>}
      {error && <Alert variant="danger" role="alert">{t(error)}</Alert>}
      {review?.blockers?.map(message => <Alert key={message} variant="warning">{t(message)}</Alert>)}
      {receipt ? <div role="status">
        <h5>{t("Offboarding completed")}: {receipt.user}</h5>
        <p>{t("Responsibilities transferred")}: {receipt.total_transferred} · {t("Replacement")}: {receipt.successor || "—"}</p>
        <p>{t("Project memberships removed")}: {receipt.projects_removed} · {t("Notebook access grants removed")}: {receipt.notebook_grants_removed}</p>
        <p>{t("Sessions revoked. Reactivating this account will require a fresh sign-in and new access grants.")}</p>
        <p>{t("The handover and access removal are recorded in Audit Events.")}</p>
      </div> : snapshot && <>
        <ResponsibilityReview snapshot={snapshot} t={t} />
        {review.latest_receipt && !preview && <details className="mb-3">
          <summary>{t("A previous offboarding receipt is available.")} {new Date(review.latest_receipt.completed_at).toLocaleString()}</summary>
          <p>{t("Responsibilities transferred")}: {review.latest_receipt.total_transferred} · {t("Replacement")}: {review.latest_receipt.successor || "—"}</p>
          <p>{t("Reason")}: {review.latest_receipt.reason}</p>
        </details>}
        {!preview ? <Form id="offboarding-form" onSubmit={prepare}>
          <Form.Group controlId="offboarding-successor" className="mb-3">
            <Form.Label>{t("Replacement")}</Form.Label>
            <Form.Select value={successor} onChange={event => setSuccessor(event.target.value)} required={needsReplacement} disabled={busy || blocked}>
              <option value="">{t("Choose an active replacement")}</option>
              {review.successors.map(row => <option key={row.id} value={row.id}>{row.username} ({row.roles.join(", ")})</option>)}
            </Form.Select>
            <Form.Text>{t("The replacement must already have the required project access and work or QC role. No application roles are copied.")}</Form.Text>
          </Form.Group>
          <Form.Group controlId="offboarding-reason" className="mb-3">
            <Form.Label>{t("Offboarding reason (at least 10 characters)")}</Form.Label>
            <Form.Control as="textarea" rows={2} minLength={10} maxLength={2000} required value={reason} onChange={event => setReason(event.target.value)} disabled={busy || blocked} />
          </Form.Group>
          {custodyCount > 0 && <Form.Check id="offboarding-custody" className="mb-3" required checked={custodyConfirmed} disabled={busy || blocked}
            onChange={event => setCustodyConfirmed(event.target.checked)} label={t("I verified the physical sample handoff to the replacement.")} />}
        </Form> : <>
          <h6>{t("Review and confirm")}</h6>
          <p>{t("Replacement")}: <strong>{preview.successor?.username || "—"}</strong></p>
          <p>{t("Reason")}: {preview.reason}</p>
          <p>{t("Preview expires")}: {new Date(preview.expires_at).toLocaleString()}</p>
          <Form.Check id="offboarding-confirmed" checked={confirmed} disabled={busy || forbidden} onChange={event => setConfirmed(event.target.checked)}
            label={t("I reviewed the responsibility transfers and access removal.")} />
        </>}
      </>}
    </Modal.Body>
    <Modal.Footer>
      <Button variant="outline-secondary" disabled={busy} onClick={() => onClose(Boolean(receipt))}>{t(receipt ? "Done" : "Close")}</Button>
      {!receipt && preview && <Button variant="outline-secondary" disabled={busy || uncertain} onClick={() => { setPreview(null); setConfirmed(false); setError(""); }}>{t("Edit handover")}</Button>}
      {!receipt && snapshot && (!preview
        ? <Button type="submit" form="offboarding-form" disabled={busy || blocked || reason.trim().length < 10 || (needsReplacement && !successor) || (custodyCount > 0 && !custodyConfirmed)}>{t(busy ? "Preparing..." : "Preview offboarding")}</Button>
        : <Button variant="danger" disabled={busy || forbidden || !confirmed} onClick={complete}>{t(busy ? "Completing..." : uncertain ? "Retry confirmation" : "Confirm offboarding")}</Button>)}
    </Modal.Footer>
  </Modal>;
}
