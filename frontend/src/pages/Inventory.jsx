import { useEffect, useState } from "react";
import { apiGet } from "../api";

export default function Inventory() {
  const [locations, setLocations] = useState([]);
  const [containers, setContainers] = useState([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [locs, conts] = await Promise.all([
          apiGet("/api/locations/"),
          apiGet("/api/containers/"),
        ]);
        setLocations(locs);
        setContainers(conts);
      } catch (e) {
        setErr(e.message || String(e));
      }
    })();
  }, []);

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Inventory</h2>

      {err && (
        <div style={{ background: "#ffe6e6", padding: 12, borderRadius: 8, marginBottom: 12 }}>
          <strong>Error:</strong> {err}
        </div>
      )}

      <h3>Locations</h3>
      <ul>
        {locations.map((l) => (
          <li key={l.id}>
            {l.name} ({l.kind}) — id {l.id}
          </li>
        ))}
      </ul>

      <h3>Containers</h3>
      <ul>
        {containers.map((c) => (
          <li key={c.id}>
            {c.container_id} ({c.kind}) — location {c.location} — id {c.id}
          </li>
        ))}
      </ul>
    </div>
  );
}
