import { useEffect, useState } from "react";
import { apiGet } from "../api";

export default function Events() {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  async function load() {
    setErr("");
    setLoading(true);
    try {
      const data = await apiGet("/api/events/");
      setEvents(data);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Events</h2>

      {err && (
        <div style={{ background: "#ffe6e6", padding: 12, borderRadius: 8, marginBottom: 12 }}>
          <strong>Error:</strong> {err}
        </div>
      )}

      {loading ? (
        <div>Loading...</div>
      ) : (
        <table width="100%" cellPadding="10" style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd" }}>
              <th>Time</th>
              <th>Entity</th>
              <th>Action</th>
              <th>Payload</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e) => (
              <tr key={e.id} style={{ borderBottom: "1px solid #f0f0f0" }}>
                <td style={{ fontFamily: "monospace", fontSize: 12 }}>{e.timestamp}</td>
                <td>{e.entity_type} #{e.entity_id}</td>
                <td>{e.action}</td>
                <td style={{ fontFamily: "monospace", fontSize: 12 }}>{JSON.stringify(e.payload)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
