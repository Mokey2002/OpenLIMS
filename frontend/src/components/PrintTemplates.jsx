import { useEffect, useId, useState } from "react";
import { Alert, Button, Form } from "react-bootstrap";
import { apiGet, apiGetAll, apiPatch, apiPost, apiPostDownload } from "../api";
import { isAdmin } from "../authz";
import { useLanguage } from "../i18n";

const defaults = kind => kind === "LABEL" ? { title: "", footer: "", page_size: "LETTER", columns: 2, rows: 5, show_project: true, border: true } : { title: "", footer: "", page_size: "LETTER", orientation: "portrait", show_summary: true };

export default function PrintTemplates({ kind, selected, onSelect }) {
  const { language } = useLanguage();
  const t = (en, es) => language === "es" ? es : en;
  const id = useId();
  const [rows, setRows] = useState([]), [admin, setAdmin] = useState(false), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({ name: "", kind, config: defaults(kind) });
  useEffect(() => {
    let active = true;
    Promise.all([apiGetAll("/api/print-templates/"), apiGet("/api/me/")]).then(([templates, me]) => {
      if (active) { setRows(templates.filter(row => row.kind === kind)); setAdmin(isAdmin(me)); }
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [kind]);
  const update = (key, value) => setDraft({ ...draft, config: { ...draft.config, [key]: value } });
  async function save(archive = false) {
    setBusy(true); setError("");
    try {
      const result = draft.id ? await apiPatch(`/api/print-templates/${draft.id}/`, { ...draft, archived: archive }) : await apiPost("/api/print-templates/", draft);
      setRows([...rows.filter(row => row.id !== result.id), result]); setDraft(result);
      onSelect(result.archived ? "" : String(result.id));
    } catch(e) { setError(e.message); } finally { setBusy(false); }
  }
  async function preview() {
    setBusy(true); setError("");
    try { await apiPostDownload("/api/print-templates/preview/", { name: draft.name || "Preview", kind, config: draft.config }, "template-preview.pdf"); }
    catch(e) { setError(e.message); } finally { setBusy(false); }
  }
  async function logo(file) {
    if (!file) return;
    if (file.type !== "image/png" || file.size > 200000) { setError(t("Use a PNG up to 200 KB.", "Use un PNG de hasta 200 KB.")); return; }
    const reader = new FileReader();
    reader.onload = () => update("logo", reader.result);
    reader.readAsDataURL(file);
  }
  return <div className="border rounded p-3 mb-3">
    <Form.Label htmlFor={`${id}-template`}>{t("Print template", "Plantilla de impresión")}</Form.Label>
    <Form.Select id={`${id}-template`} value={selected} onChange={e => { onSelect(e.target.value); const row = rows.find(r => String(r.id) === e.target.value); setDraft(row || { name: "", kind, config: defaults(kind) }); }}>
      <option value="">{t("Built-in layout", "Diseño integrado")}</option>{rows.filter(r => !r.archived).map(r => <option key={r.id} value={r.id}>{r.name} · v{r.revision}</option>)}
    </Form.Select>
    {error && <Alert variant="danger" className="mt-2">{error}</Alert>}
    {admin && <details className="mt-2"><summary>{t("Edit print templates", "Editar plantillas de impresión")}</summary>
      <Button type="button" size="sm" onClick={() => { setDraft({ name: "", kind, config: defaults(kind) }); }}>{t("New template", "Nueva plantilla")}</Button>
      {[ ["name", t("Template name", "Nombre de plantilla"), 80], ["title", t("Heading / lab name", "Encabezado / laboratorio"), 80], ["footer", t("Footer", "Pie de página"), 100] ].map(([key, label, limit]) => <div key={key}><Form.Label htmlFor={`${id}-${key}`}>{label}</Form.Label><Form.Control id={`${id}-${key}`} maxLength={limit} value={key === "name" ? draft.name : draft.config[key] || ""} onChange={e => key === "name" ? setDraft({ ...draft, name: e.target.value }) : update(key, e.target.value)} /></div>)}
      <Form.Label htmlFor={`${id}-paper`}>{t("Paper", "Papel")}</Form.Label><Form.Select id={`${id}-paper`} value={draft.config.page_size || "LETTER"} onChange={e => update("page_size", e.target.value)}><option>LETTER</option><option>A4</option></Form.Select>
      {kind === "LABEL" ? <>
        {[ ["columns", t("Columns", "Columnas"), [1, 2]], ["rows", t("Rows", "Filas"), [3, 4, 5]] ].map(([key, label, choices]) => <div key={key}><Form.Label htmlFor={`${id}-${key}`}>{label}</Form.Label><Form.Select id={`${id}-${key}`} value={draft.config[key]} onChange={e => update(key, Number(e.target.value))}>{choices.map(n => <option key={n}>{n}</option>)}</Form.Select></div>)}
        <Form.Check id={`${id}-project`} label={t("Show project", "Mostrar proyecto")} checked={draft.config.show_project ?? true} onChange={e => update("show_project", e.target.checked)} />
        <Form.Check id={`${id}-border`} label={t("Label borders", "Bordes de etiquetas")} checked={draft.config.border ?? true} onChange={e => update("border", e.target.checked)} />
      </> : <><Form.Label htmlFor={`${id}-orientation`}>{t("Orientation", "Orientación")}</Form.Label><Form.Select id={`${id}-orientation`} value={draft.config.orientation || "portrait"} onChange={e => update("orientation", e.target.value)}><option value="portrait">{t("Portrait", "Vertical")}</option><option value="landscape">{t("Landscape", "Horizontal")}</option></Form.Select><Form.Check id={`${id}-summary`} label={t("Show event count", "Mostrar cantidad de eventos")} checked={draft.config.show_summary ?? true} onChange={e => update("show_summary", e.target.checked)} /></>}
      <Form.Label htmlFor={`${id}-logo`}>{t("PNG logo (200 KB, 1000 pixels maximum)", "Logotipo PNG (máximo 200 KB y 1000 píxeles)")}</Form.Label><Form.Control id={`${id}-logo`} type="file" accept="image/png" onChange={e => logo(e.target.files[0])} />
      {draft.config.logo && <><img alt={t("Logo preview", "Vista previa del logotipo")} src={draft.config.logo} style={{ maxWidth: 120, maxHeight: 60 }} /><Button size="sm" type="button" onClick={() => update("logo", "")}>{t("Remove logo", "Quitar logotipo")}</Button></>}
      <div className="d-flex gap-2 mt-2"><Button type="button" disabled={busy} onClick={preview}>{t("Preview PDF (synthetic data)", "Vista previa PDF (datos ficticios)")}</Button><Button type="button" disabled={busy || !draft.name.trim()} onClick={() => save()}>{t("Save template", "Guardar plantilla")}</Button>{draft.id && <Button type="button" variant="outline-danger" disabled={busy} onClick={() => save(true)}>{t("Archive template", "Archivar plantilla")}</Button>}</div>
      <div className="small text-muted">{t("Changes apply to new confirmation previews. Preview and check actual print size before laboratory use.", "Los cambios se aplican a nuevas vistas de confirmación. Compruebe el PDF y el tamaño real de impresión antes de usarlo en el laboratorio.")}</div>
    </details>}
  </div>;
}
