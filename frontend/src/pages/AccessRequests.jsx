import { useEffect, useRef, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { Alert, Badge, Button, Card, Col, Form, Pagination, Row, Spinner, Table } from "react-bootstrap";
import { apiGet, apiPostResponse } from "../api";
import { isAdmin } from "../authz";
import { useLanguage } from "../i18n";

const PAGE_SIZE = 25;
const VALID_STATUSES = ["PENDING", "APPROVED", "REJECTED", "CANCELLED"];

export default function AccessRequests() {
  const { language, t: translate } = useLanguage();
  const location = useLocation();
  const t = (en, es) => language === "es" ? es : en;
  const [me, setMe] = useState(null), [rows, setRows] = useState([]), [count, setCount] = useState(0);
  const [searchParams, setSearchParams] = useSearchParams();
  const rawStatus = searchParams.get("status");
  const status = rawStatus === "ALL" ? "" : VALID_STATUSES.includes(rawStatus) ? rawStatus : "PENDING";
  const rawPage = searchParams.get("page") || "1";
  const page = /^[1-9]\d{0,5}$/.test(rawPage) ? Number(rawPage) : 1;
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true), [error, setError] = useState("");
  const [success, setSuccess] = useState(() => typeof location.state?.accessRequestNotice === "string" ? location.state.accessRequestNotice : "");
  const [busy, setBusy] = useState(false), [kind, setKind] = useState("PROJECT"), [projectCode, setProjectCode] = useState("");
  const [role, setRole] = useState(""), [reason, setReason] = useState("");
  const [review, setReview] = useState(null), [reviewLoading, setReviewLoading] = useState(false);
  const [reviewReason, setReviewReason] = useState(""), [reviewError, setReviewError] = useState(""), [stale, setStale] = useState(false);
  const previewRequest = useRef(null);
  const admin = isAdmin(me);
  const roles = {
    viewer: t("Read-only user", "Usuario de solo lectura"),
    tech: t("Technician", "Técnico"), qc_reviewer: t("QC reviewer", "Revisor de QC"),
  };
  const statuses = {
    PENDING: t("Pending", "Pendiente"), APPROVED: t("Approved", "Aprobada"),
    REJECTED: t("Rejected", "Rechazada"), CANCELLED: t("Withdrawn", "Retirada"),
  };
  const reload = () => setRefresh(value => value + 1);
  const setPage = value => setSearchParams({ status: status || "ALL", page: String(typeof value === "function" ? value(page) : value) });
  const setStatus = (value, notice = "") => setSearchParams({ status: value || "ALL", page: "1" }, { state: notice ? { accessRequestNotice: notice } : null });

  useEffect(() => () => previewRequest.current?.abort(), []);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      setLoading(true); setError("");
      const query = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
      if (status) query.set("status", status);
      try {
        const [account, data] = await Promise.all([
          apiGet("/api/me/", { signal: controller.signal }),
          apiGet(`/api/access-requests/?${query}`, { signal: controller.signal }),
        ]);
        if (!controller.signal.aborted) {
          const items = Array.isArray(data) ? data : data.results || [];
          if (!items.length && page > 1 && data.count > 0) { setSearchParams({ status: status || "ALL", page: "1" }); return; }
          setMe(account); setRows(items); setCount(data.count ?? items.length);
          if (!isAdmin(account)) setReview(null);
        }
      } catch (failure) {
        if (!controller.signal.aborted && page > 1 && failure.status === 404) { setSearchParams({ status: status || "ALL", page: "1" }); return; }
        if (!controller.signal.aborted) setError(language === "es" ? "No se pudieron cargar las solicitudes. Inténtalo de nuevo." : "Could not load access requests. Try again.");
      } finally { if (!controller.signal.aborted) setLoading(false); }
    }, 0);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [page, status, refresh, language, setSearchParams]);

  async function send(event) {
    event.preventDefault(); setError(""); setSuccess("");
    if (reason.trim().length < 10) { setError(t("Give a reason with at least 10 characters.", "Indica un motivo de al menos 10 caracteres.")); return; }
    setBusy(true);
    try {
      const response = await apiPostResponse("/api/access-requests/", {
        kind, project_code: kind === "PROJECT" ? projectCode.trim() : "", role: kind === "ROLE" ? role : "", reason: reason.trim(),
      });
      if (!response.ok) {
        setError(response.status === 429 ? t("Too many submissions. Wait before trying again.", "Demasiadas solicitudes. Espera antes de intentarlo de nuevo.")
          : t("Could not submit the request. Check the fields and whether access is already assigned.", "No se pudo enviar la solicitud. Revisa los campos y si ya tienes ese acceso."));
        return;
      }
      const notice = response.status === 200
        ? t("You already have a pending request for this access. Its original reason is unchanged.", "Ya tienes una solicitud pendiente para este acceso. Su motivo original se conserva.")
        : t("Request submitted for administrator review. Access has not been granted yet.", "Solicitud enviada para revisión administrativa. El acceso todavía no se ha concedido.");
      setSuccess(notice);
      setProjectCode(""); setRole(""); setReason(""); setStatus("PENDING", notice); reload();
    } catch { setError(t("Could not confirm submission. Refresh the list before trying again.", "No se pudo confirmar el envío. Actualiza la lista antes de intentarlo de nuevo.")); }
    finally { setBusy(false); }
  }

  async function openReview(id, keepReason = false) {
    previewRequest.current?.abort();
    const controller = new AbortController();
    previewRequest.current = controller;
    setReviewLoading(true); setReviewError(""); setStale(false);
    if (!keepReason) { setReview(null); setReviewReason(""); }
    try {
      const data = await apiGet(`/api/access-requests/${id}/preview/`, { signal: controller.signal });
      if (!controller.signal.aborted) setReview(data);
    } catch { if (!controller.signal.aborted) { setReview(null); setReviewError(t("The preview is unavailable. Refresh the queue and check your administrator access.", "La vista previa no está disponible. Actualiza la cola y comprueba tu acceso administrativo.")); } }
    finally { if (!controller.signal.aborted) setReviewLoading(false); }
  }

  async function decide(decision) {
    if (!review || reviewReason.trim().length < 10) {
      setReviewError(t("Give a decision reason with at least 10 characters.", "Indica un motivo de decisión de al menos 10 caracteres.")); return;
    }
    setBusy(true); setReviewError(""); setSuccess("");
    try {
      const response = await apiPostResponse(`/api/access-requests/${review.request.id}/review/`, {
        decision, decision_reason: reviewReason.trim(),
        ...(decision === "APPROVED" && review.project ? { project_public_id: review.project.public_id } : {}),
      });
      if (!response.ok) {
        setStale(true);
        setReviewError(response.status === 409
          ? t("The request or project changed. Refresh the preview before deciding.", "La solicitud o el proyecto cambiaron. Actualiza la vista previa antes de decidir.")
          : t("The decision was not accepted. Refresh the preview and check current access and account status.", "La decisión no fue aceptada. Actualiza la vista previa y comprueba los permisos y el estado de la cuenta."));
        return;
      }
      setSuccess(decision === "APPROVED" ? t("Access request approved.", "Solicitud de acceso aprobada.") : t("Access request rejected.", "Solicitud de acceso rechazada."));
      setReview(null); setReviewReason(""); reload();
    } catch { setStale(true); setReviewError(t("Could not confirm the decision. Refresh the preview before retrying.", "No se pudo confirmar la decisión. Actualiza la vista previa antes de reintentarlo.")); }
    finally { setBusy(false); }
  }

  async function withdraw(id) {
    setBusy(true); setError(""); setSuccess("");
    try {
      const response = await apiPostResponse(`/api/access-requests/${id}/withdraw/`, {});
      if (!response.ok) { setError(t("The request could not be withdrawn. Refresh its status.", "No se pudo retirar la solicitud. Actualiza su estado.")); return; }
      setSuccess(t("Request withdrawn.", "Solicitud retirada.")); reload();
    } catch { setError(t("Could not confirm withdrawal. Refresh the list.", "No se pudo confirmar la retirada. Actualiza la lista.")); }
    finally { setBusy(false); }
  }

  return <div>
    <div className="page-header d-flex justify-content-between gap-3 flex-wrap">
      <div><h1 className="page-title">{t("Access requests", "Solicitudes de acceso")}</h1>
        <p className="text-muted">{admin ? t("Review requested access before granting it.", "Revisa el acceso solicitado antes de concederlo.") : t("Ask an administrator for project membership or an application role.", "Solicita a un administrador acceso a un proyecto o un rol de la aplicación.")}</p></div>
      <div className="d-flex gap-2 align-items-start"><Button variant="outline-secondary" onClick={reload} disabled={loading || busy}>{t("Refresh", "Actualizar")}</Button>
        {!admin && <Button variant="outline-primary" onClick={() => window.location.reload()} disabled={busy}>{t("Reload account access", "Recargar acceso de la cuenta")}</Button>}</div>
    </div>
    {error && <Alert variant="danger">{error}</Alert>}{success && <Alert variant="success" role="status">{success}</Alert>}
    {me && !admin && <Card className="app-card mb-4"><Card.Body>
      <h2 className="h5">{t("Request additional access", "Solicitar acceso adicional")}</h2>
      <p className="small text-muted">{t("A request grants no access until an administrator approves it. Project membership and application roles are reviewed separately. Administrator access cannot be requested here.", "Una solicitud no concede acceso hasta su aprobación. La membresía de proyectos y los roles se revisan por separado. El acceso administrativo no se solicita aquí.")}</p>
      <Form onSubmit={send}><fieldset disabled={busy}><Row className="g-3">
        <Col md={4}><Form.Group controlId="access-kind"><Form.Label>{t("Request type", "Tipo de solicitud")}</Form.Label><Form.Select value={kind} onChange={event => setKind(event.target.value)}><option value="PROJECT">{t("Project membership", "Membresía de proyecto")}</option><option value="ROLE">{t("Application role", "Rol de la aplicación")}</option></Form.Select></Form.Group></Col>
        <Col md={8}>{kind === "PROJECT" ? <Form.Group controlId="access-project"><Form.Label>{t("Project code", "Código del proyecto")}</Form.Label><Form.Control required maxLength={64} placeholder="ALPHA" value={projectCode} onChange={event => setProjectCode(event.target.value)} /><Form.Text>{t("Use the exact code provided by your laboratory. Private project names and directories are not listed.", "Usa el código facilitado por tu laboratorio. No se muestran nombres ni directorios de proyectos privados.")}</Form.Text></Form.Group>
          : <Form.Group controlId="access-role"><Form.Label>{t("Requested role", "Rol solicitado")}</Form.Label><Form.Select required value={role} onChange={event => setRole(event.target.value)}><option value="">{t("Choose a role", "Elige un rol")}</option>{Object.entries(roles).map(([key, label]) => <option key={key} value={key} disabled={me.roles?.includes(key)}>{label}</option>)}</Form.Select><Form.Text>{t("Approved roles are added to existing roles. QC and project restrictions still apply.", "Los roles aprobados se añaden a los existentes. Se mantienen las restricciones de QC y proyectos.")}</Form.Text></Form.Group>}</Col>
        <Col xs={12}><Form.Group controlId="access-reason"><Form.Label>{t("Reason (at least 10 characters)", "Motivo (mínimo 10 caracteres)")}</Form.Label><Form.Control as="textarea" rows={2} required minLength={10} maxLength={2000} value={reason} onChange={event => setReason(event.target.value)} /></Form.Group></Col>
      </Row><Button type="submit" className="mt-3">{t("Submit request", "Enviar solicitud")}</Button></fieldset></Form>
    </Card.Body></Card>}
    {reviewError && <Alert variant="danger">{reviewError}</Alert>}
    {reviewLoading && <p role="status"><Spinner size="sm" className="me-2" />{t("Loading review preview...", "Cargando vista previa...")}</p>}
    {review && admin && <Card className="border-primary mb-4"><Card.Body>
      <h2 className="h5">{t("Review access request", "Revisar solicitud de acceso")}</h2>
      <p><strong>{t("Requester", "Solicitante")}:</strong> <span translate="no">{review.request.requester_username}</span></p>
      <p><strong>{t("Current roles", "Roles actuales")}:</strong> <span translate="no">{review.current_roles.join(", ") || "—"}</span></p>
      <p><strong>{t("Requested access", "Acceso solicitado")}:</strong> {review.project ? <span translate="no">{review.project.code} — {review.project.name}</span> : roles[review.request.role] || <span translate="no">{review.request.project_code}</span>}</p>
      <p style={{ whiteSpace: "pre-wrap" }} translate="no">{review.request.reason}</p>
      {review.already_granted && <Alert variant="info">{t("This access is already assigned. Approval will record the decision without adding it again.", "Este acceso ya está asignado. La aprobación registra la decisión sin volver a añadirlo.")}</Alert>}
      {review.blockers.map(blocker => <Alert variant="warning" key={blocker}>{translate(blocker)}</Alert>)}
      <Form onSubmit={event => { event.preventDefault(); void decide("APPROVED"); }}><fieldset disabled={busy || reviewLoading}>
        <Form.Group controlId="access-decision-reason"><Form.Label>{t("Decision reason (at least 10 characters)", "Motivo de decisión (mínimo 10 caracteres)")}</Form.Label><Form.Control as="textarea" rows={2} required minLength={10} maxLength={2000} value={reviewReason} onChange={event => setReviewReason(event.target.value)} /></Form.Group>
        <div className="d-flex flex-wrap gap-2 mt-3"><Button type="submit" disabled={!review.can_approve || stale || !review.request.can_review}>{t("Approve access", "Aprobar acceso")}</Button>
          <Button variant="outline-danger" disabled={review.request.status !== "PENDING" || stale || !review.request.can_review} onClick={() => decide("REJECTED")}>{t("Reject request", "Rechazar solicitud")}</Button>
          <Button variant="outline-secondary" onClick={() => openReview(review.request.id, true)}>{t("Refresh preview", "Actualizar vista previa")}</Button>
          <Button variant="link" onClick={() => { previewRequest.current?.abort(); setReviewLoading(false); setReview(null); }}>{t("Close review", "Cerrar revisión")}</Button></div>
      </fieldset></Form>
    </Card.Body></Card>}
    <Card className="app-card"><Card.Body>
      <div className="d-flex justify-content-between align-items-center gap-3 mb-3 flex-wrap"><h2 className="h5 mb-0">{admin ? t("Administrator review queue", "Cola de revisión administrativa") : t("My requests", "Mis solicitudes")}</h2>
        <Form.Group controlId="access-status"><Form.Label className="visually-hidden">{t("Filter by status", "Filtrar por estado")}</Form.Label><Form.Select value={status} onChange={event => setStatus(event.target.value)}><option value="">{t("All statuses", "Todos los estados")}</option>{Object.entries(statuses).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</Form.Select></Form.Group></div>
      {loading ? <p role="status"><Spinner size="sm" className="me-2" />{t("Loading requests...", "Cargando solicitudes...")}</p> : rows.length === 0 ? <p>{t("No requests match this status.", "Ninguna solicitud coincide con este estado.")}</p> : <Table responsive className="align-middle"><thead><tr>
        {admin && <th>{t("Requester", "Solicitante")}</th>}<th>{t("Requested access", "Acceso solicitado")}</th><th>{t("Status", "Estado")}</th><th>{t("Reason and decision", "Motivo y decisión")}</th><th>{t("Actions", "Acciones")}</th>
      </tr></thead><tbody>{rows.map(row => <tr key={row.id}>
        {admin && <td translate="no">{row.requester_username}</td>}<td>{row.kind === "PROJECT" ? <span translate="no">{row.project_code}</span> : roles[row.role]}<div className="small text-muted">{new Date(row.created_at).toLocaleString(language === "es" ? "es" : "en")}</div></td>
        <td><Badge bg={{ PENDING: "warning", APPROVED: "success", REJECTED: "danger", CANCELLED: "secondary" }[row.status]} text={row.status === "PENDING" ? "dark" : undefined}>{statuses[row.status]}</Badge></td>
        <td style={{ maxWidth: 400, overflowWrap: "anywhere" }}><details><summary>{t("View details", "Ver detalles")}</summary><p className="mt-2" style={{ whiteSpace: "pre-wrap" }} translate="no">{row.reason}</p>{row.decision_reason && <><p className="mb-1" translate="no">{row.decision_reason}</p><small translate="no">{row.reviewer_username}</small></>}</details></td>
        <td><div className="d-flex flex-wrap gap-2">{row.can_review && <Button size="sm" disabled={busy || reviewLoading || Boolean(error)} onClick={() => openReview(row.id)}>{t("Review request", "Revisar solicitud")}</Button>}{row.can_withdraw && <Button size="sm" variant="outline-secondary" disabled={busy || Boolean(error)} onClick={() => withdraw(row.id)}>{t("Withdraw request", "Retirar solicitud")}</Button>}</div></td>
      </tr>)}</tbody></Table>}
      <div className="d-flex align-items-center justify-content-between gap-3"><span className="small text-muted">{t("Requests", "Solicitudes")}: {count}</span><Pagination className="mb-0"><Pagination.Prev disabled={page === 1 || loading} onClick={() => setPage(value => value - 1)} /><Pagination.Item active>{page}</Pagination.Item><Pagination.Next disabled={page * PAGE_SIZE >= count || loading} onClick={() => setPage(value => value + 1)} /></Pagination></div>
    </Card.Body></Card>
  </div>;
}
