import { useState } from "react";
import { Alert, Button, Card, Form } from "react-bootstrap";
import { apiPost } from "../api";
import { useLanguage } from "../i18n";
export default function ConfiguredIntake({ projects, onImported }) {
  const { language } = useLanguage();
  const t = (en, es) => language === "es" ? es : en;
  const [csv, setCsv] = useState(""), [project, setProject] = useState("");
  const [preview, setPreview] = useState(null), [busy, setBusy] = useState(false), [message, setMessage] = useState("");
  async function submit(confirm = false) {
    setBusy(true); setMessage("");
    try {
      const result = await apiPost("/api/samples/import-configured/", { csv, project: project ? Number(project) : null, confirm, preview_token: preview?.preview_token });
      if (confirm) { setMessage(t(`Created ${result.created} samples.`, `Se crearon ${result.created} muestras.`)); setPreview(null); setCsv(""); onImported(); } else setPreview(result);
    } catch(e) { setMessage(e.message); setPreview(null); } finally { setBusy(false); }
  }
  return <Card className="mb-4"><Card.Body><h5>{t("Import configured samples", "Importar muestras configuradas")}</h5>
    <p>{t("New samples only. CSV columns: sample_id, sample_type, form_values (JSON). Exported versions must match the current form. Maximum 500 rows. Project selection applies to every row.", "Solo muestras nuevas. Columnas CSV: sample_id, sample_type, form_values (JSON). La versión exportada debe coincidir con la actual. Máximo 500 filas. El proyecto se aplica a todas las filas.")}</p>
    {message && <Alert variant="info">{message}</Alert>}
    <fieldset disabled={busy}><Form.Control aria-label="CSV" type="file" accept=".csv,text/csv" onChange={async e => { setPreview(null); setCsv(""); const file = e.target.files[0]; if (file?.size > 1000000) { setMessage(t("Maximum 1 MB.", "Máximo 1 MB.")); return; } if (file) setCsv(await file.text()); }} />
      <Form.Select aria-label={t("Import project", "Proyecto de importación")} value={project} onChange={e => { setProject(e.target.value); setPreview(null); }}><option value="">{t("No project", "Sin proyecto")}</option>{projects.map(p => <option key={p.id} value={p.id}>{p.code} — {p.name}</option>)}</Form.Select>
      <Button className="mt-2" disabled={!csv} onClick={() => submit(false)}>{t("Validate and preview", "Validar y previsualizar")}</Button>
      {preview && <Button className="mt-2 ms-2" onClick={() => submit(true)}>{t(`Confirm ${preview.count} new samples`, `Confirmar ${preview.count} muestras nuevas`)}</Button>}
    </fieldset></Card.Body></Card>;
}
