import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiGet, apiPost } from "../api";

export default function SamplesList() {
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
      setErr(e.message || String(e));
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
      setErr(e.message || String(e));
    }
  }

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Samples</h2>

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
                <td>
                  <Link to={`/samples/${s.id}`}>{s.sample_id}</Link>
                </td>
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
