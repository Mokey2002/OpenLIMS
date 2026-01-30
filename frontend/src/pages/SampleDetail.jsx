import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { apiGet, apiPatch, apiPost } from "../api";

function parseInitialValue(def, existingValue) {
  // existingValue may be undefined if not set
  if (existingValue === undefined) return "";

  // for json we store whatever JSON, show as JSON string
  if (def.data_type === "json") return JSON.stringify(existingValue);

  return existingValue;
}

function coerceForSubmit(def, raw) {
  // raw comes from input elements (usually strings)
  if (raw === "" || raw === null || raw === undefined) return "";


  switch (def.data_type) {
    case "string":
      return String(raw);

    case "int":
      // input gives string; convert to int
      return Number.isNaN(parseInt(raw, 10)) ? raw : parseInt(raw, 10);

    case "float":
      return Number.isNaN(parseFloat(raw)) ? raw : parseFloat(raw);

    case "bool":
      // raw is boolean from checkbox handler
      return Boolean(raw);

    case "date":
      // keep ISO date string YYYY-MM-DD
      return String(raw);

    case "json":
      // user edits JSON as text; parse it
      return JSON.parse(raw);

    default:
      return raw;
  }
}

export default function SampleDetail() {
  const { id } = useParams();

  const [sample, setSample] = useState(null);
  const [containers, setContainers] = useState([]);

  const [defs, setDefs] = useState([]);
  const [values, setValues] = useState([]); // list of FieldValue rows
  const [form, setForm] = useState({});     // defId -> raw input value

  const [loading, setLoading] = useState(true);
  const [savingContainer, setSavingContainer] = useState(false);
  const [savingFields, setSavingFields] = useState(false);
  const [err, setErr] = useState("");

  const valueByDefId = useMemo(() => {
    const map = new Map();
    for (const v of values) map.set(v.field_definition, v);
    return map;
  }, [values]);

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
      const [s, cs, defsData, valsData] = await Promise.all([
        apiGet(`/api/samples/${id}/`),
        apiGet("/api/containers/"),
	apiGet(`/api/field-definitions/`),
        apiGet(`/api/field-values/?entity_type=Sample&entity_id=${id}`),
      ]);

      setSample(s);
      setContainers(cs);
setSample(s);
setContainers(cs);

// defsData might be paginated OR plain list
const defsList = defsData.results ?? defsData;

// only keep Sample definitions
const defsForSample = defsList.filter((d) => d.entity_type === "Sample");

setDefs(defsForSample);
setValues(valsData);

// Build initial form state from definitions + existing values
const initial = {};
for (const d of defsForSample) {
  const existing = valsData.find((v) => v.field_definition === d.id);
  initial[d.id] = parseInitialValue(d, existing ? existing.value : undefined);
}
setForm(initial);

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
    setSavingContainer(true);
    setErr("");
    try {
      const payload = { container: newContainer === "" ? null : Number(newContainer) };
      const updated = await apiPatch(`/api/samples/${id}/`, payload);
      setSample(updated);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setSavingContainer(false);
    }
  }

  function updateField(def, raw) {
    setForm((prev) => ({ ...prev, [def.id]: raw }));
  }

  async function saveCustomFields() {
    setSavingFields(true);
    setErr("");

    try {
      // For each definition, either create or update a FieldValue.
      // We’ll only send values that changed compared to what DB has.
      const updates = [];

      for (const d of defs) {
        const raw = form[d.id];

        const existing = valueByDefId.get(d.id);
        const existingRaw = parseInitialValue(d, existing ? existing.value : undefined);

        // If unchanged, skip
        if (raw === existingRaw) continue;

        // If empty and not required, we simply skip for v1 (no delete yet)
        // You can add delete later.
        if ((raw === "" || raw === null) && !d.required) {
          // If it exists, we could delete it later. For now: set to empty (will likely fail if required).
          // We'll skip to avoid writing empty values.
          continue;
        }

        let submitValue;
        try {
          submitValue = coerceForSubmit(d, raw);
        } catch (parseErr) {
          throw new Error(`Custom field "${d.name}" JSON is invalid.`);
        }

        if (!existing) {
          updates.push(
            apiPost("/api/field-values/", {
              field_definition: d.id,
              entity_type: "Sample",
              entity_id: String(id),
              value: submitValue,
            })
          );
        } else {
          updates.push(
            apiPatch(`/api/field-values/${existing.id}/`, {
              value: submitValue,
            })
          );
        }
      }

      await Promise.all(updates);

      // reload values after save
      const valsData = await apiGet(`/api/field-values/?entity_type=Sample&entity_id=${id}`);
      setValues(valsData);

      // sync form with saved values
      const synced = {};
      for (const d of defs) {
        const existing = valsData.find((v) => v.field_definition === d.id);
        synced[d.id] = parseInitialValue(d, existing ? existing.value : undefined);
      }
      setForm(synced);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setSavingFields(false);
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
            disabled={savingContainer}
            style={{ padding: 8, minWidth: 280 }}
          >
            {containerOptions.map((opt) => (
              <option key={opt.id} value={opt.id}>{opt.label}</option>
            ))}
          </select>
          {savingContainer && <span>Saving...</span>}
        </div>
      </div>

      <h3>Custom Fields</h3>

      <div style={{ border: "1px solid #eee", borderRadius: 10, padding: 12 }}>
        {defs.length === 0 ? (
          <div>
            No custom field definitions yet.
            <div style={{ marginTop: 8, fontSize: 12 }}>
              Create definitions at <code>/api/field-definitions/</code> (entity_type="Sample").
            </div>
          </div>
        ) : (
          <div style={{ display: "grid", gap: 10 }}>
            {defs.map((d) => {
              const raw = form[d.id] ?? "";
              const requiredMark = d.required ? " *" : "";

              const inputCommon = {
                style: { padding: 8, width: "100%", maxWidth: 420 },
              };

              return (
                <div key={d.id} style={{ paddingBottom: 10, borderBottom: "1px solid #f2f2f2" }}>
                  <div style={{ fontWeight: 600 }}>
                    {d.label || d.name}{requiredMark}{" "}
                    <span style={{ fontFamily: "monospace", fontSize: 12, fontWeight: 400 }}>
                      ({d.data_type})
                    </span>
                  </div>

                  <div style={{ marginTop: 6 }}>
                    {d.data_type === "bool" ? (
                      <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <input
                          type="checkbox"
                          checked={Boolean(raw)}
                          onChange={(e) => updateField(d, e.target.checked)}
                        />
                        <span>{d.name}</span>
                      </label>
                    ) : d.data_type === "date" ? (
                      <input
                        type="date"
                        value={raw}
                        onChange={(e) => updateField(d, e.target.value)}
                        {...inputCommon}
                      />
                    ) : d.data_type === "int" || d.data_type === "float" ? (
                      <input
                        type="number"
                        value={raw}
                        onChange={(e) => updateField(d, e.target.value)}
                        {...inputCommon}
                      />
                    ) : d.data_type === "json" ? (
                      <textarea
                        rows={3}
                        value={raw}
                        onChange={(e) => updateField(d, e.target.value)}
                        style={{ padding: 8, width: "100%", maxWidth: 640, fontFamily: "monospace" }}
                        placeholder='{"key":"value"}'
                      />
                    ) : (
                      <input
                        type="text"
                        value={raw}
                        onChange={(e) => updateField(d, e.target.value)}
                        {...inputCommon}
                      />
                    )}
                  </div>

                  {d.rules && Object.keys(d.rules).length > 0 && (
                    <div style={{ marginTop: 6, fontSize: 12, color: "#444" }}>
                      Rules: <span style={{ fontFamily: "monospace" }}>{JSON.stringify(d.rules)}</span>
                    </div>
                  )}
                </div>
              );
            })}

            <div style={{ display: "flex", gap: 10 }}>
              <button onClick={saveCustomFields} disabled={savingFields} style={{ padding: "10px 14px" }}>
                {savingFields ? "Saving..." : "Save Custom Fields"}
              </button>
              <button onClick={loadAll} disabled={savingFields} style={{ padding: "10px 14px" }}>
                Reload
              </button>
            </div>

            <div style={{ fontSize: 12, color: "#444" }}>
              Note: empty values for non-required fields are currently skipped (no delete yet).
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
