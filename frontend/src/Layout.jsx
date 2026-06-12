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
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearTokens } from "./auth";
import { apiGet } from "./api";
import { isAdmin, isTech } from "./authz";

function DropdownItemLink({ to, children }) {
  return (
    <NavDropdown.Item as={NavLink} to={to}>
      {children}
    </NavDropdown.Item>
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

      <Container fluid className="px-4 pb-4">
        <Outlet />
      </Container>
    </>
  );
}