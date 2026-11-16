import { Badge, Card } from "react-bootstrap";
import { Link } from "react-router-dom";
import { useLanguage } from "../i18n";
import { sampleNextStep } from "../utils/sampleNextStep.mjs";

export default function SampleWorkflowGuide({ sample, allowed, runs, canModify, canReview }) {
  const { language } = useLanguage();
  const t = (en, es) => language === "es" ? es : en;
  const guidance = {
    received: [t("Received: check the sample details and project, then choose or inspect its pipeline. Change status only when the sample is ready to enter the next stage.", "Recibida: revisa los datos y el proyecto, y elige o consulta su flujo. Cambia el estado solo cuando la muestra esté lista para la siguiente etapa."), "#sample-workflow"],
    ready: [t("A workflow step is ready. Check its instructions, required measurements, and responsible person before starting the work.", "Hay un paso listo. Revisa las instrucciones, mediciones obligatorias y responsable antes de iniciar el trabajo."), "#sample-workflow"],
    continue: [t("Work is in progress. Record the required measurements and results, then complete the work through its existing controls.", "Hay trabajo en curso. Registra las mediciones y resultados obligatorios y completa el trabajo con sus controles habituales."), "#sample-work-items"],
    working: [t("The sample is in progress. Review its work items and record results. Check outstanding work and quality requirements before changing its status.", "La muestra está en curso. Revisa las tareas y registra resultados. Comprueba el trabajo pendiente y los requisitos de calidad antes de cambiar el estado."), "#sample-work-items"],
    review: [t("Quality review is needed. Inspect results and ask an authorized reviewer to resolve the outstanding review before proceeding.", "Se necesita revisión de calidad. Consulta los resultados y pide a un revisor autorizado que resuelva la revisión pendiente antes de continuar."), canReview ? "/qc-review" : "#sample-results"],
    failed: [t("A workflow step failed. Read its failure reason and check whether a retry is available. Resolve the issue with the responsible person; do not skip the failed step.", "Falló un paso del flujo. Lee el motivo y comprueba si se permite repetirlo. Resuelve el problema con el responsable; no omitas el paso fallido."), "#sample-workflow"],
    blocked: [t("The pipeline has no ready step. Inspect dependencies, quality gates, and failure reasons below. Ask the workflow owner to resolve outstanding requirements.", "El flujo no tiene pasos listos. Revisa las dependencias, requisitos de calidad y motivos de fallo. Pide al responsable que resuelva los requisitos pendientes."), "#sample-workflow"],
    reported: [t("The sample is reported. Review its results and history. Archive it only when your lab’s retention policy allows it.", "La muestra está informada. Revisa los resultados y el historial. Archívala solo cuando lo permita la política de conservación del laboratorio."), "#sample-results"],
    cancelled: [t("The sample is cancelled. Review the recorded reason in its history; archive it only if your lab’s policy allows it.", "La muestra está cancelada. Revisa el motivo registrado en el historial; archívala solo si lo permite la política del laboratorio."), "#sample-history"],
    archived: [t("The sample is archived. Review its history and saved results. No further status change is suggested.", "La muestra está archivada. Consulta el historial y los resultados guardados. No se sugiere otro cambio de estado."), "#sample-history"],
    custom: [t("Your lab uses a configured sample status. Review the available transitions and your lab’s procedure before choosing the next stage.", "Tu laboratorio utiliza un estado configurado. Revisa las transiciones disponibles y el procedimiento antes de elegir la siguiente etapa."), "#sample-status"],
    noTransition: [t("No next status is available under the current policy. Review the sample history or ask your administrator about the workflow configuration.", "La política actual no permite otro estado. Revisa el historial o consulta al administrador sobre la configuración del flujo."), "#sample-history"],
  };
  const [message, href] = guidance[sampleNextStep(sample, allowed, runs)];
  const active = ["ARCHIVED", "CANCELLED"].includes(sample.status) ? [] : runs.filter(run => ["ACTIVE", "BLOCKED"].includes(run.status));
  const sectionLabels = {
    "#sample-workflow": t("Review workflow", "Revisar flujo"),
    "#sample-work-items": t("Review work items", "Revisar tareas"),
    "#sample-results": t("View results", "Ver resultados"),
    "#sample-history": t("Review sample history", "Revisar historial de la muestra"),
    "#sample-status": t("Review status options", "Revisar opciones de estado"),
  };
  return <Card className="app-card mb-4" data-testid="sample-workflow-guide"><Card.Body>
    <h2 className="h4">{t("Where this sample is", "Dónde está esta muestra")}</h2>
    <p>{t("Recorded status", "Estado registrado")}: <Badge bg="info" text="dark">{sample.status}</Badge></p>
    <h3 className="h6">{t("What to do next", "Qué hacer a continuación")}</h3>
    <p>{message}</p>
    {!canModify && <p className="small text-muted">{t("You have read-only access to this sample. You can inspect its records; ask the project owner or an administrator to make changes.", "Tienes acceso de lectura a esta muestra. Puedes consultar sus registros; pide al responsable del proyecto o a un administrador que realice los cambios.")}</p>}
    {active.map(run => <div key={run.id} className="border rounded p-3 mb-3">
      <strong>{run.template_name || run.template_code}</strong> · {run.status}
      <div>{(run.steps || []).filter(step => step.status === "COMPLETED").length} / {(run.steps || []).length} {t("steps completed", "pasos completados")}</div>
      <ul className="mb-0">{(run.steps || []).filter(step => !["COMPLETED", "SKIPPED", "CANCELLED"].includes(step.status)).map(step => <li key={step.id}>
        {step.position}. {step.name} — <Badge bg={step.status === "FAILED" ? "danger" : "secondary"}>{step.status}</Badge>
        {step.dependency_positions?.length > 0 && <span> · {t("Depends on steps", "Depende de los pasos")}: {step.dependency_positions.join(", ")}</span>}
        {step.failure_reason && <div className="text-danger">{step.failure_reason}</div>}
      </li>)}</ul>
    </div>)}
    <div className="d-flex gap-2 flex-wrap">
      {href.startsWith("#") ? <a className="btn btn-outline-dark btn-sm" href={href}>{sectionLabels[href]}</a> : <Link className="btn btn-outline-dark btn-sm" to={href}>{t("Review results", "Revisar resultados")}</Link>}
      {canModify && allowed.length > 0 && sample.status !== "ARCHIVED" && href !== "#sample-status" && <a className="btn btn-outline-secondary btn-sm" href="#sample-status">{t("Review status options", "Revisar opciones de estado")}</a>}
    </div>
    <p className="small text-muted mt-3 mb-0">{t("Available next statuses", "Estados siguientes disponibles")}: {allowed.length ? allowed.join(", ") : t("None", "Ninguno")}. {t("Guidance does not change status, complete work, or approve results. Existing checks and reason requirements still apply.", "La orientación no cambia estados, completa tareas ni aprueba resultados. Se mantienen las comprobaciones y los motivos obligatorios.")}</p>
  </Card.Body></Card>;
}
