import { Badge, Card } from "react-bootstrap";
import { Link } from "react-router-dom";
import { useLanguage } from "../i18n";

export default function LabSetupChecklist({ setup }) {
  const { language } = useLanguage();
  const t = (en, es) => language === "es" ? es : en;
  if (!setup) return null;
  const steps = [
    { done: setup.users_added, title: t("Add lab users", "Añadir usuarios del laboratorio"),
      help: t("Add each person with their own account and the role they need. Send an invitation so they can set their password.", "Añade a cada persona con su propia cuenta y el rol necesario. Envía una invitación para que establezca su contraseña."),
      allowed: setup.can_add_users, to: "/users", action: t("Manage users", "Gestionar usuarios"),
      blocked: t("Ask an administrator to add your colleagues. Only administrators can check this step.", "Pide a un administrador que añada a tus compañeros. Solo los administradores pueden comprobar este paso.") },
    { done: setup.project_created, title: t("Create a project", "Crear un proyecto"),
      help: t("Give the study a name and unique code, then add the people who need access to its samples.", "Asigna al estudio un nombre y un código único, y añade a las personas que necesitan acceder a sus muestras."),
      allowed: setup.can_create_project, to: "/projects", action: t("Open projects", "Abrir proyectos"),
      blocked: t("Ask an administrator to create a project and add you as a member. You can view projects shared with you.", "Pide a un administrador que cree un proyecto y te añada como miembro. Puedes ver los proyectos compartidos contigo.") },
    { done: setup.sample_registered, title: t("Register the first sample", "Registrar la primera muestra"),
      help: t("Use a unique sample ID, select the sample type, and choose the primary project under More options. Open the saved sample to see what to do next.", "Usa un identificador único, selecciona el tipo de muestra y elige el proyecto principal en Más opciones. Abre la muestra guardada para ver el siguiente paso."),
      allowed: setup.can_register_sample, to: "/samples", action: t("Open samples", "Abrir muestras"),
      blocked: t("Ask an administrator or technician to register a sample in your project. Your account can view accessible samples.", "Pide a un administrador o técnico que registre una muestra en tu proyecto. Tu cuenta puede ver las muestras accesibles.") },
  ];
  return <Card className="app-card mb-4" data-testid="lab-setup-checklist"><Card.Body>
    <h2 className="h4">{t("Set up your lab", "Configura tu laboratorio")}</h2>
    <p className="text-muted">{t("This checklist checks saved records each time you refresh. Project and sample progress reflects records you can access; it does not verify invitations or approvals.", "La lista comprueba los registros guardados al actualizar. El progreso de proyectos y muestras refleja los registros a los que tienes acceso; no verifica invitaciones ni aprobaciones.")}</p>
    <ol className="mb-0">{steps.map(step => <li key={step.to} className="mb-3">
      <div className="d-flex gap-2 flex-wrap align-items-center"><strong>{step.title}</strong>
        <Badge bg={step.done ? "success" : "secondary"}>{step.done ? t("Complete", "Completo") : step.done === null ? t("Administrator check", "Comprobación del administrador") : t("Not started", "Sin iniciar")}</Badge>
      </div>
      <p className="mb-1 mt-1">{step.help}</p>
      {!step.allowed && <p className="small text-muted mb-1">{step.blocked}</p>}
      {(step.allowed || step.to !== "/users") && <Link className="btn btn-outline-dark btn-sm" to={step.to}>{step.action}</Link>}
    </li>)}</ol>
  </Card.Body></Card>;
}
