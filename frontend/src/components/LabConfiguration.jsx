import { useEffect, useState } from "react";
import { Alert, Button, Card, Form, Table } from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGet, apiPatch } from "../api";
import { useLanguage } from "../i18n";

export default function LabConfiguration({ canEdit, notebookEnabled }) {
  const { language } = useLanguage();
  const t = (en, es) => language === "es" ? es : en;
  const [policy, setPolicy] = useState(null);
  const [draft, setDraft] = useState(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    let active = true;
    apiGet("/api/sample-status-policy/").then(data => {
      if (active) { setPolicy(data); setDraft(data.transitions); }
    }).catch(() => { if (active) setError("load"); });
    return () => { active = false; };
  }, []);
  async function reload() {
    if (dirty && !window.confirm(t("Discard unsaved status changes and reload?", "¿Descartar los cambios de estado sin guardar y recargar?"))) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const data = await apiGet("/api/sample-status-policy/");
      setPolicy(data); setDraft(data.transitions); setReason(""); setDirty(false);
    } catch { setError("load"); } finally { setBusy(false); }
  }
  async function save(event) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      const data = await apiPatch("/api/sample-status-policy/", { expected_revision: policy.revision, transitions: draft, reason: reason.trim() });
      setPolicy(data); setDraft(data.transitions); setReason(""); setDirty(false); setMessage("saved");
    } catch { setError("save"); } finally { setBusy(false); }
  }
  function toggle(source, target, checked) {
    setDraft(current => ({ ...current, [source]: checked ? [...current[source], target] : current[source].filter(value => value !== target) }));
    setDirty(true); setMessage("");
  }
  const valid = draft && Object.entries(draft).every(([source, targets]) => source === "ARCHIVED" || targets.length > 0);
  return <section aria-label={t("Lab configuration", "Configuración del laboratorio")} className="mb-4">
    <Card className="app-card mb-4"><Card.Body>
      <h2 className="h4">{t("Configure your lab without code", "Configura tu laboratorio sin código")}</h2>
      <p>{t("Use these editors for fields, templates and access. Each editor enforces its own permissions; changing a workflow never grants access to data.", "Usa estos editores para campos, plantillas y acceso. Cada editor valida los permisos; cambiar un flujo nunca concede acceso a datos.")}</p>
      <ul>
        {canEdit && <li><a href="#sample-form-builder">{t("Sample fields and forms", "Campos y formularios de muestras")}</a> — {t("Build, preview and publish versioned forms below.", "Crea, previsualiza y publica formularios versionados más abajo.")}</li>}
        <li><Link to="/workflow-designer">{t("Analysis fields and pipeline templates", "Campos de análisis y plantillas de pipelines")}</Link> — {t("Required results, procedures and step dependencies; administrator editing.", "Resultados obligatorios, procedimientos y dependencias; edición de administrador.")}</li>
        {notebookEnabled && <li><Link to="/notebook">{t("Experiment templates and notebook permissions", "Plantillas de experimentos y permisos de bitácora")}</Link> — {t("Template editors need notebook edit access; owners/admins manage sharing.", "Los editores necesitan permiso de edición; propietarios/administradores gestionan el acceso.")}</li>}
        <li><Link to="/projects">{t("Project membership", "Miembros del proyecto")}</Link> — {t("Manage the project team using your authorized role.", "Gestiona el equipo con tu rol autorizado.")}</li>
        {canEdit && <li><Link to="/users">{t("Account roles and invitations", "Roles de cuentas e invitaciones")}</Link> — {t("Administrator only. Use the least access each person needs.", "Solo administradores. Concede únicamente el acceso necesario.")}</li>}
        <li><Link to="/labels">{t("Label templates", "Plantillas de etiquetas")}</Link> · <Link to="/reports">{t("Report templates", "Plantillas de informes")}</Link></li>
      </ul>
    </Card.Body></Card>
    <Card className="app-card"><Card.Body>
      <h2 className="h4">{t("Sample status transitions", "Transiciones de estado de muestras")}</h2>
      <p>{t("Choose which supported transitions your lab allows. Status codes stay stable, QC cannot be skipped, and each non-final status must keep a way forward. Applies to future manual status changes, including existing samples; it does not rewrite records or change automatic pipeline/custody actions.", "Elige las transiciones admitidas. Los códigos de estado se mantienen, no se puede omitir QC y cada estado no final conserva una salida. Se aplica a futuros cambios manuales, incluso de muestras existentes; no modifica registros ni acciones automáticas de pipelines/custodia.")}</p>
      {error && <Alert variant="danger">{error === "load" ? t("Could not load the status policy. Retry with Reload policy.", "No se pudo cargar la política. Reintenta con Recargar política.") : t("Not saved. The policy may have changed or your permissions may have changed. Your edits are preserved. Reload the latest policy, review your changes and try again.", "No se guardó. La política o tus permisos pueden haber cambiado. Se conservan tus cambios. Recarga la política, revisa los cambios e inténtalo otra vez.")}</Alert>}
      {message && <Alert variant="success">{t("Status policy saved and audited.", "Política de estados guardada y auditada.")}</Alert>}
      <Button variant="outline-secondary" size="sm" onClick={reload} disabled={busy}>{t("Reload policy", "Recargar política")}</Button>
      {policy && draft && <Form onSubmit={save} className="mt-3">
        <p>{t("Revision", "Revisión")} {policy.revision}{dirty ? t(" · Unsaved changes", " · Cambios sin guardar") : ""}</p>
        <Table responsive><thead><tr><th>{t("From", "Desde")}</th><th>{t("Allowed destinations", "Destinos permitidos")}</th></tr></thead>
          <tbody>{Object.entries(policy.supported_transitions).map(([source, targets]) => <tr key={source}><td>{source}</td><td>
            {targets.length === 0 ? t("Final status", "Estado final") : targets.map(target => <Form.Check key={target} id={`transition-${source}-${target}`} label={`${source} → ${target}`} checked={draft[source].includes(target)} disabled={!canEdit || busy} onChange={event => toggle(source, target, event.target.checked)} />)}
          </td></tr>)}</tbody></Table>
        {!valid && <Alert variant="warning">{t("Keep at least one destination for every non-final status.", "Conserva al menos un destino para cada estado no final.")}</Alert>}
        {canEdit ? <>
          <Form.Group controlId="status-policy-reason" className="mb-3"><Form.Label>{t("Reason for policy change", "Motivo del cambio de política")}</Form.Label>
            <Form.Control as="textarea" value={reason} minLength={10} maxLength={2000} required disabled={busy} onChange={event => setReason(event.target.value)} />
          </Form.Group>
          <Button type="submit" disabled={busy || !dirty || !valid || reason.trim().length < 10}>{t("Save status policy", "Guardar política de estados")}</Button>{" "}
          <Button variant="outline-secondary" disabled={busy} onClick={() => { setDraft(policy.supported_transitions); setDirty(true); setMessage(""); }}>{t("Use default transitions", "Usar transiciones predeterminadas")}</Button>
          <p className="small text-muted mt-2">{t("Defaults are only applied after saving with a reason. General settings reset does not reset this policy.", "Los valores predeterminados solo se aplican al guardar con un motivo. Restablecer los ajustes generales no cambia esta política.")}</p>
        </> : <p>{t("Read only. An administrator must save configuration changes.", "Solo lectura. Un administrador debe guardar los cambios.")}</p>}
      </Form>}
    </Card.Body></Card>
  </section>;
}
