import { useEffect, useMemo, useState } from "react";
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
import {
  NavLink,
  Outlet,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { clearTokens } from "./auth";
import { apiGet } from "./api";
import { isAdmin, isTech } from "./authz";

const baseTutorialSteps = [
  {
    number: 1,
    title: "Dashboard overview",
    path: "/",
  },
  {
    number: 2,
    title: "Project workspace",
    path: "/projects",
  },
  {
    number: 3,
    title: "Sample traceability",
    path: "/samples",
  },
  {
    number: 4,
    title: "Import lab data",
    path: "/imports",
  },
  {
    number: 5,
    title: "Analyze imported results",
    path: "/analyze",
  },
  {
    number: 6,
    title: "Sequence workspaces",
    path: "/sequences",
  },
  {
    number: 7,
    title: "Clustal Omega alignments",
    path: "/alignments",
  },
  {
    number: 8,
    title: "Local BLAST search",
    path: "/blast",
  },
  {
    number: 9,
    title: "Mass spec run details",
    path: "/mass-spec",
  },
  {
    number: 10,
    title: "Compare mass spec runs",
    path: "/mass-spec/compare",
  },
  {
    number: 11,
    title: "Audit trail",
    path: "/events",
  },
];

const adminTutorialSteps = [
  {
    number: 12,
    title: "Admin settings",
    path: "/settings",
  },
  {
    number: 13,
    title: "System status",
    path: "/system-status",
  },
];

function getTutorialSteps(userIsAdmin) {
  return userIsAdmin
    ? [...baseTutorialSteps, ...adminTutorialSteps]
    : baseTutorialSteps;
}

function DropdownItemLink({ to, children }) {
  return (
    <NavDropdown.Item as={NavLink} to={to}>
      {children}
    </NavDropdown.Item>
  );
}

function TutorialBar({ userIsAdmin }) {
  const location = useLocation();
  const nav = useNavigate();

  const params = new URLSearchParams(location.search);
  const rawTour = params.get("tour");
  const stepNumber = rawTour ? Number(rawTour) : null;

  if (!stepNumber || Number.isNaN(stepNumber)) return null;

  const tutorialSteps = getTutorialSteps(userIsAdmin);
  const index = tutorialSteps.findIndex((step) => step.number === stepNumber);
  if (index < 0) return null;

  const step = tutorialSteps[index];
  const previousStep = tutorialSteps[index - 1];
  const nextStep = tutorialSteps[index + 1];

  function goToStep(targetStep) {
    if (!targetStep) return;
    nav(`${targetStep.path}?tour=${targetStep.number}`);
  }

  function exitTour() {
    nav(location.pathname);
  }

  return (
    <div className="tutorial-floating-bar">
      <div>
        <div className="feed-meta text-light opacity-75">
          Guided demo step {step.number} of {tutorialSteps.length}
        </div>
        <div className="fw-semibold text-light">{step.title}</div>
      </div>

      <div className="inline-actions">
        <Button
          variant="outline-light"
          size="sm"
          onClick={() => goToStep(previousStep)}
          disabled={!previousStep}
        >
          Previous
        </Button>

        <Button
          variant="light"
          size="sm"
          onClick={() => goToStep(nextStep)}
          disabled={!nextStep}
        >
          {nextStep ? `Next: ${nextStep.title}` : "Done"}
        </Button>

        <Button
          variant="outline-light"
          size="sm"
          onClick={() => nav(`/getting-started?tour=${step.number}`)}
        >
          Guide
        </Button>

        <Button variant="outline-light" size="sm" onClick={exitTour}>
          Exit
        </Button>
      </div>
    </div>
  );
}

export default function Layout() {
  const nav = useNavigate();

  const [me, setMe] = useState(null);
  const [loadingMe, setLoadingMe] = useState(true);
  const [notifications, setNotifications] = useState([]);
  const [globalSearch, setGlobalSearch] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [meData, notificationData] = await Promise.all([
          apiGet("/api/me/"),
          apiGet("/api/notifications/"),
        ]);

        setMe(meData);
        setNotifications(notificationData.results || notificationData || []);
      } catch (e) {
        console.error("Failed to load layout data:", e);
        setNotifications([]);
      } finally {
        setLoadingMe(false);
      }
    })();
  }, []);

  function logout() {
    clearTokens();
    nav("/login");
  }

  function submitGlobalSearch(e) {
    e.preventDefault();

    const q = globalSearch.trim();
    if (!q) return;

    nav(`/search?q=${encodeURIComponent(q)}`);
    setGlobalSearch("");
  }

  const unreadCount = useMemo(
    () => notifications.filter((notification) => !notification.is_read).length,
    [notifications]
  );

  const userIsAdmin = isAdmin(me);
  const userIsTech = isTech(me);

  return (
    <>
      <Navbar
        bg="dark"
        variant="dark"
        expand="xl"
        sticky="top"
        className="mb-4 shadow-sm"
      >
        <Container fluid className="px-4">
          <Navbar.Brand
            as={NavLink}
            to="/"
            className="fw-bold d-flex align-items-center gap-2"
          >
            <span>OpenLIMS</span>
            <Badge bg="secondary" className="fw-normal">
              Demo
            </Badge>
          </Navbar.Brand>

          <Navbar.Toggle aria-controls="openlims-nav" />

          <Navbar.Collapse id="openlims-nav">
            <Nav className="me-auto align-items-xl-center">
              <Nav.Link as={NavLink} to="/">
                Dashboard
              </Nav.Link>

              <Nav.Link as={NavLink} to="/getting-started">
                Getting Started
              </Nav.Link>

              <NavDropdown title="Core" id="core-nav">
                <DropdownItemLink to="/projects">Projects</DropdownItemLink>
                <DropdownItemLink to="/samples">Samples</DropdownItemLink>
                <DropdownItemLink to="/inventory">Inventory</DropdownItemLink>
              </NavDropdown>

              <NavDropdown title="Analysis" id="analysis-nav">
                <DropdownItemLink to="/analyze">Analyze</DropdownItemLink>
                <DropdownItemLink to="/sequences">Sequences</DropdownItemLink>
                <DropdownItemLink to="/alignments">Alignments</DropdownItemLink>
                <DropdownItemLink to="/blast">BLAST</DropdownItemLink>
                <DropdownItemLink to="/mass-spec">Mass Spec</DropdownItemLink>
                <DropdownItemLink to="/mass-spec/compare">
                  Compare Mass Spec
                </DropdownItemLink>
              </NavDropdown>

              <NavDropdown title="Operations" id="operations-nav">
                {(userIsAdmin || userIsTech) && (
                  <DropdownItemLink to="/imports">Imports</DropdownItemLink>
                )}

                <DropdownItemLink to="/events">Audit Events</DropdownItemLink>
                <DropdownItemLink to="/reports">Reports</DropdownItemLink>

                <DropdownItemLink to="/notifications">
                  Notifications{" "}
                  {unreadCount > 0 && (
                    <Badge bg="danger" className="ms-1">
                      {unreadCount}
                    </Badge>
                  )}
                </DropdownItemLink>
              </NavDropdown>

              {userIsAdmin && (
                <NavDropdown title="Admin" id="admin-nav">
                  <DropdownItemLink to="/users">Users</DropdownItemLink>
                  <DropdownItemLink to="/settings">Settings</DropdownItemLink>
                  <DropdownItemLink to="/system-status">
                    System Status
                  </DropdownItemLink>
                </NavDropdown>
              )}
            </Nav>

            <Form
              className="d-flex me-xl-3 my-3 my-xl-0"
              onSubmit={submitGlobalSearch}
            >
              <Form.Control
                size="sm"
                value={globalSearch}
                onChange={(e) => setGlobalSearch(e.target.value)}
                placeholder="Search samples, projects..."
                style={{ minWidth: "260px" }}
              />
            </Form>

            <div className="d-flex align-items-center gap-3">
              {loadingMe ? (
                <Spinner animation="border" size="sm" variant="light" />
              ) : (
                <div className="text-light small text-xl-end">
                  <div className="fw-semibold">{me?.username || "Unknown"}</div>
                  <div className="text-light opacity-75">
                    {me?.roles?.length ? me.roles.join(", ") : "No role"}
                  </div>
                </div>
              )}

              <Button variant="outline-light" size="sm" onClick={logout}>
                Logout
              </Button>
            </div>
          </Navbar.Collapse>
        </Container>
      </Navbar>

      <Container fluid className="px-4 pb-5">
        <Outlet />
      </Container>

      <TutorialBar userIsAdmin={userIsAdmin} />
    </>
  );
}
