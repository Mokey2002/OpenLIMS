import { useEffect, useRef, useState } from "react";
import { Alert, Badge, Button, Card, Col, Form, Row } from "react-bootstrap";
import { Link, useSearchParams } from "react-router-dom";
import { apiGet, apiGetAll, apiPost, apiPostDownload } from "../api";
import { canWrite } from "../authz";
import { useLanguage } from "../i18n";
import FeedbackForm, { FormField } from "../components/FeedbackForm";
import SampleFormFields from "../components/SampleFormFields";
import useFormFeedback from "../hooks/useFormFeedback";

export default function ReceiveSample() {
  const { language } = useLanguage();
  const t = (en, es) => language === "es" ? es : en;
  const feedback = useFormFeedback();
  const [query] = useSearchParams();
  const [me, setMe] = useState(null), [projects, setProjects] = useState([]), [forms, setForms] = useState([]);
  const [scan, setScan] = useState(() => query.get("barcode") || ""), [selected, setSelected] = useState(null), [scannedCode, setScannedCode] = useState("");
  const [project, setProject] = useState(""), [sampleType, setSampleType] = useState("GENERAL"), [values, setValues] = useState({});
  const [reason, setReason] = useState(""), [confirmation, setConfirmation] = useState(""), [size, setSize] = useState("100x50");
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [loading, setLoading] = useState(true), [loadError, setLoadError] = useState("");
  const scanInput = useRef(null), confirmInput = useRef(null), pending = useRef(false);
  useEffect(() => {
    let active = true;
    Promise.all([apiGet("/api/me/"), apiGetAll("/api/projects/"), apiGetAll("/api/sample-forms/?active=1")])
      .then(([user, projectRows, formRows]) => { if (active) { setMe(user); setProjects(projectRows.filter(p => p.members?.some(id => String(id) === String(user.id)))); setForms(formRows.filter(f => f.published && !f.archived)); } })
      .catch(e => { if (active) setLoadError(e.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (busy || loading) return;
    if (selected?.receipt && !selected.label_verified_at) {
      confirmInput.current?.focus(); confirmInput.current?.select();
    } else if (!selected || selected.label_verified_at) {
      scanInput.current?.focus(); scanInput.current?.select();
    }
  }, [selected, busy, loading]);

  async function run(action) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError("");
    try { await action(); }
    catch (e) { setError(e.message || t("Request failed. Scan again to check the saved state before retrying.", "Falló la solicitud. Escanea de nuevo para comprobar el estado guardado antes de reintentar.")); }
    finally { pending.current = false; setBusy(false); }
  }
  async function lookup(event) {
    event.preventDefault();
    const code = scan.trim();
    if (!code) return;
    await run(async () => {
      // Drop the old selection before lookup so an unavailable scan cannot leave another tube selected.
      setSelected(null); feedback.clear(); setConfirmation(""); setReason("");
      const result = await apiGet(`/api/samples/accession-lookup/?barcode=${encodeURIComponent(code)}`);
      setSelected(result); setScannedCode(code); setScan(""); setValues({}); setSampleType(forms.length ? "" : "GENERAL");
    });
  }
  async function register(event) {
    event.preventDefault();
    await run(async () => {
      try {
        const result = await apiPost("/api/samples/accession-register/", {
          barcode: selected.barcode, project: Number(receivingProject), sample_type: sampleType, form_values: values,
        });
        setSelected(result); setScannedCode(result.barcode);
      } catch (e) { feedback.reject(e); }
    });
  }
  async function receive(event) {
    event.preventDefault();
    await run(async () => setSelected(await apiPost(`/api/samples/${selected.sample.id}/receive/`, { barcode: scannedCode, reason })));
  }
  async function verify(event) {
    event.preventDefault();
    await run(async () => {
      const result = await apiPost(`/api/samples/${selected.sample.id}/verify-label/`, { barcode: confirmation.trim() });
      setSelected(result); setConfirmation(""); setScan(""); scanInput.current?.focus();
    });
  }
  const writable = canWrite(me) && (!selected?.sample || selected.sample.can_modify !== false);
  const terminal = ["ARCHIVED", "CANCELLED"].includes(selected?.sample?.status);
  const schema = forms.find(f => f.code === sampleType.trim().toUpperCase());
  const submission = selected?.submission;
  const receivingProject = submission ? String(submission.project) : project;
  const canRegister = Boolean(receivingProject) && projects.some(row => String(row.id) === receivingProject);
  return <div className="mx-auto" style={{ maxWidth: 1000 }} data-testid="receive-sample-page">
    <h1>{t("Receive sample", "Recibir muestra")}</h1>
    <p className="text-muted">{t("Scan a tube with a USB keyboard scanner and press Enter, or type its barcode. Each tube is registered once; physical receipt and label confirmation are separate recorded steps.", "Escanea un tubo con un lector USB de teclado y pulsa Intro, o escribe su código. Cada tubo se registra una vez; la recepción física y la confirmación de etiqueta se registran por separado.")}</p>
    {loadError && <Alert variant="danger">{loadError} {t("Reload this page before receiving samples.", "Recarga esta página antes de recibir muestras.")}</Alert>}
    {error && <Alert variant="danger" role="alert">{error}<div>{t("If a request was interrupted, scan the tube again to check its saved state. Do not register it under a different ID.", "Si se interrumpió una solicitud, vuelve a escanear el tubo para comprobar su estado guardado. No lo registres con otro identificador.")}</div></Alert>}
    <fieldset disabled={busy || loading || Boolean(loadError)}>
      <Card className="app-card mb-4"><Card.Body>
        <Form onSubmit={lookup}>
          <Form.Group controlId="accession-barcode" className="mb-3">
            <Form.Label>{t("Tube barcode", "Código del tubo")}</Form.Label>
            <Form.Control ref={scanInput} onFocus={event => event.target.select()} autoFocus required maxLength={128} autoComplete="off" value={scan} onChange={e => setScan(e.target.value)} />
            <Form.Text>{t("Existing codes open the sample here. New codes start registration. Scanning alone does not record receipt.", "Los códigos existentes abren la muestra aquí. Los nuevos inician el registro. Escanear no registra la recepción.")}</Form.Text>
          </Form.Group>
          <Button type="submit" disabled={!scan.trim()}>{busy ? t("Working…", "Procesando…") : t("Look up barcode", "Buscar código")}</Button>
        </Form>
      </Card.Body></Card>
      {submission && <Alert variant="info">
        <Link to={`/workflow-requests?request=${submission.request_public_id}`}>{submission.request_number}</Link>
        {" · "}{submission.reference}{" · "}{submission.project_name}
      </Alert>}
      {selected?.kind === "new" && <Card className="app-card mb-4"><Card.Body>
        <h2 className="h4">{t("1. Register new sample", "1. Registrar nueva muestra")}</h2>
        {!writable ? <Alert variant="info">{t("Ask an administrator or technician to register this tube. Your account is read-only.", "Pide a un administrador o técnico que registre el tubo. Tu cuenta es de lectura.")}</Alert> :
          <FeedbackForm feedback={feedback} onSubmit={register}>
            <FormField name="barcode" label={t("Barcode / sample ID", "Código / identificador de muestra")} hint={t("Up to 64 printable ASCII characters. The barcode becomes the unique sample ID.", "Hasta 64 caracteres ASCII imprimibles. El código será el identificador único de la muestra.")}><Form.Control value={selected.barcode} readOnly required maxLength={64} /></FormField>
            <Row><Col md={6}><FormField name="project" label={t("Receiving project", "Proyecto receptor")}><Form.Select required disabled={Boolean(submission)} value={receivingProject} onChange={e => setProject(e.target.value)}>
              <option value="">{t("Choose a project", "Elige un proyecto")}</option>{projects.map(p => <option key={p.id} value={p.id}>{p.code} — {p.name}</option>)}
            </Form.Select></FormField></Col>
            <Col md={6}><FormField name="sample_type" label={t("Sample type", "Tipo de muestra")}><Form.Select required value={sampleType} onChange={e => { setSampleType(e.target.value); setValues({}); }}>
              <option value="">{t("Choose a sample type", "Elige un tipo de muestra")}</option>
              {forms.length ? forms.map(f => <option key={f.id} value={f.code}>{f.code} — {f[language === "es" ? "name_es" : "name_en"] || f.code}</option>) : <option value="GENERAL">GENERAL</option>}
            </Form.Select></FormField>
            </Col></Row>
            <SampleFormFields fields={schema?.fields || []} values={values} onChange={setValues} />
            {!projects.length && <Alert variant="info">{t("No receiving projects are available. Open Projects or ask an administrator to add you as a member before registering a tube.", "No hay proyectos receptores disponibles. Abre Proyectos o pide a un administrador que te añada como miembro antes de registrar un tubo.")} <Link to="/projects">{t("Open projects", "Abrir proyectos")}</Link></Alert>}
            {submission && !canRegister && <Alert variant="info">{t("Join the submission’s project before registering this sample.", "Únete al proyecto de la solicitud antes de registrar la muestra.")}</Alert>}
            <Button type="submit" disabled={!canRegister || selected.barcode.length > 64}>{t("Register sample", "Registrar muestra")}</Button>
          </FeedbackForm>}
      </Card.Body></Card>}
      {selected?.sample && <>
        <Card className="app-card mb-4"><Card.Body>
          <div className="d-flex align-items-center gap-2 flex-wrap"><h2 className="h4 mb-0 text-break">{selected.sample.sample_id}</h2><Badge bg="secondary">{selected.sample.status}</Badge><Link to={`/samples/${selected.sample.id}`}>{t("Open sample record", "Abrir registro de muestra")}</Link></div>
          <p className="mt-2">{selected.sample.project_code || t("No project", "Sin proyecto")} · {selected.sample.sample_type}</p>
          {!writable && <Alert variant="info">{t("You can view this sample. Receipt, label generation and confirmation require permission to modify it.", "Puedes consultar la muestra. Recibir, generar etiquetas y confirmar requiere permiso para modificarla.")}</Alert>}
          {terminal && <Alert variant="warning">{t("This sample is archived or cancelled and cannot be received or label-confirmed.", "La muestra está archivada o cancelada y no se puede recibir ni confirmar su etiqueta.")}</Alert>}
          <h3 className="h5">{t("2. Record physical receipt", "2. Registrar recepción física")}</h3>
          {selected.receipt ? <Alert variant="success">{t("Received by", "Recibida por")} <strong>{selected.receipt.received_by}</strong> · {new Date(selected.receipt.received_at).toLocaleString()}<div>{t("Scanning again will not create another receipt.", "Volver a escanear no crea otra recepción.")}</div></Alert> : writable && !terminal &&
            <Form onSubmit={receive}><Form.Group controlId="accession-reason" className="mb-3"><Form.Label>{t("Receipt note / reason", "Nota / motivo de recepción")}</Form.Label>
              <Form.Control required minLength={10} maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} placeholder={t("For example: tube received intact at the lab bench", "Por ejemplo: tubo recibido intacto en el laboratorio")} />
            </Form.Group><Button type="submit" disabled={reason.trim().length < 10}>{t("Record receipt", "Registrar recepción")}</Button></Form>}
          <h3 className="h5 mt-4">{t("3. Print and attach the label", "3. Imprimir y colocar la etiqueta")}</h3>
          <p>{t("Download the Code 128 PDF, print at actual size (100%), and attach it to this tube. Existing labels may be used if their barcode identifies this sample.", "Descarga el PDF Code 128, imprime al tamaño real (100 %) y colócalo en el tubo. Puedes usar una etiqueta existente si su código identifica esta muestra.")}</p>
          {writable && <div className="d-flex gap-2 flex-wrap align-items-end">
            <Form.Group controlId="accession-label-size"><Form.Label>{t("Label size", "Tamaño de etiqueta")}</Form.Label><Form.Select value={size} onChange={e => setSize(e.target.value)}><option value="100x50">100 × 50 mm</option><option value="75x35">75 × 35 mm</option><option value="A4">A4</option></Form.Select></Form.Group>
            <Button variant="outline-dark" onClick={() => run(() => apiPostDownload(`/api/samples/${selected.sample.id}/accession-label/`, { size }, "sample-label.pdf"))}>{t("Download printable label", "Descargar etiqueta imprimible")}</Button>
          </div>}
          <h3 className="h5 mt-4">{t("4. Scan the attached label to confirm", "4. Escanear la etiqueta colocada para confirmar")}</h3>
          {selected.label_verified_at ? <Alert variant="success" role="status">{t("Label confirmed by", "Etiqueta confirmada por")} <strong>{selected.label_verified_by}</strong> · {new Date(selected.label_verified_at).toLocaleString()}<div>{t("Ready for the next tube. Scan it in the barcode field above.", "Listo para el siguiente tubo. Escanéalo en el campo de código de arriba.")}</div></Alert> : selected.receipt && writable && !terminal ?
            <Form onSubmit={verify}><Form.Group controlId="accession-confirm" className="mb-3"><Form.Label>{t("Scan attached label", "Escanear etiqueta colocada")}</Form.Label>
              <Form.Control ref={confirmInput} onFocus={event => event.target.select()} required maxLength={128} autoComplete="off" value={confirmation} onChange={e => setConfirmation(e.target.value)} />
            </Form.Group><Button type="submit" disabled={!confirmation.trim()}>{t("Confirm label", "Confirmar etiqueta")}</Button></Form> : <p className="text-muted">{t("Record physical receipt before confirming the attached label.", "Registra la recepción física antes de confirmar la etiqueta colocada.")}</p>}
        </Card.Body></Card>
      </>}
    </fieldset>
  </div>;
}
