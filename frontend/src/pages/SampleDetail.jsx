import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiGet, apiPatch } from "../api";

export default function SampleDetail() {
  const { id } = useParams();

  const [sample, setSample] = useState(null);
  const [containers, setContainers] = useState([]);
  const [customFields, setCustomFields] = useState(null);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const containerOptions = useMemo(() => {
    return [{ id: "", label: "— Unassigned —" }].concat(
      containers.map((c) => ({
        id: String(c.id),
        label: `${c.container_id} (${c.kind}) @ location ${c.location}`,
      }))
    );
  }, [containers]);

  async function loadAll() {
    setErr("");
    setLoading(true);
    try {
      const [s, cs, cf] = await Promise.all([
        apiGet(`/api/samples/${id}/`),
        apiGet("/api/containers/"),
        apiGet(`/api/samples/${id}/custom-fields/`),
      ]);
      setSample(s);
      setContainers(cs);
      setCustomFields(cf);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
  }, [id]);

  async function onChangeContainer(e) {
    const newContainer = e.target.value; // "" or id
    setSaving(true);
    setErr("");
    try {
      const payload = { container: newContainer === "" ? null : Number(newContainer) };
      const updated = await apiPatch(`/api/samples/${id}/`, payload);
      setSample(updated);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div>Loading...</div>;

  if (err) {
    return (
      <div>
        <div style={{ marginBottom: 10 }}>
          <Link to="/samples">← Back</Link>
        </div>
        <div style={{ background: "#ffe6e6", padding: 12, borderRadius: 8 }}>
          <strong>Error:</strong> {err}
        </div>
      </div>
    );
  }

  if (!sample) return <div>Not found</div>;

  return (
    <div>
      <div style={{ marginBottom: 10 }}>
        <Link to="/samples">← Back</Link>
      </div>

      <h2 style={{ marginTop: 0 }}>
        Sample: {sample.sample_id} <span style={{ fontSize: 14, fontWeight: 400 }}>(id {sample.id})</span>
      </h2>

      <div style={{ display: "grid", gap: 8, marginBottom: 16 }}>
        <div><strong>Status:</strong> {sample.status}</div>
        <div><strong>Created:</strong> <span style={{ fontFamily: "monospace" }}>{sample.created_at}</span></div>

        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <strong>Container:</strong>
          <select
            value={sample.container ?? ""}
            onChange={onChangeContainer}
            disabled={saving}
            style={{ padding: 8, minWidth: 280 }}
          >
            {containerOptions.map((opt) => (
              <option key={opt.id} value={opt.id}>{opt.label}</option>
            ))}
          </select>
          {saving && <span>Saving...</span>}
        </div>
      </div>

      <h3>Custom Fields</h3>
      {customFields ? (
        <div style={{ border: "1px solid #eee", borderRadius: 10, padding: 12 }}>
          {customFields.fields_meta.length === 0 ? (
            <div>No custom fields set for this sample yet.</div>
          ) : (
            <table width="100%" cellPadding="8" style={{ borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd" }}>
                  <th>Name</th>
                  <th>Type</th>
                  <th>Value</th>
                </tr>
              </thead>
              <tbody>
                {customFields.fields_meta.map((f) => (
                  <tr key={f.name} style={{ borderBottom: "1px solid #f0f0f0" }}>
                    <td>{f.label}</td>
                    <td style={{ fontFamily: "monospace", fontSize: 12 }}>{f.data_type}</td>
                    <td style={{ fontFamily: "monospace", fontSize: 12 }}>
                      {JSON.stringify(f.value)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div style={{ marginTop: 10, fontSize: 12, color: "#444" }}>
            (Editing custom fields comes next — we’re only viewing in Milestone B.)
          </div>
        </div>
      ) : (
        <div>Loading custom fields...</div>
      )}
    </div>
  );
}
