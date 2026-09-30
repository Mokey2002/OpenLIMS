import { useState } from "react";
import { Alert, Badge, Button, Card, Form } from "react-bootstrap";
import { apiPost } from "../../api";
import { useLanguage } from "../../i18n";

function WorkflowStep({ experiment, step, blocked, editable, users, onSaved }) {
  const { language } = useLanguage();
  const t = (en, es) => language === "es" ? es : en;
  const [values, setValues] = useState(step.values);
  const [assignee, setAssignee] = useState(step.assignee || "");
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const finished = step.status === "COMPLETED";
  const writable = editable && !finished;
  async function submit(operation) {
    setBusy(true); setError(""); setMessage("");
    try {
      const saved = await apiPost(`/api/experiments/${experiment.id}/workflow-steps/${step.position}/`, {
        operation, expected_version: step.version, values, assignee: assignee ? Number(assignee) : null, note, confirmed,
      });
      if (operation !== "assign") setValues(saved.values);
      setMessage(operation === "assign" ? t("Assignment saved. Save progress to keep any entered measurements.", "Asignación guardada. Guarda el progreso para conservar las mediciones introducidas.") : t("Progress saved.", "Progreso guardado."));
      onSaved(saved, operation);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return <Card className="mb-3" data-testid="experiment-workflow-step"><Card.Body>
    <h5>{step.position}. {step.definition.name} <Badge bg={finished ? "success" : blocked ? "secondary" : "primary"}>{finished ? t("Completed", "Completado") : blocked ? t("Blocked", "Bloqueado") : t("Ready", "Listo")}</Badge></h5>
    <p className="text-muted">{step.definition.instructions}</p>
    <p><strong>{t("Completion criteria", "Criterios de finalización")}: </strong>{step.definition.completion_criteria || t("Fill required fields and confirm completion.", "Completa los campos obligatorios y confirma la finalización.")}</p>
    {blocked && <Alert variant="secondary">{t("Complete preceding steps to record this step.", "Completa los pasos anteriores para registrar este paso.")}</Alert>}
    {error && <Alert variant="danger">{error}</Alert>}
    {message && <Alert variant="success">{message}</Alert>}
    <div className="mb-3"><strong>{t("Responsible person", "Responsable")}: </strong>{step.assignee_username || t("Unassigned", "Sin asignar")}</div>
    {writable && <fieldset disabled={busy} className="d-flex gap-2 mb-3"><Form.Select aria-label={t("Responsible person", "Responsable")} value={assignee} onChange={e => setAssignee(e.target.value)}><option value="">{t("Choose a notebook editor", "Elige un editor de la bitácora")}</option>{users.map(user => <option key={user.id} value={user.id}>{user.username}</option>)}</Form.Select><Button variant="outline-secondary" disabled={!note.trim() || String(assignee) === String(step.assignee || "")} onClick={() => submit("assign")}>{t("Save assignment", "Guardar asignación")}</Button></fieldset>}
    <fieldset disabled={!writable || blocked || busy}>
      {step.definition.fields.map(field => <Form.Group className="mb-3" key={field.key} controlId={`workflow-${experiment.id}-${step.position}-${field.key}`}>
        <Form.Label>{field.label}{field.required ? " *" : ""}</Form.Label>
        {field.type === "BOOLEAN" ? <Form.Select value={values[field.key] == null ? "" : String(values[field.key])} onChange={e => setValues({ ...values, [field.key]: e.target.value === "" ? null : e.target.value === "true" })}><option value="">{t("Choose", "Elige")}</option><option value="true">{t("Yes", "Sí")}</option><option value="false">No</option></Form.Select> : <Form.Control type={field.type === "NUMBER" ? "number" : "text"} step="any" value={values[field.key] ?? ""} onChange={e => setValues({ ...values, [field.key]: field.type === "NUMBER" ? (e.target.value === "" ? null : Number(e.target.value)) : e.target.value })} />}
        <Form.Text>{[field.minimum != null && `${t("Minimum", "Mínimo")}: ${field.minimum}`, field.maximum != null && `${t("Maximum", "Máximo")}: ${field.maximum}`, field.equals !== undefined && `${t("Required value", "Valor exigido")}: ${String(field.equals)}`].filter(Boolean).join(" · ")}</Form.Text>
      </Form.Group>)}
    </fieldset>
    {finished ? <p>{t("Completed by", "Completado por")} {step.completed_by_username} · {new Date(step.completed_at).toLocaleString()}<br />{step.completion_note}</p> : writable && <fieldset disabled={busy}>
      <Form.Label htmlFor={`workflow-note-${step.position}`}>{t("Completion note / assignment reason", "Nota de finalización / motivo de asignación")}</Form.Label><Form.Control id={`workflow-note-${step.position}`} as="textarea" value={note} onChange={e => setNote(e.target.value)} />
      <Form.Check className="my-2" label={t("I confirm the work is finished and meets the completion criteria.", "Confirmo que el trabajo está terminado y cumple los criterios de finalización.")} checked={confirmed} disabled={blocked} onChange={e => setConfirmed(e.target.checked)} />
      <div className="d-flex gap-2"><Button variant="outline-dark" disabled={blocked} onClick={() => submit("save")}>{t("Save progress", "Guardar progreso")}</Button><Button disabled={blocked || !step.assignee || !confirmed || !note.trim()} onClick={() => submit("complete")}>{t("Complete step", "Completar paso")}</Button></div>
      {!step.assignee && <Form.Text>{t("Assign a responsible person before completing this step. Enter a reason above, then save the assignment.", "Asigna un responsable antes de finalizar. Escribe un motivo arriba y guarda la asignación.")}</Form.Text>}
    </fieldset>}
  </Card.Body></Card>;
}

export default function ExperimentWorkflow({ experiment, editable, users, onSaved }) {
  const { language } = useLanguage();
  const t = (en, es) => language === "es" ? es : en;
  const steps = experiment.workflow_steps || [];
  if (!steps.length) return <Alert variant="info">{t("This experiment has no workflow. Create an experiment from a template with workflow steps to use one.", "Este experimento no tiene flujo. Crea un experimento desde una plantilla con pasos de flujo para usar uno.")}</Alert>;
  const completed = steps.filter(step => step.status === "COMPLETED").length;
  return <div data-testid="experiment-workflow"><p className="fw-semibold">{completed} / {steps.length} {t("steps completed", "pasos completados")}</p>
    {completed === steps.length && <Alert variant="success">{t("Workflow finished. Use Complete in the experiment header to submit the experiment for review.", "Flujo terminado. Usa Completar en la cabecera del experimento para enviarlo a revisión.")}</Alert>}
    {steps.map((step, index) => <WorkflowStep key={`${experiment.id}-${step.position}`} experiment={experiment} step={step} blocked={steps.slice(0, index).some(row => row.status !== "COMPLETED")} editable={editable} users={users} onSaved={onSaved} />)}
  </div>;
}
