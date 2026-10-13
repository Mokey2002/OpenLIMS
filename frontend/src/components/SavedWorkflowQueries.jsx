import { useEffect, useState } from "react";
import { apiDelete, apiGet, apiPost } from "../api";

const endpoint = "/api/assistant/saved-queries/";
const changedEvent = "openlims:saved-workflow-queries";

export default function SavedWorkflowQueries({ draft, onLoad, disabled, valid }) {
  const [items, setItems] = useState([]);
  const [name, setName] = useState("");
  const [selected, setSelected] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const es = draft.language === "es";
  const t = (en, spanish) => es ? spanish : en;
  const item = items.find(value => String(value.id) === selected);

  useEffect(() => {
    let controller;
    const refresh = async () => {
      controller?.abort();
      controller = new AbortController();
      const signal = controller.signal;
      try {
        const result = await apiGet(endpoint, { signal });
        if (!signal.aborted) { setItems(Array.isArray(result) ? result : []); setError(""); }
      } catch { if (!signal.aborted) setError("Could not load saved questions. / No se pudieron cargar las consultas."); }
    };
    refresh();
    window.addEventListener(changedEvent, refresh);
    return () => { controller?.abort(); window.removeEventListener(changedEvent, refresh); };
  }, []);

  async function save() {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await apiPost(endpoint, { name: name.trim(), query: draft });
      setSelected(String(result.id)); setName("");
      setNotice(t("Question saved to your account.", "Consulta guardada en tu cuenta."));
      window.dispatchEvent(new Event(changedEvent));
    } catch { setError(t("Could not save. Check project access, assignee and a unique name (20 questions maximum).", "No se pudo guardar. Revisa permisos, responsable y nombre único (máximo 20 consultas).")); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!item) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await apiDelete(`${endpoint}${item.id}/`);
      setSelected(""); setConfirmDelete(false);
      setNotice(t("Saved question deleted.", "Consulta guardada eliminada."));
      window.dispatchEvent(new Event(changedEvent));
    } catch { setError(t("Could not delete. Refresh the list and try again.", "No se pudo eliminar. Actualiza la lista e inténtalo otra vez.")); }
    finally { setBusy(false); }
  }

  return (
    <fieldset disabled={disabled || busy} className="border rounded p-2 mb-2 saved-workflow-queries">
      <legend className="float-none w-auto fs-6 px-1">{t("My saved questions", "Mis consultas guardadas")}</legend>
      <p className="small">{t("Private to your account. Loading fills the builder; Run question checks current access and records. Save settings only, never results.", "Privadas para tu cuenta. Cargar completa el constructor; Ejecutar consulta verifica permisos y registros actuales. Solo se guardan ajustes, nunca resultados.")}</p>
      <label className="d-block">{t("Saved question", "Consulta guardada")}
        <select className="form-select form-select-sm" value={selected} onChange={e => { setSelected(e.target.value); setConfirmDelete(false); }}>
          <option value="">{t("Choose a question", "Elige una consulta")}</option>
          {items.map(value => <option key={value.id} value={String(value.id)}>{value.name}</option>)}
        </select>
      </label>
      <div className="d-flex gap-1 my-2 flex-wrap">
        <button type="button" className="btn btn-sm btn-outline-dark" disabled={!item} onClick={() => { onLoad({ ...item.query, filters: [...item.query.filters] }); setNotice(t("Loaded for review. Run when ready.", "Cargada para revisión. Ejecuta cuando estés listo.")); }}>{t("Load saved question", "Cargar consulta guardada")}</button>
        <button type="button" className="btn btn-sm btn-outline-secondary" onClick={() => window.dispatchEvent(new Event(changedEvent))}>{t("Refresh saved questions", "Actualizar consultas guardadas")}</button>
        <button type="button" className="btn btn-sm btn-outline-danger" disabled={!item} onClick={() => setConfirmDelete(true)}>{t("Delete saved question", "Eliminar consulta guardada")}</button>
      </div>
      {confirmDelete && item && <div className="small mb-2">{t("Delete", "Eliminar")} “{item.name}”? <button type="button" className="btn btn-sm btn-danger" onClick={remove}>{t("Confirm deletion", "Confirmar eliminación")}</button> <button type="button" className="btn btn-sm btn-link" onClick={() => setConfirmDelete(false)}>{t("Cancel", "Cancelar")}</button></div>}
      <label className="d-block">{t("Name this question", "Nombre de esta consulta")}<input className="form-control form-control-sm" value={name} maxLength={80} onChange={e => setName(e.target.value)} /></label>
      <button type="button" className="btn btn-sm btn-outline-dark mt-2" disabled={!valid || !name.trim() || items.length >= 20} onClick={save}>{t("Save builder settings", "Guardar ajustes del constructor")}</button>
      <span className="small ms-2">{items.length}/20</span>
      {error && <p role="alert" className="text-danger small mt-2 mb-0">{error}</p>}
      {notice && <p role="status" className="small mt-2 mb-0">{notice}</p>}
    </fieldset>
  );
}
