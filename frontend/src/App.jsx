import { useEffect, useState } from "react";
import { apiGet, apiPost } from "./api";

export default function App() {
  const [samples, setSamples] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [sampleId, setSampleId] = useState("");

  async function load() {
    setErr("");
    setLoading(true);
    try {
      const data = await apiGet("/api/samples/");
      setSamples(data);
    } catch (e) {
      setErr(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function createSample(e) {
    e.preventDefault();
    setErr("");
    const id = sampleId.trim();
    if (!id) return;

    try {
      await apiPost("/api/samples/", { sample_id: id, status: "RECEIVED" });
      setSampleId("");
      await load();
    } catch (e) {
      setErr(String(e.message || e));
    }
  }

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: 16, fontFamily: "system-ui, sans-serif" }}>
      <h1>OpenLIMS UI</h1>

      <div style={{ marginBottom: 12 }}>
        <a href="/api/" target="_blank" rel="noreferrer">API</a>{" "}
        |{" "}
        <a href="/health" target="_blank" rel="noreferrer">Health</a>
      </div>

      <form onSubmit={createSample} style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <input
          value={sampleId}
          onChange={(e) => setSampleId(e.target.value)}
          placeholder="New sample id (e.g. S-002)"
          style={{ flex: 1, padding: 10 }}
        />
        <button type="submit" style={{ padding: "10px 14px" }}>Create</button>
      </form>

      {err && (
        <div style={{ padding: 12, borderRadius: 8, background: "#ffe6e6", marginBottom: 12 }}>
          <strong>Error:</strong> {err}
        </div>
      )}

      {loading ? (
        <div>Loading samples...</div>
      ) : (
        <table width="100%" cellPadding="10" style={{ borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd" }}>
              <th>ID</th>
              <th>sample_id</th>
              <th>status</th>
              <th>container</th>
              <th>created_at</th>
            </tr>
          </thead>
          <tbody>
            {samples.map((s) => (
              <tr key={s.id} style={{ borderBottom: "1px solid #f0f0f0" }}>
                <td>{s.id}</td>
                <td>{s.sample_id}</td>
                <td>{s.status}</td>
                <td>{s.container ?? "-"}</td>
                <td style={{ fontFamily: "monospace", fontSize: 12 }}>{s.created_at}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
