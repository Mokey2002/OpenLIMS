import { Container, Nav, Navbar, Button } from "react-bootstrap";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearTokens } from "./auth";

export default function Layout() {
  const nav = useNavigate();

  function logout() {
    clearTokens();
    nav("/login");
  }

  return (
    <>
      <Navbar bg="dark" variant="dark" expand="lg" className="mb-4">
        <Container fluid className="px-4">
          <Navbar.Brand as={NavLink} to="/samples">
            OpenLIMS
          </Navbar.Brand>

          <Navbar.Toggle aria-controls="openlims-nav" />
          <Navbar.Collapse id="openlims-nav">
            <Nav className="me-auto">
              <Nav.Link as={NavLink} to="/samples">Samples</Nav.Link>
              <Nav.Link as={NavLink} to="/inventory">Inventory</Nav.Link>
              <Nav.Link as={NavLink} to="/events">Events</Nav.Link>
	      <Nav.Link as={NavLink} to="/">Dashboard</Nav.Link>

            </Nav>

            <Button variant="outline-light" size="sm" onClick={logout}>
              Logout
            </Button>
          </Navbar.Collapse>
        </Container>
      </Navbar>

      <Container fluid className="px-4 pb-4">
        <Outlet />
      </Container>
    </>
  );
}
