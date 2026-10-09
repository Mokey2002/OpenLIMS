import { Badge, Table } from "react-bootstrap";
import { Link } from "react-router-dom";

export default function ProjectWorkflowTable({ data }) {
  const spanish = data.language === "es";
  const t = (en, es) => spanish ? es : en;
  const labels = {
    failed: ["Failed", "Fallido"], qc: ["QC", "QC"], missing: ["Missing fields", "Campos faltantes"],
    overdue: ["Overdue", "Vencido"], unassigned: ["Unassigned", "Sin asignar"],
    dependency: ["Dependency", "Dependencia"], activation: ["Activation", "Activación"],
    run_blocked: ["Blocked pipeline", "Pipeline bloqueado"], ready: ["Available work", "Trabajo disponible"],
  };
  if (!data.rows?.length) return null;
  return (
    <Table size="sm" bordered responsive className="mt-3">
      <caption>
        {t("Current workflow evidence", "Registros actuales del flujo")} · {data.project_code}
        {data.as_of && ` · ${new Date(data.as_of).toLocaleString()}`}
      </caption>
      <thead>
        <tr>
          <th>{t("Sample", "Muestra")}</th>
          <th>{t("Steps and reasons", "Pasos y motivos")}</th>
        </tr>
      </thead>
      <tbody>
        {data.rows.map(row => (
          <tr key={row.sample_id}>
            <td>
              <Link to={row.url}>{row.sample_code}</Link>
              <div className="small text-muted">{row.status}</div>
            </td>
            <td>
              {row.reasons.map((reason, index) => (
                <div key={`${reason.run_id}-${reason.step}-${index}`} className="mb-2">
                  <strong>
                    Run #{reason.run_id}
                    {reason.step != null && ` · ${t("Step", "Paso")} ${reason.step}: ${reason.step_name}`}
                  </strong>
                  <Badge bg={reason.kind === "failed" || (reason.kind === "qc" && ["REJECTED", "RERUN_REQUIRED"].includes(reason.qc_status)) ? "danger" : "secondary"} className="me-2">
                    {t(...(labels[reason.kind] || [reason.kind, reason.kind]))}
                  </Badge>
                  <div>{reason.reason}</div>
                  {reason.due_at && <div className="small">{t("Due", "Vence")}: {new Date(reason.due_at).toLocaleString()}</div>}
                  {reason.next_action && <div className="small mt-1"><strong>{t("Next action", "Próxima acción")}:</strong> {reason.next_action}</div>}
                  {reason.assignee && <div className="small text-muted">{t("Work assignee", "Responsable del trabajo")}: {reason.assignee}</div>}
                </div>
              ))}
              {!row.reasons.length && t("No active pipeline or unfinished step evidence.", "Sin pipeline activo o pasos pendientes registrados.")}
              {row.additional_reasons > 0 && (
                <Link to={row.url}>{t("More reasons", "Más motivos")}: {row.additional_reasons}</Link>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}
