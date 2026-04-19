import { useEffect, useState } from "react";
import { Container, Nav, Navbar, Button, Spinner } from "react-bootstrap";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearTokens } from "./auth";
import { apiGet } from "./api";

export default function Layout() {
  const nav = useNavigate();
  const [me, setMe] = useState(null);
  const [loadingMe, setLoadingMe] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const data = await apiGet("/api/me/");
        //console.log(data)
        setMe(data);
      } catch (e) {
        console.error("Failed to load current user:", e);
      } finally {
        setLoadingMe(false);
      }
    })();
  }, []);

  function logout() {
    clearTokens();
    nav("/login");
  }

  const isAdmin = me?.roles?.includes("admin");

  return (
    <>
      <Navbar bg="dark" variant="dark" expand="lg" className="mb-4">
        <Container fluid className="px-4">
          <Navbar.Brand as={NavLink} to="/">
            OpenLIMS
          </Navbar.Brand>

          <Navbar.Toggle aria-controls="openlims-nav" />
          <Navbar.Collapse id="openlims-nav">
            <Nav className="me-auto">
              <Nav.Link as={NavLink} to="/">Dashboard</Nav.Link>
              <Nav.Link as={NavLink} to="/samples">Samples</Nav.Link>
              <Nav.Link as={NavLink} to="/inventory">Inventory</Nav.Link>
              <Nav.Link as={NavLink} to="/events">Events</Nav.Link>
              <Nav.Link as={NavLink} to="/analyze">Analyze</Nav.Link>
              <Nav.Link as={NavLink} to="/projects">Projects</Nav.Link>
              {isAdmin && (
                <Nav.Link as={NavLink} to="/users">Users</Nav.Link>,
                <Nav.Link as={NavLink} to="/imports">Imports</Nav.Link>
              )}
            </Nav>

            <div className="d-flex align-items-center gap-3">
              {loadingMe ? (
                <Spinner animation="border" size="sm" variant="light" />
              ) : (
                <small className="text-light">
                  {me?.username || "Unknown user"}
                </small>
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