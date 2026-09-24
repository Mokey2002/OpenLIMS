import { useEffect, useState } from "react";
import { Alert, Badge, Button, Card, Col, Row, Spinner } from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGet, apiGetAll } from "../api";
import { useLanguage } from "../i18n";

export default function MyProfile() {
  const { t, language } = useLanguage();
  const [account, setAccount] = useState(null);
  const [projects, setProjects] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [projectsError, setProjectsError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    apiGet("/api/me/").then((data) => {
      if (active) setAccount(data);
    }).catch(() => { if (active) setError(true); })
      .finally(() => { if (active) setLoading(false); });
    apiGetAll("/api/projects/").then((data) => {
      if (active) setProjects(data);
    }).catch(() => { if (active) setProjectsError(true); });
    return () => { active = false; };
  }, [attempt]);

  function retry() {
    setLoading(true);
    setError(false);
    setProjectsError(false);
    setProjects(null);
    setAttempt((value) => value + 1);
  }

  const roles = account?.roles || [];
  const roleLabels = { admin: t("Director / administrator"), tech: t("Technician"), viewer: t("Read-only user"), qc_reviewer: t("QC reviewer") };
  const loginDate = account?.last_login ? new Date(account.last_login) : null;
  const lastLogin = loginDate && !Number.isNaN(loginDate.getTime())
    ? loginDate.toLocaleString(language === "es" ? "es" : "en") : t("Not available");
  const fields = [
    [t("Username"), account?.username],
    [t("Full name"), account?.full_name],
    [t("Email address"), account?.email],
    [t("Account status"), account?.is_active ? t("Active") : t("Inactive")],
    [t("Last sign-in"), lastLogin],
  ];

  return <div className="mx-auto" style={{ maxWidth: 1100 }}>
    <div className="page-header mb-4">
      <h1 className="page-title">{t("My profile")}</h1>
      <p className="text-muted">{t("Your account details and laboratory access.")}</p>
    </div>
    {loading ? <div role="status" className="py-5 text-center"><Spinner size="sm" className="me-2" />{t("Loading profile...")}</div> : error ?
      <Alert variant="danger">{t("Unable to load your profile.")} <Button variant="outline-danger" size="sm" onClick={retry}>{t("Try again")}</Button></Alert> :
      <Row className="g-4">
        <Col lg={7}><Card className="app-card h-100"><Card.Body>
          <h2 className="h5 mb-4">{t("Account information")}</h2>
          <dl className="row mb-0">{fields.map(([label, value]) => <div className="row mx-0 px-0 mb-3" key={label}>
            <dt className="col-sm-4 text-muted fw-normal">{label}</dt>
            <dd className="col-sm-8 mb-0 text-break" translate="no">{value || t("Not provided")}</dd>
          </div>)}</dl>
          <p className="text-muted small mt-3 mb-0">{t("Contact your administrator to correct your name, email, or access.")}</p>
        </Card.Body></Card></Col>
        <Col lg={5}><Card className="app-card h-100"><Card.Body>
          <h2 className="h5 mb-3">{t("Your roles")}</h2>
          <div className="d-flex flex-wrap gap-2 mb-3">{roles.length ? roles.map((role) =>
            <Badge bg="secondary" key={role}>{roleLabels[role] || <span translate="no">{role}</span>}</Badge>
          ) : <p className="text-muted">{t("No assigned role")}</p>}</div>
          <p className="small text-muted">{t("Roles work together with project membership and notebook sharing. Access can differ between records.")}</p>
          {account?.is_superuser && <p className="small">{t("This account also has Django superuser access. Application roles are listed above.")}</p>}
          <h2 className="h5 mt-4">{t("Password")}</h2>
          <p className="small text-muted">{t("Use email recovery to choose a new password. Email delivery must be configured by your administrator.")}</p>
          <Button as={Link} to="/forgot-password" variant="outline-primary">{t("Reset your password")}</Button>
        </Card.Body></Card></Col>
        <Col xs={12}><Card className="app-card"><Card.Body>
          <h2 className="h5">{t("Accessible projects")}</h2>
          <p className="text-muted small">{t("Projects visible to your account, including any access granted by your role.")}</p>
          {projectsError ? <Alert variant="warning">{t("Unable to load projects.")} <Button size="sm" variant="outline-secondary" onClick={retry}>{t("Try again")}</Button></Alert> :
            projects === null ? <p role="status">{t("Loading projects...")}</p> : projects.length ? <ul className="list-unstyled mb-0">{projects.map((project) => <li key={project.id} className="py-2 border-bottom">
              <Link to={`/projects/${project.id}`} className="text-break" translate="no">{project.code} — {project.name}</Link>
            </li>)}</ul> : <p className="text-muted mb-0">{t("No projects are currently visible to your account.")}</p>}
        </Card.Body></Card></Col>
      </Row>}
  </div>;
}
