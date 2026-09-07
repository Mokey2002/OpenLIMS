import { useEffect, useId, useState } from "react";
import { Alert, Button, Form } from "react-bootstrap";
import { apiGet, apiGetAll, apiPost } from "../api";
import { isAdmin } from "../authz";
import { useLanguage } from "../i18n";
import { defaultWorkspace } from "../workspaceDefaults";

export default function WorkspacePreferences({ value, onChange }) {
  const { language } = useLanguage();
  const t = (en, es) => language === "es" ? es : en;
  const id = useId();
  const [selectedId, setSelectedId] = useState("");
  const [views, setViews] = useState([]), [me, setMe] = useState(null), [name, setName] = useState(""), [role, setRole] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    Promise.all([apiGetAll("/api/workspace-views/"), apiGet("/api/me/")]).then(([rows, user]) => {
      if (!active) return;
      setViews(rows); setMe(user);
      const stored = localStorage.getItem(`openlims-view-${user.id}`);
      const chosen = rows.find(v => String(v.id) === stored);
      const shared = rows.find(v => !v.owner && v.role === (isAdmin(user) ? "admin" : user.roles?.[0]));
      const selected = stored === "default" ? null : chosen || shared;
      if (selected) { onChange({ ...defaultWorkspace, ...selected.config }); setSelectedId(String(selected.id)); }
    }).catch(e => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [onChange]);
  const labels = { summary: t("Summary cards", "Tarjetas de resumen"), assigned: t("Assigned work", "Trabajo asignado"), overdue: t("Overdue", "Vencidos"), attention: t("Attention", "Atención"), name: t("Work", "Trabajo"), sample: t("Sample", "Muestra"), status: t("Status", "Estado"), qc: "QC", due: t("Due", "Vencimiento") };
  function toggle(key, item) {
    const list = value[key];
    onChange({ ...value, [key]: list.includes(item) ? list.filter(x => x !== item) : [...list, item] });
  }
  async function save() {
    setBusy(true); setError("");
    try {
      const result = await apiPost("/api/workspace-views/", { name, role, config: value });
      setViews([...views, result]); setName("");
      setSelectedId(String(result.id));
      if (!role && me) localStorage.setItem(`openlims-view-${me.id}`, result.id);
    } catch(e) { setError(e.message); } finally { setBusy(false); }
  }
  return <details className="border rounded p-3 mb-3">
    <summary>{t("Customize My Work", "Personalizar Mi trabajo")}</summary>
    {error && <Alert variant="danger">{error}</Alert>}
    <Form.Label htmlFor={`${id}-view`}>{t("Saved view", "Vista guardada")}</Form.Label>
    <Form.Select id={`${id}-view`} value={selectedId} onChange={e => {
      setSelectedId(e.target.value);
      const selected = views.find(v => String(v.id) === e.target.value);
      onChange({ ...defaultWorkspace, ...selected?.config });
      if (me) localStorage.setItem(`openlims-view-${me.id}`, selected?.id || "default");
    }}><option value="">{t("Default layout", "Diseño predeterminado")}</option>{views.map(v => <option key={v.id} value={v.id}>{v.name}{v.role ? ` (${v.role})` : ""}</option>)}</Form.Select>
    <fieldset className="mt-2"><legend className="fs-6">{t("Visible widgets", "Widgets visibles")}</legend>{defaultWorkspace.widgets.map(key => <Form.Check inline id={`${id}-widget-${key}`} key={key} label={labels[key]} checked={value.widgets.includes(key)} disabled={value.widgets.length === 1 && value.widgets.includes(key)} onChange={() => toggle("widgets", key)} />)}</fieldset>
    <fieldset><legend className="fs-6">{t("Work table columns (selection order)", "Columnas de trabajo (orden de selección)")}</legend>{defaultWorkspace.columns.map(key => <Form.Check inline id={`${id}-column-${key}`} key={key} label={labels[key]} checked={value.columns.includes(key)} disabled={value.columns.length === 1 && value.columns.includes(key)} onChange={() => toggle("columns", key)} />)}</fieldset>
    <Form.Label htmlFor={`${id}-query`}>{t("Filter assigned work", "Filtrar trabajo asignado")}</Form.Label><Form.Control id={`${id}-query`} maxLength={80} value={value.query} onChange={e => onChange({ ...value, query: e.target.value })} />
    <Form.Label htmlFor={`${id}-status`}>{t("Work status", "Estado del trabajo")}</Form.Label><Form.Select id={`${id}-status`} value={value.status} onChange={e => onChange({ ...value, status: e.target.value })}><option value="">{t("All", "Todos")}</option><option>PENDING</option><option>IN_PROGRESS</option></Form.Select>
    <Form.Label htmlFor={`${id}-name`}>{t("New view name", "Nombre de la nueva vista")}</Form.Label><Form.Control id={`${id}-name`} maxLength={80} value={name} onChange={e => setName(e.target.value)} />
    {isAdmin(me) && <><Form.Label htmlFor={`${id}-role`}>{t("Share with role", "Compartir con rol")}</Form.Label><Form.Select id={`${id}-role`} value={role} onChange={e => setRole(e.target.value)}><option value="">{t("Personal", "Personal")}</option>{["admin", "tech", "qc_reviewer", "viewer"].map(r => <option key={r}>{r}</option>)}</Form.Select></>}
    <Button className="mt-2" disabled={busy || !name.trim()} onClick={save}>{t("Save new view", "Guardar nueva vista")}</Button>
    <div className="text-muted small">{t("Display only: permissions and underlying records do not change. Filters apply to the assigned work shown here.", "Solo presentación: los permisos y registros no cambian. Los filtros se aplican al trabajo asignado mostrado aquí.")}</div>
  </details>;
}
