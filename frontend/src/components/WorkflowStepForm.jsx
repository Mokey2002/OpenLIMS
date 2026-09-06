import { useState } from "react";
import { Alert, Button, Form } from "react-bootstrap";
import { useLanguage } from "../i18n";
import { apiPost } from "../api";
import SampleFormFields from "./SampleFormFields";

export default function WorkflowStepForm({ run, step, canEdit, onSaved }) {
  const { language } = useLanguage();
  const t = (en, es) => language === "es" ? es : en;
  const [editing, setEditing] = useState(false), [values, setValues] = useState({}), [before, setBefore] = useState({});
  const [reason, setReason] = useState(""), [error, setError] = useState(""), [busy, setBusy] = useState(false);
  if (!step.form_schema?.version) return null;
  const editable = canEdit && ["READY", "IN_PROGRESS"].includes(step.status) && ["PENDING", "IN_PROGRESS"].includes(step.work_item_status);
  async function save(e) {
    e.preventDefault(); setBusy(true); setError("");
    try { await apiPost(`/api/pipeline-runs/${run.id}/steps/${step.id}/form/`, { values, before, reason, work_item: step.work_item }); setEditing(false); await onSaved(); }
    catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return <div className="border rounded p-2 mt-2">
    <strong>{step.form_schema[language === "es" ? "name_es" : "name_en"]} · #{step.form_schema.version}</strong>
    {Object.keys(step.form_errors || {}).length > 0 && <Alert variant="warning" className="mt-2">{t("Complete the required measurements before finishing this step.", "Complete las mediciones obligatorias antes de finalizar este paso.")}<pre className="text-wrap">{JSON.stringify(step.form_errors, null, 2)}</pre></Alert>}
    {error && <Alert variant="danger">{error}</Alert>}
    {editing ? <Form onSubmit={save}><fieldset disabled={busy || !editable}>
      <SampleFormFields fields={step.form_schema.fields} values={values} onChange={setValues} />
      <Form.Label htmlFor={`step-reason-${step.id}`}>{t("Reason (10 characters minimum)", "Motivo (mínimo 10 caracteres)")}</Form.Label>
      <Form.Control id={`step-reason-${step.id}`} required minLength={10} value={reason} onChange={e => setReason(e.target.value)} />
      <Button type="submit" size="sm" className="mt-2">{t("Save measurements", "Guardar mediciones")}</Button>{" "}
      <Button size="sm" variant="outline-secondary" onClick={() => setEditing(false)}>{t("Cancel", "Cancelar")}</Button>
    </fieldset></Form> : <><SampleFormFields fields={step.form_schema.fields} values={step.form_values} readOnly />{editable && <Button size="sm" onClick={() => { setValues(structuredClone(step.form_values)); setBefore(structuredClone(step.form_values)); setError(""); setReason(""); setEditing(true); }}>{t("Record measurements", "Registrar mediciones")}</Button>}</>}
  </div>;
}
