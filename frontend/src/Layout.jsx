import { useEffect, useId, useState } from "react";
import {
  Badge,
  Button,
  Container,
  Form,
  Nav,
  Navbar,
  NavDropdown,
  OverlayTrigger,
  Spinner,
  Tooltip,
} from "react-bootstrap";
import { Navigate, NavLink, useLocation, useNavigate } from "react-router-dom";
import { apiGet, logout as apiLogout } from "./api";
import { clearLegacyTokens } from "./auth";
import { isAdmin, isRequesterOnly, isTech, validIdentity } from "./authz";
import { OPENLIMS_VERSION } from "./version";
import { useLanguage } from "./i18n";
import RouteContent from "./components/RouteContent";
import AssistantWidget from "./components/AssistantWidget";
import AssistantPageProvider from "./components/AssistantPageProvider";
import FavoritesMenu from "./components/FavoritesMenu";

const routeLabels = {
  "/": "My Work",
  "/me": "My profile",
  "/access-requests": "Access requests",
  "/getting-started": "Getting started",
  "/dashboard": "Dashboard",
  "/assistant": "Assistant",
  "/projects": "Projects",
  "/samples": "Samples",
  "/receive-sample": "Receive sample",
  "/traceability": "Sample Traceability",
  "/inventory": "Inventory",
  "/registry": "Biological Registry",
  "/notebook": "Laboratory Notebook",
  "/analyze": "Analyze",
  "/investigations": "Investigation Workbench",
  "/comparisons": "Comparisons & Charts",
  "/sequences": "Sequences",
  "/alignments": "Alignments",
  "/blast": "BLAST",
  "/mass-spec": "Mass Spec",
  "/mass-spec/compare": "Compare Mass Spec",
  "/imports": "Imports",
  "/batches": "Sample Batches",
  "/qc-review": "Result QC",
  "/work-queue": "Work Queue",
  "/workflow-requests": "Workflow Requests",
  "/labels": "Barcode Labels",
  "/events": "Audit Events",
  "/reports": "Reports",
  "/notifications": "Notifications",
  "/users": "Users",
  "/settings": "Settings",
  "/sops": "SOP Management",
  "/workflow-designer": "Workflow Designer",
  "/system-status": "System Status",
  "/data-migration": "Data Migration",
};

function DropdownItemLink({ to, children, hint }) {
  const hintId = useId();
  if (!hint) return <NavDropdown.Item as={NavLink} to={to}>{children}</NavDropdown.Item>;

  return (
    <>
      <OverlayTrigger
        placement="bottom"
        trigger={["hover", "focus"]}
        overlay={<Tooltip aria-hidden="true">{hint}</Tooltip>}
      >
        <NavDropdown.Item as={NavLink} to={to} aria-describedby={hintId}>
          {children}
        </NavDropdown.Item>
      </OverlayTrigger>
      <span id={hintId} className="visually-hidden">{hint}</span>
    </>
  );
}

export default function Layout() {
  const { assistantHelperEnabled, t } = useLanguage();
  const nav = useNavigate();
  const location = useLocation();
  const [me, setMe] = useState(null);
  const [loadingMe, setLoadingMe] = useState(true);
  const [sessionCheckStatus, setSessionCheckStatus] = useState(null);
  const [unreadCount, setUnreadCount] = useState(0);
  const [globalSearch, setGlobalSearch] = useState("");
  const [featureFlags, setFeatureFlags] = useState({});

  useEffect(() => {
    const controller = new AbortController();
    const options = { signal: controller.signal, cache: "no-store" };
    clearLegacyTokens();
    (async () => {
      try {
        const session = await apiGet("/api/v1/session/", options);
        if (controller.signal.aborted) return;
        if (!validIdentity(session?.user)) {
          throw new Error("Session bootstrap did not include a valid authenticated user.");
        }
        setMe(session.user);
        setUnreadCount(session.unread_notification_count || 0);
        setFeatureFlags(session.feature_flags || {});
      } catch (sessionError) {
        if (controller.signal.aborted || sessionError.status === 401) return;
        if (sessionError.status === 400) {
          setSessionCheckStatus(400);
          return;
        }
        console.warn("Session bootstrap failed; falling back to /me/:", sessionError);
        try {
          const fallbackUser = await apiGet("/api/v1/me/", options);
          if (controller.signal.aborted) return;
          if (!validIdentity(fallbackUser)) {
            throw new Error("Fallback identity response did not include username and roles.");
          }
          setMe(fallbackUser);
          if (isRequesterOnly(fallbackUser)) return;

          try {
            const fallbackFlags = await apiGet("/api/v1/feature-flags/", options);
            if (!controller.signal.aborted) setFeatureFlags(fallbackFlags || {});
          } catch (flagsError) {
            if (!controller.signal.aborted) console.warn("Failed to load feature flags during identity fallback:", flagsError);
          }
        } catch (fallbackError) {
          if (!controller.signal.aborted && fallbackError.status !== 401) {
            setSessionCheckStatus(fallbackError.status ?? 0);
          }
        }
      } finally {
        if (!controller.signal.aborted) setLoadingMe(false);
      }
    })();
    return () => controller.abort();
  }, []);

  const userIsAdmin = isAdmin(me);
  const userIsTech = isTech(me);
  function canVisitFavorite(path) {
    if (path === "/registry" && !featureFlags.registry) return false;
    if (path === "/notebook" && !featureFlags.notebook) return false;
    if (["/users", "/settings", "/sops", "/workflow-designer", "/system-status", "/data-migration"].includes(path) && !userIsAdmin) return false;
    if (path === "/imports" && !(userIsAdmin || userIsTech)) return false;
    return Object.hasOwn(routeLabels, path);
  }

  async function logout() {
    if (!window.dispatchEvent(new Event("openlims:before-logout", { cancelable: true }))) return;
    await apiLogout();
    nav("/login", { replace: true });
  }

  function submitGlobalSearch(e) {
    e.preventDefault();
    const q = globalSearch.trim();
    if (!q) return;
    nav(`/search?q=${encodeURIComponent(q)}`);
    setGlobalSearch("");
  }

  if (loadingMe) return <main className="py-5 text-center" role="status">
    <Spinner size="sm" className="me-2" aria-hidden="true" />{t("Checking sign-in…")}
  </main>;
  if (!me) return <Navigate to="/login" replace state={{ sessionCheckStatus }} />;
  if (isRequesterOnly(me)) return <Navigate to="/requester" replace />;

  return (
    <>
      <Navbar bg="dark" variant="dark" expand="xl" sticky="top" className="mb-4 shadow-sm">
        <Container fluid className="px-4">
          <Navbar.Brand as={NavLink} to="/" className="fw-bold d-flex align-items-center gap-2">
            <span>OpenLIMS</span><Badge bg="secondary" className="fw-normal">Demo</Badge>
          </Navbar.Brand>
          <Navbar.Toggle aria-controls="openlims-nav" />
          <Navbar.Collapse id="openlims-nav">
            <Nav className="me-auto align-items-xl-center" data-testid="workflow-navigation">
              <Nav.Link as={NavLink} to="/">My Work</Nav.Link>

              <NavDropdown title="Plan" id="plan-nav">
                <DropdownItemLink to="/dashboard">Dashboard</DropdownItemLink>
                <DropdownItemLink to="/projects">Projects</DropdownItemLink>
                <DropdownItemLink to="/assistant">Assistant</DropdownItemLink>
                {userIsAdmin && <DropdownItemLink to="/workflow-designer" hint="Build reusable workflow templates with ordered steps.">Workflow Designer</DropdownItemLink>}
              </NavDropdown>

              <NavDropdown title="Receive" id="receive-nav">
                <DropdownItemLink to="/receive-sample">Receive sample</DropdownItemLink>
                <DropdownItemLink to="/samples">Samples</DropdownItemLink>
                <DropdownItemLink to="/workflow-requests">Workflow Requests</DropdownItemLink>
                <DropdownItemLink to="/requester">Requester portal</DropdownItemLink>
                <DropdownItemLink to="/inventory">Inventory</DropdownItemLink>
                {(userIsAdmin || userIsTech) && <DropdownItemLink to="/imports" hint="Preview and import CSV or Excel results.">Imports</DropdownItemLink>}
                {featureFlags.registry && <DropdownItemLink to="/registry">Biological Registry</DropdownItemLink>}
              </NavDropdown>

              <NavDropdown title="Execute" id="execute-nav">
                <DropdownItemLink to="/work-queue">Work Queue</DropdownItemLink>
                <DropdownItemLink to="/batches">Sample Batches</DropdownItemLink>
                {featureFlags.notebook && <DropdownItemLink to="/notebook">Laboratory Notebook</DropdownItemLink>}
                <DropdownItemLink to="/analyze">Analyze</DropdownItemLink>
                <DropdownItemLink to="/sequences">Sequences</DropdownItemLink>
                <DropdownItemLink to="/alignments">Alignments</DropdownItemLink>
                <DropdownItemLink to="/blast">BLAST</DropdownItemLink>
                <DropdownItemLink to="/mass-spec">Mass Spec</DropdownItemLink>
              </NavDropdown>

              <NavDropdown title="Review" id="review-nav">
                <DropdownItemLink to="/access-requests">Access requests</DropdownItemLink>
                <DropdownItemLink to="/qc-review">Result QC</DropdownItemLink>
                <DropdownItemLink to="/traceability">Sample Traceability</DropdownItemLink>
                <DropdownItemLink to="/investigations">Investigation Workbench</DropdownItemLink>
                <DropdownItemLink to="/comparisons">Comparisons & Charts</DropdownItemLink>
                <DropdownItemLink to="/mass-spec/compare">Compare Mass Spec</DropdownItemLink>
                <DropdownItemLink to="/events">Audit Events</DropdownItemLink>
                <DropdownItemLink to="/notifications">Notifications {unreadCount > 0 && <Badge bg="danger" className="ms-1">{unreadCount}</Badge>}</DropdownItemLink>
              </NavDropdown>

              <NavDropdown title="Report" id="report-nav">
                <DropdownItemLink to="/reports">Reports</DropdownItemLink>
                <DropdownItemLink to="/labels">Barcode Labels</DropdownItemLink>
                {userIsAdmin && <DropdownItemLink to="/sops">SOP Management</DropdownItemLink>}
              </NavDropdown>

              <FavoritesMenu userId={me.id} currentPath={location.pathname} routes={routeLabels} canVisit={canVisitFavorite} />

              {userIsAdmin && (
                <NavDropdown title="Admin" id="admin-nav">
                  <DropdownItemLink to="/users">Users</DropdownItemLink>
                  <DropdownItemLink to="/settings">Settings</DropdownItemLink>
                  <DropdownItemLink to="/data-migration">Data Migration</DropdownItemLink>
                  <DropdownItemLink to="/system-status">System Status</DropdownItemLink>
                </NavDropdown>
              )}
            </Nav>

            <Form className="d-flex me-xl-3 my-3 my-xl-0" onSubmit={submitGlobalSearch}>
              <Form.Control size="sm" value={globalSearch} onChange={(e) => setGlobalSearch(e.target.value)} placeholder="Search samples, projects..." style={{ minWidth: "240px" }} />
            </Form>

            <div className="d-flex align-items-center gap-3">
              <div className="text-light small text-xl-end">
                <div className="fw-semibold" data-testid="current-user-name">{me.username}</div>
                <div className="text-light opacity-75" data-testid="current-user-roles">{me.roles.length ? me.roles.join(", ") : "No assigned role"}</div>
              </div>
              <Button as={NavLink} to="/me" variant="outline-light" size="sm">My profile</Button>
              <Button as={NavLink} to="/getting-started" variant="outline-light" size="sm">Getting started</Button>
              <Button variant="outline-light" size="sm" onClick={logout}>Logout</Button>
            </div>
          </Navbar.Collapse>
        </Container>
      </Navbar>

      <AssistantPageProvider>
        <Container fluid className="px-4 pb-5">
          <RouteContent />
        </Container>
        <footer className="app-footer-version">OpenLIMS {OPENLIMS_VERSION}</footer>
        {assistantHelperEnabled && <AssistantWidget />}
      </AssistantPageProvider>
    </>
  );
}
