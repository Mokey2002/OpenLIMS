import { Badge, Table } from "react-bootstrap";

function formatValue(value, format) {
  if (value === null || value === undefined || value === "") return "—";
  const numeric = Number(value);
  if (format === "percent" && Number.isFinite(numeric)) {
    return `${numeric.toFixed(1)}%`;
  }
  if (format === "integer" && Number.isFinite(numeric)) {
    return Math.round(numeric).toLocaleString();
  }
  if (format === "number" && Number.isFinite(numeric)) {
    return numeric.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default function ComparisonTable({ comparison }) {
  if (!comparison || !Array.isArray(comparison.rows)) return null;

  const columns = comparison.columns || [];
  const filters = comparison.filters || {};

  return (
    <div className="comparison-result-card">
      <div className="d-flex justify-content-between align-items-start gap-3 flex-wrap mb-3">
        <div>
          <div className="assistant-chart-title">
            {comparison.title || "Comparison"}
          </div>
          <div className="assistant-chart-description">
            {comparison.rows.length} row(s), calculated from accessible records
          </div>
        </div>
        <div className="d-flex gap-1 flex-wrap">
          {filters.kind && <Badge bg="secondary">{filters.kind}</Badge>}
          {filters.metric && <Badge bg="dark">{filters.metric}</Badge>}
          {filters.days && <Badge bg="primary">Last {filters.days} days</Badge>}
        </div>
      </div>

      <div className="table-responsive comparison-table-wrap">
        <Table hover size="sm" align="middle" className="mb-0">
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column.key}>{column.label || column.key}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {comparison.rows.map((row, index) => (
              <tr key={`${row.entity || row.sample || "row"}-${index}`}>
                {columns.map((column) => (
                  <td key={column.key}>
                    {formatValue(row[column.key], column.format)}
                  </td>
                ))}
              </tr>
            ))}
            {comparison.rows.length === 0 && (
              <tr>
                <td colSpan={Math.max(columns.length, 1)} className="text-muted text-center py-4">
                  No matching records were found.
                </td>
              </tr>
            )}
          </tbody>
        </Table>
      </div>

      {comparison.notes?.length > 0 && (
        <ul className="small text-muted mt-3 mb-0 ps-3">
          {comparison.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
