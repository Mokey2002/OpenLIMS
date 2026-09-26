import { useEffect, useState } from "react";
import { Alert, Breadcrumb } from "react-bootstrap";
import { Link, useLocation } from "react-router-dom";
import { useLanguage } from "../i18n";

const labels = {
  projects: ["Projects", "Proyectos"], samples: ["Samples", "Muestras"],
  notebook: ["Notebooks", "Bitácoras"], search: ["Search", "Buscar"],
  notifications: ["Notifications", "Notificaciones"], me: ["My profile", "Mi perfil"],
  inventory: ["Inventory", "Inventario"], sequences: ["Sequences", "Secuencias"],
  alignments: ["Alignments", "Alineamientos"], imports: ["Imports", "Importaciones"],
  "mass-spec": ["Mass spectrometry", "Espectrometría de masas"],
  "qc-review": ["Quality review", "Revisión de calidad"],
  "work-queue": ["Work queue", "Cola de trabajo"], reports: ["Reports", "Informes"],
  settings: ["Settings", "Configuración"], users: ["Users", "Usuarios"],
  dashboard: ["Dashboard", "Panel"], assistant: ["Assistant", "Asistente"],
  traceability: ["Traceability", "Trazabilidad"], events: ["Audit events", "Auditoría"],
  analyze: ["Analysis", "Análisis"], "system-status": ["System status", "Estado del sistema"],
  sops: ["Protocols", "Protocolos"], batches: ["Batches", "Lotes"], labels: ["Labels", "Etiquetas"],
  comparisons: ["Comparisons", "Comparaciones"], investigations: ["Investigations", "Investigaciones"],
  "workflow-requests": ["Workflow requests", "Solicitudes de trabajo"],
  "data-migration": ["Data migration", "Migración de datos"], blast: ["BLAST", "BLAST"],
  registry: ["Registry", "Registro"], "workflow-designer": ["Workflow designer", "Diseñador de flujos"],
};

export default function WorkspaceFeedback() {
  const { pathname } = useLocation();
  const { language, t } = useLanguage();
  const es = language === "es";
  const [feedback, setFeedback] = useState(null);
  useEffect(() => {
    const listener = event => setFeedback(event.detail);
    window.addEventListener("openlims:request", listener);
    return () => window.removeEventListener("openlims:request", listener);
  }, []);
  useEffect(() => {
    if (!feedback || feedback.state === "pending" || feedback.state === "error") return;
    const timer = setTimeout(() => setFeedback(null), 5000);
    return () => clearTimeout(timer);
  }, [feedback]);
  const segments = pathname.split("/").filter(Boolean);
  const parts = segments.length > 1 ? [segments[0], segments.slice(1).join("/")] : segments;
  const text = feedback?.state === "pending" ? (es ? "Procesando…" : "Processing…")
    : feedback?.state === "error" ? feedback?.status === 403
      ? (es ? "No tienes permiso para esta acción. Solicita acceso al propietario del registro o a un administrador." : "You do not have permission for this action. Ask the record owner or an administrator for access.")
      : (es ? "No se pudo confirmar la acción. Revisa el mensaje del formulario y tu conexión antes de volver a intentar." : "The action could not be confirmed. Check the form message and your connection before retrying.")
    : (es ? "Solicitud completada." : "Request completed.");
  return <>
    {parts.length > 0 && <Breadcrumb aria-label={es ? "Ruta de navegación" : "Breadcrumb"}>
      <Breadcrumb.Item linkAs={Link} linkProps={{ to: "/" }}>{es ? "Mi trabajo" : "My Work"}</Breadcrumb.Item>
      {parts.map((part, index) => <Breadcrumb.Item key={index} active={index === parts.length - 1}
        linkAs={index < parts.length - 1 ? Link : undefined}
        linkProps={index < parts.length - 1 ? { to: "/" + parts.slice(0, index + 1).join("/") } : undefined}>
        {labels[part]?.[es ? 1 : 0] || (index > 0 ? (es ? "Detalle" : "Details") : t(part.replaceAll("-", " ")))}
      </Breadcrumb.Item>)}
    </Breadcrumb>}
    {feedback && <Alert role={feedback.state === "error" ? "alert" : "status"}
      variant={feedback.state === "error" ? "danger" : feedback.state === "pending" ? "info" : "success"}
      dismissible={feedback.state !== "pending"} onClose={() => setFeedback(null)}>{text}</Alert>}
  </>;
}
