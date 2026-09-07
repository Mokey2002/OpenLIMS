import { Form } from "react-bootstrap";
import { useId } from "react";
import { useLanguage } from "../i18n";

export default function WorkflowStepActions({ value = {}, users, onChange }) {
  const { language } = useLanguage();
  const notifyId = useId();
  const t = (en, es) => language === "es" ? es : en;
  const update = (changes) => onChange({ ...value, ...changes });
  const missing = [value.assigned_to, ...(value.notify_users || [])].filter(id => id && !users.some(u => u.id === id));
  return <fieldset className="border rounded p-3 mt-2">
    <legend className="fs-6">{t("When this step activates", "Cuando se activa este paso")}</legend>
    <Form.Label>
      {t("Assign work to", "Asignar trabajo a")}
      <Form.Select value={value.assigned_to || ""} onChange={e => update({ assigned_to: e.target.value ? Number(e.target.value) : null, notify_assignee: e.target.value ? !!value.notify_assignee : false })}>
        <option value="">{t("Leave unassigned", "Dejar sin asignar")}</option>
        {users.filter(u => u.can_assign).map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
        {value.assigned_to && !users.some(u => u.id === value.assigned_to && u.can_assign) && <option value={value.assigned_to}>{t("Unavailable user", "Usuario no disponible")} #{value.assigned_to}</option>}
      </Form.Select>
    </Form.Label>
    <Form.Check id={notifyId} label={t("Notify the assignee in the app", "Notificar a la persona asignada en la aplicación")} checked={!!value.notify_assignee} disabled={!value.assigned_to} onChange={e => update({ notify_assignee: e.target.checked })} />
    <Form.Label className="mt-2 d-block">
      {t("Additional in-app recipients", "Destinatarios adicionales en la aplicación")}
      <Form.Select multiple value={(value.notify_users || []).map(String)} onChange={e => update({ notify_users: Array.from(e.target.selectedOptions, o => Number(o.value)) })}>
        {users.map(u => <option key={u.id} value={u.id}>{u.username}</option>)}
        {[...new Set(missing)].map(id => <option key={id} value={id}>{t("Unavailable user", "Usuario no disponible")} #{id}</option>)}
      </Form.Select>
    </Form.Label>
    <Form.Text>{t("Actions run only when the step activates. Access is checked again then. Ineligible assignments remain unassigned; unavailable recipients are skipped and audited. Retries create a new notification. Hold Ctrl or Command to select multiple recipients.", "Las acciones se ejecutan al activar el paso y se vuelve a comprobar el acceso. Las asignaciones no permitidas quedan sin asignar; los destinatarios no disponibles se omiten y se auditan. Cada reintento crea una nueva notificación. Mantenga Ctrl o Command para seleccionar varios destinatarios.")}</Form.Text>
  </fieldset>;
}
