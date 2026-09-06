import { Form } from "react-bootstrap";
import { useLanguage } from "../i18n";
export default function SampleFormFields({ fields = [], values = {}, onChange, readOnly = false }) {
  const { language } = useLanguage();
  const es = language === "es";
  const emit = next => { for (const field of fields) if (field.show_if && next[field.show_if.key] !== field.show_if.equals) delete next[field.key]; onChange(next); };
  return fields.filter(f => readOnly || !f.show_if || values[f.show_if.key] === f.show_if.equals).map((f, i) => <Form.Group key={i} className="mb-3" controlId={`sample-field-${i}`}>
    <Form.Label>{f[es ? "es" : "en"]}{f.unit ? ` (${f.unit})` : ""}{f.required ? " *" : ""}</Form.Label>
    {readOnly ? <div>{values[f.key] == null ? "—" : typeof values[f.key] === "boolean" ? (values[f.key] ? (es ? "Sí" : "Yes") : "No") : String(values[f.key])}</div>
      : f.type === "select" ? <Form.Select required={f.required} value={values[f.key] || ""} onChange={e => emit({ ...values, [f.key]: e.target.value })}>
        <option value="">{es ? "Seleccionar" : "Select"}</option>{(f.choices || []).map(c => <option key={c} value={c}>{c}</option>)}
      </Form.Select> : f.type === "boolean" ? <Form.Select required={f.required} value={values[f.key] == null ? "" : String(values[f.key])}
        onChange={e => emit({ ...values, [f.key]: e.target.value === "" ? null : e.target.value === "true" })}>
        <option value="">{es ? "Seleccionar" : "Select"}</option><option value="true">{es ? "Sí" : "Yes"}</option><option value="false">No</option>
      </Form.Select> : <Form.Control type={f.type === "number" ? "number" : f.type === "date" ? "date" : "text"} step="any"
        required={f.required} min={f.min} max={f.max} maxLength={4000} value={values[f.key] ?? ""}
        onChange={e => emit({ ...values, [f.key]: f.type === "number" && e.target.value !== "" ? Number(e.target.value) : e.target.value })} />}
  </Form.Group>);
}
