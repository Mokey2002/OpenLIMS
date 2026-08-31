import { useEffect, useState } from "react";
import {
  Badge,
  Button,
  Container,
  Form,
  Nav,
  Navbar,
  NavDropdown,
  Spinner,
} from "react-bootstrap";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { apiGet, logout as apiLogout } from "./api";
import { clearLegacyTokens } from "./auth";
import { isAdmin, isTech } from "./authz";
import { OPENLIMS_VERSION } from "./version";
import AssistantWidget from "./components/AssistantWidget";

const FAVORITES_KEY = "openlims_favorites";

const routeLabels = {
  "/": "My Work",
  "/dashboard": "Dashboard",
  "/getting-started": "Getting Started",
  "/assistant": "Assistant",
  "/projects": "Projects",
  "/samples": "Samples",
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

const tutorialSteps = [
  { number: 1, title: "My Work overview", path: "/" },
  { number: 2, title: "Project workspace", path: "/projects" },
  { number: 3, title: "Sample traceability", path: "/samples" },
  { number: 4, title: "Import lab data", path: "/imports" },
  { number: 5, title: "Analyze imported results", path: "/analyze" },
  { number: 6, title: "Sequence workspaces", path: "/sequences" },
  { number: 7, title: "Clustal Omega alignments", path: "/alignments" },
  { number: 8, title: "Local BLAST search", path: "/blast" },
  { number: 9, title: "Mass spec run details", path: "/mass-spec" },
  { number: 10, title: "Compare mass spec runs", path: "/mass-spec/compare" },
  { number: 11, title: "Audit trail", path: "/events" },
];

function DropdownItemLink({ to, children }) {
  return <NavDropdown.Item as={NavLink} to={to}>{children}</NavDropdown.Item>;
}

function TutorialBar({ userIsAdmin }) {
  const location = useLocation();
  const nav = useNavigate();
  const params = new URLSearchParams(location.search);
  const stepNumber = Number(params.get("tour"));
  if (!stepNumber) return null;

  const steps = userIsAdmin
    ? [...tutorialSteps, { number: 12, title: "Admin settings", path: "/settings" }, { number: 13, title: "System status", path: "/system-status" }]
    : tutorialSteps;
  const index = steps.findIndex((step) => step.number === stepNumber);
  if (index < 0) return null;

  const step = steps[index];
  const previous = steps[index - 1];
  const next = steps[index + 1];

  return (
    <div className="tutorial-floating-bar">
      <div>
        <div className="feed-meta text-light opacity-75">Guided demo step {step.number} of {steps.length}</div>
        <div className="fw-semibold text-light">{step.title}</div>
      </div>
      <div className="inline-actions">
        <Button variant="outline-light" size="sm" disabled={!previous} onClick={() => previous && nav(`${previous.path}?tour=${previous.number}`)}>Previous</Button>
        <Button variant="light" size="sm" disabled={!next} onClick={() => next && nav(`${next.path}?tour=${next.number}`)}>{next ? `Next: ${next.title}` : "Done"}</Button>
        <Button variant="outline-light" size="sm" onClick={() => nav(`/getting-started?tour=${step.number}`)}>Guide</Button>
        <Button variant="outline-light" size="sm" onClick={() => nav(location.pathname)}>Exit</Button>
      </div>
    </div>
  );
}

function loadFavorites() {
  try {
    const value = JSON.parse(localStorage.getItem(FAVORITES_KEY) || "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

export default function Layout() {
  const nav = useNavigate();
  const location = useLocation();
  const [me, setMe] = useState(null);
  const [loadingMe, setLoadingMe] = useState(true);
  const [unreadCount, setUnreadCount] = useState(0);
  const [globalSearch, setGlobalSearch] = useState("");
  const [featureFlags, setFeatureFlags] = useState({});
  const [favorites, setFavorites] = useState(loadFavorites);

  useEffect(() => {
    clearLegacyTokens();
    (async () => {
      try {
        const session = await apiGet("/api/v1/session/");
        setMe(session.user);
        setUnreadCount(session.unread_notification_count || 0);
        setFeatureFlags(session.feature_flags || {});
      } catch (e) {
        console.error("Failed to load layout data:", e);
      } finally {
        setLoadingMe(false);
      }
    })();
  }, []);

  const userIsAdmin = isAdmin(me);
  const userIsTech = isTech(me);
  const currentFavoritePath = routeLabels[location.pathname] ? location.pathname : null;

  const visibleFavorites = favorites.filter((path) => {
    if (path === "/registry" && !featureFlags.registry) return false;
    if (path === "/notebook" && !featureFlags.notebook) return false;
    if (["/users", "/settings", "/sops", "/workflow-designer", "/system-status", "/data-migration"].includes(path) && !userIsAdmin) return false;
    if (path === "/imports" && !(userIsAdmin || userIsTech)) return false;
    return routeLabels[path];
  });

  function saveFavorites(next) {
    setFavorites(next);
    localStorage.setItem(FAVORITES_KEY, JSON.stringify(next));
  }

  function toggleCurrentFavorite() {
    if (!currentFavoritePath) return;
    saveFavorites(
      favorites.includes(currentFavoritePath)
        ? favorites.filter((path) => path !== currentFavoritePath)
        : [...favorites, currentFavoritePath]
    );
  }

  async function logout() {
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
                <DropdownItemLink to="/getting-started">Getting Started</DropdownItemLink>
                <DropdownItemLink to="/assistant">Assistant</DropdownItemLink>
                {userIsAdmin && <DropdownItemLink to="/workflow-designer">Workflow Designer</DropdownItemLink>}
              </NavDropdown>

              <NavDropdown title="Receive" id="receive-nav">
                <DropdownItemLink to="/samples">Samples</DropdownItemLink>
                <DropdownItemLink to="/workflow-requests">Workflow Requests</DropdownItemLink>
                <DropdownItemLink to="/inventory">Inventory</DropdownItemLink>
                {(userIsAdmin || userIsTech) && <DropdownItemLink to="/imports">Imports</DropdownItemLink>}
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

              <NavDropdown title={`Favorites${visibleFavorites.length ? ` (${visibleFavorites.length})` : ""}`} id="favorites-nav">
                {visibleFavorites.length === 0 && <NavDropdown.Item disabled>No favorites pinned</NavDropdown.Item>}
                {visibleFavorites.map((path) => <DropdownItemLink key={path} to={path}>{routeLabels[path]}</DropdownItemLink>)}
                {currentFavoritePath && <><NavDropdown.Divider /><NavDropdown.Item onClick={toggleCurrentFavorite}>{favorites.includes(currentFavoritePath) ? "★ Unpin current page" : "☆ Pin current page"}</NavDropdown.Item></>}
              </NavDropdown>

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
              {loadingMe ? <Spinner animation="border" size="sm" variant="light" /> : (
                <div className="text-light small text-xl-end">
                  <div className="fw-semibold">{me?.username || "Unknown"}</div>
                  <div className="text-light opacity-75">{me?.roles?.length ? me.roles.join(", ") : "No role"}</div>
                </div>
              )}
              <Button variant="outline-light" size="sm" onClick={logout}>Logout</Button>
            </div>
          </Navbar.Collapse>
        </Container>
      </Navbar>

      <Container fluid className="px-4 pb-5"><Outlet /></Container>
      <footer className="app-footer-version">OpenLIMS {OPENLIMS_VERSION}</footer>
      <AssistantWidget />
      <TutorialBar userIsAdmin={userIsAdmin} />
    </>
  );
}
