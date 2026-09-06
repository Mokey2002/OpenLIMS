import { useEffect, useState } from "react";
import { Alert, Button, Card, Form } from "react-bootstrap";
import { apiGet, apiPost, apiPatch } from "../api";
import { useLanguage } from "../i18n";
import SampleFormFields from "./SampleFormFields";
const blank = () => ({ code: "", name_en: "", name_es: "", fields: [] });
export default function LabFormBuilder() {
  const { language } = useLanguage();
  const t = (en, es) => language === "es" ? es : en;
  const [forms, setForms] = useState([]), [draft, setDraft] = useState(blank);
  const [values, setValues] = useState({}), [busy, setBusy] = useState(false);
  const [error, setError] = useState(""), [message, setMessage] = useState("");
  const [dirty, setDirty] = useState(false);
  const [comparison, setComparison] = useState(null);
  const load = async () => setForms(await apiGet("/api/sample-forms/"));
  useEffect(() => { let active = true; apiGet("/api/sample-forms/").then(data => { if (active) setForms(data); }).catch(e => { if (active) setError(e.message); }); return () => { active = false; }; }, []);
  const locked = draft.published || draft.archived;
  const change = (key, value) => { setDraft({ ...draft, [key]: value }); setDirty(true); setComparison(null); };
  const fieldChange = (index, key, value) => change("fields", draft.fields.map((f, i) => {
    if (i !== index) return f;
    const next = { ...f, [key]: value };
    if (value === undefined) delete next[key];
    if (key === "type") { delete next.choices; delete next.min; delete next.max; }
    return next;
  }));
  async function action(kind) {
    setBusy(true); setError(""); setMessage("");
    try {
      let result;
      if (kind === "save") {
        const payload = { code: draft.code, name_en: draft.name_en, name_es: draft.name_es, fields: draft.fields };
        result = draft.id ? await apiPatch(`/api/sample-forms/${draft.id}/`, payload) : await apiPost("/api/sample-forms/", payload);
      } else result = await apiPost(`/api/sample-forms/${draft.id}/${kind}/`, kind === "publish" ? { review_token: comparison?.review_token } : {});
      setDraft(result); setDirty(false); setComparison(null); await load(); setMessage(t("Configuration saved.", "Configuración guardada."));
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  function move(index, direction) {
    const fields = [...draft.fields];
    [fields[index], fields[index + direction]] = [fields[index + direction], fields[index]];
    change("fields", fields);
  }
  function exportTemplate() {
    const template = { format: "openlims.sample-form.v1", code: draft.code, name_en: draft.name_en, name_es: draft.name_es, fields: draft.fields };
    const url = URL.createObjectURL(new Blob([JSON.stringify(template, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = "openlims-sample-form.json"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <Card className="my-4"><Card.Body>
    <h2>{t("Lab Configuration · Sample forms", "Configuración del laboratorio · Formularios de muestras")}</h2>
    <p>{t("Save a draft, preview its fields, then publish. Existing samples keep their original version.", "Guarde un borrador, revise sus campos y publíquelo. Las muestras existentes conservan su versión original.")}</p>
    <Button variant="outline-secondary" disabled={busy || dirty || !draft.id} onClick={exportTemplate}>{t("Export saved template", "Exportar plantilla guardada")}</Button>
    <Form.Group className="my-2" controlId="import-form-template"><Form.Label>{t("Import template as a new draft", "Importar plantilla como borrador nuevo")}</Form.Label>
      <Form.Control type="file" accept="application/json,.json" disabled={busy || dirty} onChange={async e => { const file = e.target.files[0]; if (!file) return; setBusy(true); setError(""); try {
        if (file.size > 100000) throw new Error(t("Maximum 100 KB.", "Máximo 100 KB."));
        const data = JSON.parse(await file.text());
        if (data.format !== "openlims.sample-form.v1" || !Array.isArray(data.fields) || data.fields.length > 50 || data.fields.some(f => !f || typeof f !== "object") || [data.code, data.name_en, data.name_es].some(v => typeof v !== "string")) throw new Error(t("Invalid template.", "Plantilla inválida."));
        const result = await apiPost("/api/sample-forms/", { code: data.code, name_en: data.name_en, name_es: data.name_es, fields: data.fields });
        setDraft(result); setValues({}); setComparison(null); await load();
      } catch(error) { setError(error.message); } finally { setBusy(false); } }} />
    </Form.Group>
    {error && <Alert variant="danger">{error}</Alert>}{message && <Alert variant="success">{message}</Alert>}
    {dirty && <Alert variant="warning">{t("Unsaved changes. Save before publishing or switching forms.", "Cambios sin guardar. Guarde antes de publicar o cambiar de formulario.")}</Alert>}
    <Form.Select aria-label={t("Form version", "Versión del formulario")} value={draft.id || ""} disabled={busy || dirty}
      onChange={e => { setDraft(forms.find(f => f.id === Number(e.target.value)) || blank()); setValues({}); setComparison(null); }}>
      <option value="">{t("New sample type", "Nuevo tipo de muestra")}</option>
      {forms.map(f => <option key={f.id} value={f.id}>{f.code} · #{f.id} · {f.archived ? t("Archived", "Archivado") : f.published ? t("Published", "Publicado") : t("Draft", "Borrador")}</option>)}
    </Form.Select>
    <fieldset disabled={busy || locked} className="mt-3">
      {[["code", t("Sample type code", "Código del tipo")], ["name_en", t("English name", "Nombre en inglés")], ["name_es", t("Spanish name", "Nombre en español")]].map(([key, label]) =>
        <Form.Group key={key} controlId={`lab-form-${key}`} className="mb-2"><Form.Label>{label}</Form.Label><Form.Control value={draft[key]} maxLength={key === "code" ? 64 : 128} onChange={e => change(key, e.target.value)} /></Form.Group>)}
      {draft.fields.map((f, i) => <Card key={i} className="my-3"><Card.Body>
        {[["key", t("Field key", "Clave del campo")], ["en", t("English label", "Etiqueta en inglés")], ["es", t("Spanish label", "Etiqueta en español")], ["unit", t("Unit (optional)", "Unidad (opcional)")]].map(([key, label]) =>
          <Form.Group key={key} controlId={`editor-${i}-${key}`}><Form.Label>{label}</Form.Label><Form.Control value={f[key] || ""} onChange={e => fieldChange(i, key, e.target.value)} /></Form.Group>)}
        <Form.Select className="mt-2" aria-label={t("Field type", "Tipo de campo")} value={f.type} onChange={e => fieldChange(i, "type", e.target.value)}>
          {[["text", t("Text", "Texto")], ["number", t("Number", "Número")], ["date", t("Date", "Fecha")], ["boolean", t("Yes / No", "Sí / No")], ["select", t("Dropdown", "Lista desplegable")]].map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        </Form.Select>
        {f.type === "select" && <Form.Group controlId={`choices-${i}`}><Form.Label>{t("Options (one per line)", "Opciones (una por línea)")}</Form.Label><Form.Control as="textarea" value={(f.choices || []).join("\n")} onChange={e => fieldChange(i, "choices", e.target.value.split("\n"))} /></Form.Group>}
        {f.type === "number" && ["min", "max"].map(bound => <Form.Group key={bound} controlId={`${bound}-${i}`}><Form.Label>{bound === "min" ? t("Minimum", "Mínimo") : t("Maximum", "Máximo")}</Form.Label><Form.Control type="number" step="any" value={f[bound] ?? ""} onChange={e => fieldChange(i, bound, e.target.value === "" ? undefined : Number(e.target.value))} /></Form.Group>)}
        <Form.Group controlId={`condition-${i}`}><Form.Label>{t("Show only when", "Mostrar solo cuando")}</Form.Label>
          <Form.Select value={f.show_if?.key || ""} onChange={e => { const parent = draft.fields.find(p => p.key === e.target.value); fieldChange(i, "show_if", parent ? { key: parent.key, equals: parent.type === "boolean" ? true : parent.choices?.[0] || "" } : undefined); }}>
            <option value="">{t("Always visible", "Siempre visible")}</option>
            {draft.fields.slice(0, i).filter(p => !p.show_if && ["boolean", "select"].includes(p.type)).map(p => <option key={p.key} value={p.key}>{p[language === "es" ? "es" : "en"] || p.key}</option>)}
          </Form.Select>
        </Form.Group>
        {f.show_if && <Form.Select aria-label={t("Equals", "Igual a")} value={String(f.show_if.equals)} onChange={e => fieldChange(i, "show_if", { ...f.show_if, equals: draft.fields.find(p => p.key === f.show_if.key)?.type === "boolean" ? e.target.value === "true" : e.target.value })}>
          {(draft.fields.find(p => p.key === f.show_if.key)?.type === "boolean" ? ["true", "false"] : draft.fields.find(p => p.key === f.show_if.key)?.choices || []).map(c => <option key={c} value={c}>{c === "true" ? t("Yes", "Sí") : c === "false" ? "No" : c}</option>)}
        </Form.Select>}
        <Form.Check id={`required-${i}`} label={t("Required", "Obligatorio")} checked={f.required} onChange={e => fieldChange(i, "required", e.target.checked)} />
        <Button size="sm" disabled={i === 0} onClick={() => move(i, -1)}>{t("Move up", "Subir")}</Button>{" "}
        <Button size="sm" disabled={i === draft.fields.length - 1} onClick={() => move(i, 1)}>{t("Move down", "Bajar")}</Button>{" "}
        <Button size="sm" variant="outline-danger" onClick={() => change("fields", draft.fields.filter((_, n) => n !== i))}>{t("Remove from draft", "Quitar del borrador")}</Button>
      </Card.Body></Card>)}
      <Button disabled={draft.fields.length >= 50} onClick={() => change("fields", [...draft.fields, { key: `field_${draft.fields.length + 1}`, en: "", es: "", type: "text", required: false, unit: "" }])}>{t("Add field", "Agregar campo")}</Button>{" "}
      <Button onClick={() => action("save")}>{t("Save draft", "Guardar borrador")}</Button>
    </fieldset>
    <div className="d-flex gap-2 my-3">
      {dirty && <Button disabled={busy} variant="outline-secondary" onClick={() => { setDraft(forms.find(f => f.id === draft.id) || blank()); setDirty(false); setValues({}); }}>{t("Discard unsaved changes", "Descartar cambios sin guardar")}</Button>}
      {draft.id && !locked && <Button disabled={busy || dirty} onClick={async () => { setError(""); try { setComparison(await apiGet(`/api/sample-forms/${draft.id}/publish-preview/`)); } catch(e) { setError(e.message); } }}>{t("Review publication", "Revisar publicación")}</Button>}
      {draft.id && <Button disabled={busy || dirty} variant="outline-primary" onClick={() => { setDraft({ code: draft.code, name_en: draft.name_en, name_es: draft.name_es, fields: structuredClone(draft.fields) }); setDirty(true); setValues({}); }}>{t("Copy to new draft", "Copiar a un borrador nuevo")}</Button>}
      {draft.id && !draft.archived && <Button disabled={busy || dirty} variant="outline-danger" onClick={() => action("archive")}>{t("Archive saved version", "Archivar versión guardada")}</Button>}
    </div>
    {comparison && !dirty && !locked && <Alert variant="warning">
      <p>{t(`Added: ${comparison.added.join(", ") || "—"}. Removed: ${comparison.removed.join(", ") || "—"}. Changed: ${comparison.changed.join(", ") || "—"}.`, `Agregados: ${comparison.added.join(", ") || "—"}. Eliminados: ${comparison.removed.join(", ") || "—"}. Modificados: ${comparison.changed.join(", ") || "—"}.`)}</p>
      <p>{t(`${comparison.existing_samples} existing samples retain their original version. Review import mappings and workflow requirements before publishing.`, `${comparison.existing_samples} muestras existentes conservan su versión original. Revise las importaciones y los requisitos del flujo antes de publicar.`)}</p>
      {!comparison.will_be_latest && <p>{t("This older draft will not become the active version. Copy it to a new draft.", "Este borrador anterior no será la versión activa. Cópielo a uno nuevo.")}</p>}
      <Button disabled={busy || !comparison.will_be_latest} onClick={() => action("publish")}>{t("Confirm publication", "Confirmar publicación")}</Button>
    </Alert>}
    <h3>{t("Form preview", "Vista previa del formulario")}</h3>
    <SampleFormFields fields={draft.fields} values={values} onChange={setValues} />
  </Card.Body></Card>;
}
