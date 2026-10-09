import { Table } from "react-bootstrap";
import { Link } from "react-router-dom";

export default function ProjectWorkflowTable({ data }) {
  const spanish = data.language === "es";
  const t = (en, es) => spanish ? es : en;
  if (!data.rows?.length) return null;
  return (
    <Table size="sm" bordered responsive className="mt-3">
      <caption>
        {t("Current workflow evidence", "Registros actuales del flujo")} · {data.project_code}
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
                  <div>{reason.reason}</div>
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
