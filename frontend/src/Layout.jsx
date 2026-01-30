import { NavLink, Outlet } from "react-router-dom";

const linkStyle = ({ isActive }) => ({
  padding: "8px 10px",
  borderRadius: 8,
  textDecoration: "none",
  color: "black",
  background: isActive ? "#eaeaea" : "transparent",
});

export default function Layout() {
  return (
    <div style={{ maxWidth: 980, margin: "0 auto", padding: 16, fontFamily: "system-ui, sans-serif" }}>
      <h1 style={{ marginBottom: 8 }}>OpenLIMS UI</h1>

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <NavLink to="/samples" style={linkStyle}>Samples</NavLink>
        <NavLink to="/inventory" style={linkStyle}>Inventory</NavLink>
        <NavLink to="/events" style={linkStyle}>Events</NavLink>

        <div style={{ marginLeft: "auto", display: "flex", gap: 10 }}>
          <a href="/api/" target="_blank" rel="noreferrer">API</a>
          <a href="/health" target="_blank" rel="noreferrer">Health</a>
        </div>
      </div>

      <Outlet />
    </div>
  );
}
