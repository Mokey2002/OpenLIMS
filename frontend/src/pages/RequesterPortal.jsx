import { useEffect, useState } from "react";
import { Alert, Badge, Button, Card, Col, Container, Row } from "react-bootstrap";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { apiDownload, apiGet, logout } from "../api";
import { isRequesterOnly } from "../authz";
import RequesterSubmissionForm from "../components/RequesterSubmissionForm";
import { useLanguage } from "../i18n";
import { OPENLIMS_VERSION } from "../version";

const requestPath = "/api/v1/requester-requests/";
const statusDisplay = {
  SUBMITTED: ["Submitted", "info"],
  TRIAGE: ["In review", "warning"],
  APPROVED: ["Approved", "primary"],
  IN_PROGRESS: ["In progress", "primary"],
  COMPLETED: ["Completed", "success"],
  REJECTED: ["Rejected", "danger"],
  CANCELLED: ["Cancelled", "secondary"],
};

function usePortalData(path) {
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    apiGet(path, { signal: controller.signal }).then(
      data => { if (!controller.signal.aborted) setResult({ path, revision, data }); },
      failure => { if (!controller.signal.aborted) setResult({ path, revision, error: failure.message }); },
    );
    return () => controller.abort();
  }, [path, revision]);

  const current = result?.path === path && result.revision === revision ? result : null;
  return {
    data: current?.data,
    error: current?.error,
    loading: !current,
    refresh: () => setRevision(current => current + 1),
  };
}

function StatusBadge({ status }) {
  const { t } = useLanguage();
  const [label, variant] = statusDisplay[status] || [status, "secondary"];
  return <Badge pill bg={variant} text={["info", "warning"].includes(variant) ? "dark" : undefined}>{t(label)}</Badge>;
}

function PortalLoadState({ resource }) {
  const { t } = useLanguage();
  if (resource.loading) return <p role="status" className="text-muted mb-0">{t("Loading…")}</p>;
  return <Alert variant="danger" role="alert" className="mb-0">
    {resource.error}{" "}<Button size="sm" variant="link" onClick={resource.refresh}>{t("Try again")}</Button>
  </Alert>;
}

function formatDate(date, locale) {
  return date ? new Date(date).toLocaleDateString(locale, { dateStyle: "medium" }) : "—";
}

function RequestList() {
  const [page, setPage] = useState(1);
  const requests = usePortalData(`${requestPath}?page=${page}`);
  const { t, locale } = useLanguage();

  return <Card className="app-card h-100"><Card.Body className="p-4">
    <div className="toolbar-row mb-3">
      <h2 className="h5 mb-0">{t("My test requests")}</h2>
      <Button variant="outline-secondary" size="sm" disabled={requests.loading} onClick={requests.refresh}>{t("Refresh")}</Button>
    </div>
    {!requests.data ? <PortalLoadState resource={requests} /> : <>
      {requests.data.results.length ? <ul className="list-unstyled mb-0">
        {requests.data.results.map(row => <li key={row.public_id} className="border-top py-3">
          <div className="d-flex justify-content-between align-items-start gap-2">
            <div className="text-break">
              <Link className="fw-semibold" to={`/requester/${row.public_id}`}>{row.title}</Link>
              <div className="small text-muted">{row.request_number} · {row.test_name}</div>
              <div className="small text-muted">{row.project_name} · {formatDate(row.submitted_at, locale)}</div>
            </div>
            <StatusBadge status={row.status} />
          </div>
        </li>)}
      </ul> : <p className="text-muted mb-0">{t("Your submitted requests will appear here.")}</p>}
      {(requests.data.previous || requests.data.next) && <div className="d-flex gap-2 mt-3">
        <Button variant="outline-secondary" size="sm" disabled={!requests.data.previous} onClick={() => setPage(page - 1)}>{t("Previous")}</Button>
        <Button variant="outline-secondary" size="sm" disabled={!requests.data.next} onClick={() => setPage(page + 1)}>{t("Next")}</Button>
      </div>}
    </>}
  </Card.Body></Card>;
}

function PortalHome() {
  const catalog = usePortalData(`${requestPath}catalog/`);
  const { t } = useLanguage();
  return <>
    <h1 className="mb-4">{t("Requester portal")}</h1>
    <Row className="g-4">
      <Col lg={7}><RequestList /></Col>
      <Col lg={5}><Card className="app-card"><Card.Body className="p-4">
        <h2 className="h5 mb-3">{t("New test request")}</h2>
        {catalog.data
          ? <RequesterSubmissionForm catalog={catalog.data} requestPath={requestPath} />
          : <PortalLoadState resource={catalog} />}
      </Card.Body></Card></Col>
    </Row>
  </>;
}

function RequestDetail({ requestId }) {
  const { state } = useLocation();
  const { t, locale } = useLanguage();
  const path = `${requestPath}${requestId}/`;
  const request = usePortalData(path);
  const [downloadError, setDownloadError] = useState("");
  const [downloading, setDownloading] = useState(false);
  const row = request.data;
  const labelsAvailable = row && !["REJECTED", "CANCELLED"].includes(row.status);

  async function download(suffix, filename) {
    setDownloadError("");
    setDownloading(true);
    try { await apiDownload(`${path}${suffix}`, filename); }
    catch (error) { setDownloadError(error.message); }
    finally { setDownloading(false); }
  }

  return <>
    <Link to="/requester" className="d-inline-block mb-3">{t("Back to my test requests")}</Link>
    {!row ? <PortalLoadState resource={request} /> : <>
      {state?.submitted && <Alert variant="success" role="status">{t("Test request submitted.")}</Alert>}
      <div className="toolbar-row mb-4">
        <div className="text-break">
          <p className="small text-muted mb-1">{row.request_number}</p>
          <h1 className="mb-2">{row.title}</h1>
          <p className="text-muted mb-0">{row.project_name} · {row.test_name} · {formatDate(row.submitted_at, locale)}</p>
        </div>
        <div className="d-flex flex-wrap align-items-center gap-2">
          <StatusBadge status={row.status} />
          <Button size="sm" variant="outline-secondary" onClick={request.refresh}>{t("Refresh status")}</Button>
        </div>
      </div>
      {downloadError && <Alert variant="danger" role="alert">{downloadError}</Alert>}
      <Row className="g-4">
        {row.samples.length > 0 && <Col lg={7}><Card className="app-card"><Card.Body className="p-4">
          <div className="toolbar-row mb-2">
            <h2 className="h5 mb-0">{t("Submitted samples")}</h2>
            {labelsAvailable && <Button
              variant="outline-primary" size="sm" disabled={downloading}
              onClick={() => download("labels/", `${row.request_number}-labels.pdf`)}
            >{t("Download labels (PDF)")}</Button>}
          </div>
          {labelsAvailable && <p className="small text-muted">
            {t("Print at actual size on 100 × 50 mm stock. Match each label to its sample reference.")}
          </p>}
          <ul className="list-unstyled mb-0">
            {row.samples.map(sample => <li className="d-flex justify-content-between flex-wrap gap-2 py-2 border-top" key={sample.barcode}>
              <div className="text-break">
                <strong>{sample.reference}</strong>
                <div><code className="small text-muted text-break">{sample.barcode}</code></div>
              </div>
              <span className="small align-self-center">
                {sample.received_at ? `${t("Received")} · ${formatDate(sample.received_at, locale)}` : t(labelsAvailable ? "Awaiting receipt" : "Not received")}
              </span>
            </li>)}
          </ul>
        </Card.Body></Card></Col>}
        <Col lg={row.samples.length ? 5 : 12}><Card className="app-card"><Card.Body className="p-4">
          <h2 className="h5 mb-3">{t("Released reports")}</h2>
          {row.reports.length ? <ul className="list-unstyled mb-0">
            {row.reports.map(report => <li className="border-top py-2" key={report.public_id}>
              <div className="fw-semibold text-break">{report.title}</div>
              <div className="small text-muted mb-2">{formatDate(report.approved_at, locale)}</div>
              <Button size="sm" variant="outline-primary" disabled={downloading}
                aria-label={`${t("Download report")} ${report.title}`}
                onClick={() => download(`reports/${report.public_id}/download/`, report.title)}
              >{t("Download report")}</Button>
            </li>)}
          </ul> : <p className="text-muted mb-0">{t("Reports appear here after the lab releases them.")}</p>}
        </Card.Body></Card></Col>
      </Row>
    </>}
  </>;
}

export default function RequesterPortal() {
  const { requestId } = useParams();
  const { t } = useLanguage();
  const navigate = useNavigate();
  const session = usePortalData("/api/v1/session/");
  const [signOutError, setSignOutError] = useState("");
  const user = session.data?.user;

  async function signOut() {
    setSignOutError("");
    try {
      await logout();
      navigate("/login?return_to=%2Frequester", { replace: true });
    } catch (error) {
      setSignOutError(error.message);
    }
  }

  return <div className="min-vh-100 d-flex flex-column">
    <header className="bg-dark text-light">
      <Container className="d-flex flex-wrap gap-3 align-items-center justify-content-between py-3">
        <Link to="/requester" className="fw-bold text-white text-decoration-none">OpenLIMS</Link>
        {user && <div className="d-flex flex-wrap gap-3 align-items-center">
          <span className="small">{user.username}</span>
          {!isRequesterOnly(user) && <Link className="link-light small" to="/">{t("Lab workspace")}</Link>}
          <Button size="sm" variant="outline-light" onClick={signOut}>{t("Sign out")}</Button>
        </div>}
      </Container>
    </header>
    <Container as="main" className="py-4 py-lg-5 flex-grow-1">
      {signOutError && <Alert variant="danger" role="alert">{signOutError}</Alert>}
      {!session.data ? <PortalLoadState resource={session} /> : requestId
        ? <RequestDetail key={requestId} requestId={requestId} /> : <PortalHome />}
    </Container>
    <footer className="app-footer-version">OpenLIMS {OPENLIMS_VERSION}</footer>
  </div>;
}
