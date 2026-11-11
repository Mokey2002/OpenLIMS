import { Form } from "react-bootstrap";
import { useId } from "react";
import { useLanguage } from "../i18n";
import { FormField } from "./FeedbackForm";
export default function SampleFormFields({ fields = [], values = {}, onChange, readOnly = false, namePrefix = "form_values" }) {
  const { language } = useLanguage();
  const prefix = useId();
  const es = language === "es";
  const emit = next => { for (const field of fields) if (field.show_if && next[field.show_if.key] !== field.show_if.equals) delete next[field.key]; onChange(next); };
  return fields.filter(f => readOnly || !f.show_if || values[f.show_if.key] === f.show_if.equals).map((f, i) => readOnly ? <Form.Group key={i} className="mb-3" controlId={`${prefix}-sample-field-${i}`}>
    <Form.Label>{f[es ? "es" : "en"]}{f.unit ? ` (${f.unit})` : ""}{f.required ? " *" : ""}</Form.Label>
    <div>{values[f.key] == null ? "—" : typeof values[f.key] === "boolean" ? (values[f.key] ? (es ? "Sí" : "Yes") : "No") : String(values[f.key])}</div>
  </Form.Group> : <FormField key={f.key} name={`${namePrefix}.${f.key}`} label={`${f[es ? "es" : "en"]}${f.unit ? ` (${f.unit})` : ""}${f.required ? " *" : ""}`} hint={f.min != null || f.max != null ? `${es ? "Rango" : "Range"}: ${f.min ?? "—"} – ${f.max ?? "—"}` : undefined}>
    {f.type === "select" ? <Form.Select required={f.required} value={values[f.key] || ""} onChange={e => emit({ ...values, [f.key]: e.target.value })}>
        <option value="">{es ? "Seleccionar" : "Select"}</option>{(f.choices || []).map(c => <option key={c} value={c}>{c}</option>)}
      </Form.Select> : f.type === "boolean" ? <Form.Select required={f.required} value={values[f.key] == null ? "" : String(values[f.key])}
        onChange={e => emit({ ...values, [f.key]: e.target.value === "" ? null : e.target.value === "true" })}>
        <option value="">{es ? "Seleccionar" : "Select"}</option><option value="true">{es ? "Sí" : "Yes"}</option><option value="false">No</option>
      </Form.Select> : <Form.Control type={f.type === "number" ? "number" : f.type === "date" ? "date" : "text"} step="any"
        required={f.required} min={f.min} max={f.max} maxLength={4000} value={values[f.key] ?? ""}
        onChange={e => emit({ ...values, [f.key]: f.type === "number" && e.target.value !== "" ? Number(e.target.value) : e.target.value })} />}
  </FormField>);
}
