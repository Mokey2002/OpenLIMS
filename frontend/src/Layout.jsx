import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { clearTokens } from "./auth";

const linkStyle = ({ isActive }) => ({
  padding: "8px 10px",
  borderRadius: 8,
  textDecoration: "none",
  color: "black",
  background: isActive ? "#eaeaea" : "transparent",
});

export default function Layout() {
  const nav = useNavigate();

  return (
    <div style={{ maxWidth: 980, margin: "0 auto", padding: 16, fontFamily: "system-ui, sans-serif" }}>
      <h1 style={{ marginBottom: 8 }}>OpenLIMS UI</h1>

      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <NavLink to="/samples" style={linkStyle}>Samples</NavLink>
        <NavLink to="/inventory" style={linkStyle}>Inventory</NavLink>
        <NavLink to="/events" style={linkStyle}>Events</NavLink>

        <div style={{ marginLeft: "auto", display: "flex", gap: 10, alignItems: "center" }}>
          <a href="/api/" target="_blank" rel="noreferrer">API</a>
          <a href="/health" target="_blank" rel="noreferrer">Health</a>
          <button
            onClick={() => {
              clearTokens();
              nav("/login");
            }}
          >
            Logout
          </button>
        </div>
      </div>

      <Outlet />
    </div>
  );
}
