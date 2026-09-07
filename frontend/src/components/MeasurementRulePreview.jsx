import { useState } from "react";
import { Alert, Button, Form } from "react-bootstrap";
import { useLanguage } from "../i18n";
import { apiPost } from "../api";

export default function MeasurementRulePreview({ form, field, operator, value }) {
  const { language } = useLanguage();
  const t = (en, es) => language === "es" ? es : en;
  const [actual, setActual] = useState(""), [message, setMessage] = useState(""), [busy, setBusy] = useState(false);
  async function preview() {
    setBusy(true); setMessage("");
    try {
      const result = await apiPost("/api/pipeline-templates/preview-rule/", { form: Number(form), field, operator, value, actual });
      setMessage(result.matches ? t("Rule matches: this step would activate after its dependencies finish.", "La regla coincide: el paso se activaría al terminar sus dependencias.") : t("Rule does not match: this step would be skipped.", "La regla no coincide: este paso se omitiría."));
    } catch(e) { setMessage(e.message); } finally { setBusy(false); }
  }
  return <div className="border rounded p-2 mt-2">
    <Form.Control aria-label={t("Example measurement", "Medición de ejemplo")} value={actual} disabled={busy} onChange={e => { setActual(e.target.value); setMessage(""); }} placeholder={t("Example value (empty = missing)", "Valor de ejemplo (vacío = ausente)")} />
    <Button type="button" size="sm" className="mt-2" disabled={busy || !form || !field} onClick={preview}>{t("Test rule", "Probar regla")}</Button>
    {message && <Alert className="mt-2" variant="info">{message}</Alert>}
  </div>;
}
