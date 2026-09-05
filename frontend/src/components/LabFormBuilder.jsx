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
  const load = async () => setForms(await apiGet("/api/sample-forms/"));
  useEffect(() => { let active = true; apiGet("/api/sample-forms/").then(data => { if (active) setForms(data); }).catch(e => { if (active) setError(e.message); }); return () => { active = false; }; }, []);
  const locked = draft.published || draft.archived;
  const change = (key, value) => { setDraft({ ...draft, [key]: value }); setDirty(true); };
  const fieldChange = (index, key, value) => change("fields", draft.fields.map((f, i) => i === index ? { ...f, [key]: value } : f));
  async function action(kind) {
    setBusy(true); setError(""); setMessage("");
    try {
      let result;
      if (kind === "save") {
        const payload = { code: draft.code, name_en: draft.name_en, name_es: draft.name_es, fields: draft.fields };
        result = draft.id ? await apiPatch(`/api/sample-forms/${draft.id}/`, payload) : await apiPost("/api/sample-forms/", payload);
      } else result = await apiPost(`/api/sample-forms/${draft.id}/${kind}/`, {});
      setDraft(result); setDirty(false); await load(); setMessage(t("Configuration saved.", "Configuración guardada."));
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  function move(index, direction) {
    const fields = [...draft.fields];
    [fields[index], fields[index + direction]] = [fields[index + direction], fields[index]];
    change("fields", fields);
  }
  return <Card className="my-4"><Card.Body>
    <h2>{t("Lab Configuration · Sample forms", "Configuración del laboratorio · Formularios de muestras")}</h2>
    <p>{t("Save a draft, preview its fields, then publish. Existing samples keep their original version.", "Guarde un borrador, revise sus campos y publíquelo. Las muestras existentes conservan su versión original.")}</p>
    {error && <Alert variant="danger">{error}</Alert>}{message && <Alert variant="success">{message}</Alert>}
    {dirty && <Alert variant="warning">{t("Unsaved changes. Save before publishing or switching forms.", "Cambios sin guardar. Guarde antes de publicar o cambiar de formulario.")}</Alert>}
    <Form.Select aria-label={t("Form version", "Versión del formulario")} value={draft.id || ""} disabled={busy || dirty}
      onChange={e => { setDraft(forms.find(f => f.id === Number(e.target.value)) || blank()); setValues({}); }}>
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
          {[["text", t("Text", "Texto")], ["number", t("Number", "Número")], ["date", t("Date", "Fecha")], ["boolean", t("Yes / No", "Sí / No")]].map(([v, label]) => <option key={v} value={v}>{label}</option>)}
        </Form.Select>
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
      {draft.id && !locked && <Button disabled={busy || dirty} onClick={() => action("publish")}>{t("Publish saved draft", "Publicar borrador guardado")}</Button>}
      {draft.id && <Button disabled={busy || dirty} variant="outline-primary" onClick={() => { setDraft({ code: draft.code, name_en: draft.name_en, name_es: draft.name_es, fields: structuredClone(draft.fields) }); setDirty(true); setValues({}); }}>{t("Copy to new draft", "Copiar a un borrador nuevo")}</Button>}
      {draft.id && !draft.archived && <Button disabled={busy || dirty} variant="outline-danger" onClick={() => action("archive")}>{t("Archive saved version", "Archivar versión guardada")}</Button>}
    </div>
    <h3>{t("Form preview", "Vista previa del formulario")}</h3>
    <SampleFormFields fields={draft.fields} values={values} onChange={setValues} />
  </Card.Body></Card>;
}
