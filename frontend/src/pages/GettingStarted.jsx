import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Badge, Button, Card, Form, Spinner } from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGet, apiGetAll, apiPost } from "../api";
import { useLanguage } from "../i18n";

export default function GettingStarted() {
  const { language } = useLanguage();
  const es = language === "es";
  const t = (en, spanish) => es ? spanish : en;
  const [data, setData] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [selected, setSelected] = useState("");
  const [title, setTitle] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const starting = useRef(false);
  const load = useCallback(async () => {
    const current = ++generation.current;
    setError("");
    try {
      const status = await apiGet("/api/onboarding/");
      const choices = status.enabled && !status.experiment
        ? await apiGetAll("/api/experiment-templates/?for_onboarding=1", Infinity) : [];
      if (current !== generation.current) return;
      setData(status);
      setTemplates(choices);
      setSelected(previous => choices.some(choice => String(choice.id) === previous) ? previous : "");
    } catch {
      if (current === generation.current) setError("load");
    }
  }, []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
    const refresh = () => { if (!document.hidden && !starting.current) void load(); };
    window.addEventListener("focus", refresh);
    return () => { generation.current += 1; window.removeEventListener("focus", refresh); };
  }, [load]);

  async function start(event) {
    event.preventDefault();
    if (starting.current) return;
    starting.current = true;
    const current = ++generation.current;
    setBusy(true);
    setError("");
    try {
      const result = await apiPost("/api/onboarding/", { template: Number(selected), title: title.trim() });
      if (current === generation.current) setData(result);
    } catch {
      if (current === generation.current) setError("start");
    } finally {
      starting.current = false;
      if (current === generation.current) setBusy(false);
    }
  }

  const template = templates.find(choice => String(choice.id) === selected);
  const experiment = data?.experiment;
  const finished = experiment && ["COMPLETED", "REVIEWED", "LOCKED"].includes(experiment.status);
  return <div style={{ maxWidth: 900 }} className="mx-auto">
    <div className="d-flex justify-content-between align-items-start gap-3 mb-4">
      <div><h1>{t("Getting started", "Primeros pasos")}</h1>
        <p>{t("Start a real experiment using your lab’s workflow. You can leave and resume here at any time.", "Inicia un experimento real con el flujo de tu laboratorio. Puedes salir y continuar aquí cuando quieras.")}</p></div>
      <Button variant="outline-secondary" onClick={load} disabled={busy}>{t("Refresh", "Actualizar")}</Button>
    </div>
    {error && <Alert variant="danger">{error === "start"
      ? t("Could not confirm experiment creation. Refresh to check whether it was saved, or retry. Ask your lab manager to check the template and your edit access if this continues.", "No se pudo confirmar la creación. Actualiza para comprobar si se guardó o inténtalo de nuevo. Si continúa, pide al responsable revisar la plantilla y tus permisos.")
      : t("Could not load onboarding. Please refresh to retry.", "No se pudieron cargar los primeros pasos. Pulsa Actualizar para reintentar.")}</Alert>}
    {!data && !error && <Spinner animation="border" />}
    {data && !data.enabled && <Alert variant="info">{t("The notebook module is disabled. Ask your administrator to enable it before starting an experiment. You can still open My Work and the projects shared with you.", "El módulo de bitácora está desactivado. Pide al administrador activarlo antes de iniciar un experimento. Puedes consultar Mi trabajo y los proyectos compartidos contigo.")}</Alert>}
    {data?.enabled && !experiment && <Card className="mb-4"><Card.Body>
      <h2 className="h4">{t("1. Choose your lab workflow", "1. Elige el flujo de tu laboratorio")}</h2>
      {templates.length === 0 ? <Alert variant="info">{t("No workflows are available for you yet. Ask your lab manager to share a notebook with edit access and create an active template with workflow steps. Project membership alone may not grant edit access.", "Todavía no hay flujos disponibles. Pide al responsable compartir una bitácora con permiso de edición y crear una plantilla activa con pasos. Pertenecer al proyecto no siempre permite editar.")}</Alert> :
        <Form onSubmit={start}>
          <Form.Group className="mb-3" controlId="onboarding-template">
            <Form.Label>{t("Workflow template", "Plantilla del flujo")}</Form.Label>
            <Form.Select value={selected} onChange={event => setSelected(event.target.value)} required disabled={busy}>
              <option value="">{t("Choose a workflow…", "Elige un flujo…")}</option>
              {templates.map(item => <option key={item.id} value={item.id}>{item.notebook_name} — {item.name}</option>)}
            </Form.Select>
          </Form.Group>
          {template && <div className="mb-3">
            <p>{template.description}</p>
            <ol>{template.workflow_steps.map((step, index) => <li key={index} className="mb-2">
              <strong>{step.name}</strong>{step.instructions && <p className="mb-1">{step.instructions}</p>}
              {step.fields?.length > 0 && <div>{t("Fields:", "Campos:")} {step.fields.map(field => `${field.label}${field.required ? " *" : ""}`).join(", ")}</div>}
              {step.completion_criteria && <div>{t("Completion criteria:", "Criterios de finalización:")} {step.completion_criteria}</div>}
            </li>)}</ol>
            <small>{t("* Required field. Assigned people and validation rules are preserved from the template.", "* Campo obligatorio. Se conservan los responsables y las reglas de la plantilla.")}</small>
          </div>}
          <h2 className="h4">{t("2. Name your experiment", "2. Nombra tu experimento")}</h2>
          <Form.Group className="mb-3" controlId="onboarding-title"><Form.Label>{t("Experiment title", "Título del experimento")}</Form.Label>
            <Form.Control value={title} onChange={event => setTitle(event.target.value)} required maxLength={255} disabled={busy} />
          </Form.Group>
          <p>{t("This creates a real experiment in the selected notebook. It does not complete any steps or approve results.", "Se creará un experimento real en la bitácora seleccionada. No se completarán pasos ni se aprobarán resultados.")}</p>
          <Button type="submit" disabled={busy || !template || !title.trim()}>{busy ? t("Creating…", "Creando…") : t("Create my first experiment", "Crear mi primer experimento")}</Button>
        </Form>}
    </Card.Body></Card>}
    {experiment && <Card className="mb-4"><Card.Body>
      <h2 className="h4">{finished ? t("First experiment completed", "Primer experimento completado") : t("3. Run your first experiment", "3. Realiza tu primer experimento")}</h2>
      <p><strong>{experiment.title}</strong> <Badge bg={finished ? "success" : "secondary"}>{experiment.status}</Badge></p>
      <p>{experiment.steps.filter(step => step.status === "COMPLETED").length} / {experiment.steps.length} {t("steps complete", "pasos completos")}</p>
      <ol>{experiment.steps.map(step => <li key={step.position}>{step.name} — {step.status === "COMPLETED" ? t("Complete", "Completo") : t("Pending", "Pendiente")}</li>)}</ol>
      {!experiment.can_write && <Alert variant="info">{t("You currently have read-only access. Ask the notebook owner for edit access to continue.", "Actualmente tienes acceso de lectura. Pide al propietario permiso de edición para continuar.")}</Alert>}
      {!finished && <ol>
        <li>{t("Open the experiment and read the instructions for the first pending step.", "Abre el experimento y lee las instrucciones del primer paso pendiente.")}</li>
        <li>{t("Check the responsible person for each step. If unassigned, select a person with edit access and save the assignment with a reason before completing the step.", "Revisa el responsable de cada paso. Si no hay uno, elige a alguien con permiso de edición y guarda la asignación con un motivo antes de completar el paso.")}</li>
        <li>{t("Add your sample under Links, save a revision, and attach any supporting files.", "Agrega tu muestra en Links, guarda una revisión y adjunta los archivos de apoyo.")}</li>
        <li>{t("Enter the required results, save, then complete each workflow step in order. Saving is different from completing a step.", "Introduce los resultados obligatorios, guarda y completa cada paso en orden. Guardar no equivale a completar un paso.")}</li>
        <li>{t("When all steps are complete, use the experiment status controls to complete it. Review or sign-off is a separate action for an authorized reviewer.", "Al terminar todos los pasos, usa los controles de estado para completar el experimento. La revisión o firma es una acción separada de un revisor autorizado.")}</li>
      </ol>}
      <Button as={Link} to={`/notebook?experiment=${experiment.public_id}`}>{t("Open experiment", "Abrir experimento")}</Button>
    </Card.Body></Card>}
    <p><Link to="/">{t("Back to My Work", "Volver a Mi trabajo")}</Link> · <Link to="/notifications">{t("Account notifications", "Notificaciones de cuenta")}</Link></p>
  </div>;
}
