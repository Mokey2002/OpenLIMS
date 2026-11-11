import { useState } from "react";
import { Alert, Button, Form } from "react-bootstrap";
import { apiPatch } from "../api";
import { useLanguage } from "../i18n";
import SampleFormFields from "./SampleFormFields";
import FeedbackForm, { FormField } from "./FeedbackForm";
import useFormFeedback from "../hooks/useFormFeedback";
export default function SampleValuesEditor({ sample, canEdit, onSaved }) {
  const feedback = useFormFeedback();
  const { language } = useLanguage();
  const t = (en, es) => language === "es" ? es : en;
  const [editing, setEditing] = useState(false), [values, setValues] = useState({});
  const [before, setBefore] = useState({}), [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function save(e) {
    e.preventDefault(); setBusy(true); setError("");
    try { const updated = await apiPatch(`/api/samples/${sample.id}/`, { form_values: values, form_values_before: before, reason }); setEditing(false); onSaved(updated); }
    catch (e) { feedback.reject(e); } finally { setBusy(false); }
  }
  if (!editing) return <><SampleFormFields fields={sample.form_schema.fields} values={sample.form_values} readOnly />{canEdit && <Button onClick={() => { setValues(structuredClone(sample.form_values)); setBefore(structuredClone(sample.form_values)); setReason(""); setError(""); setEditing(true); }}>{t("Edit sample fields", "Editar campos de la muestra")}</Button>}</>;
  return <FeedbackForm feedback={feedback} onSubmit={save}>{error && <Alert variant="danger">{error}</Alert>}<fieldset disabled={busy || !canEdit}>
    <SampleFormFields fields={sample.form_schema.fields} values={values} onChange={setValues} />
    <FormField name="reason" label={t("Reason for change (at least 10 characters)", "Motivo del cambio (mínimo 10 caracteres)")}><Form.Control required minLength={10} value={reason} onChange={e => setReason(e.target.value)} /></FormField>
    <Button type="submit" className="mt-2">{t("Save changes", "Guardar cambios")}</Button>{" "}
    <Button variant="outline-secondary" onClick={() => setEditing(false)}>{t("Cancel", "Cancelar")}</Button>
  </fieldset></FeedbackForm>;
}
