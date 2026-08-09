import { Alert, Badge, Table } from "react-bootstrap";

function displayValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.join(", ") || "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function recordValues(values) {
  return Object.entries(values || {})
    .map(([key, value]) => `${key}: ${displayValue(value)}`)
    .join(" · ");
}

export default function AssistantActionPreview({ action }) {
  const preview = action?.preview || {};
  const result = action?.result || {};
  const records = preview.records || preview.samples || [];
  const excluded = preview.excluded || [];
  const warnings = preview.warnings || [];
  const validationErrors = preview.validation_errors || [];
  const failures = result.failed || [];

  if (!preview.operation && !result.operation) return null;

  return (
    <div className="mt-3">
      {preview.operation && (
        <>
          <div className="fw-semibold mb-2">{preview.title || "Exact preview"}</div>
          <Table size="sm" bordered responsive className="mb-2">
            <tbody>
              <tr>
                <th>Operation</th>
                <td>{preview.operation}</td>
              </tr>
              <tr>
                <th>Project</th>
                <td>{preview.project?.label || displayValue(preview.project)}</td>
              </tr>
              <tr>
                <th>Requested user</th>
                <td>
                  {preview.requested_user?.username ||
                    action.requested_user?.username ||
                    "—"}
                </td>
              </tr>
              <tr>
                <th>Records affected</th>
                <td>{preview.records_affected ?? records.length}</td>
              </tr>
              <tr>
                <th>Excluded</th>
                <td>{preview.excluded_count ?? excluded.length}</td>
              </tr>
              <tr>
                <th>Current values</th>
                <td>{recordValues(preview.current_values)}</td>
              </tr>
              <tr>
                <th>Proposed values</th>
                <td>{recordValues(preview.proposed_values)}</td>
              </tr>
            </tbody>
          </Table>

          {records.length > 0 && (
            <div className="table-responsive" style={{ maxHeight: 300 }}>
              <Table size="sm" striped bordered className="mb-2">
                <thead>
                  <tr>
                    <th>Record</th>
                    <th>Current</th>
                    <th>Proposed</th>
                  </tr>
                </thead>
                <tbody>
                  {records.map((record, index) => (
                    <tr
                      key={`${record.id || "new"}-${record.label || record.sample_id}-${index}`}
                    >
                      <td>{record.label || record.sample_id || `Record ${record.id}`}</td>
                      <td>{recordValues(record.current)}</td>
                      <td>{recordValues(record.proposed)}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          )}

          {warnings.length > 0 && (
            <Alert variant="warning" className="py-2 mb-2">
              <strong>Warnings</strong>
              <ul className="mb-0">
                {warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </Alert>
          )}

          {validationErrors.length > 0 && (
            <Alert variant="danger" className="py-2 mb-2">
              <strong>Validation errors</strong>
              <ul className="mb-0">
                {validationErrors.map((error) => (
                  <li key={error}>{error}</li>
                ))}
              </ul>
            </Alert>
          )}

          {excluded.length > 0 && (
            <Alert variant="secondary" className="py-2 mb-2">
              <strong>Excluded records</strong>
              <ul className="mb-0">
                {excluded.map((record, index) => (
                  <li key={`${record.id || record.sample_id || record.label}-${index}`}>
                    {record.label || record.sample_id || `Record ${record.id}`}: {record.reason}
                  </li>
                ))}
              </ul>
            </Alert>
          )}
        </>
      )}

      {result.operation && (
        <Alert
          variant={result.failed_count ? "warning" : "success"}
          className="py-2 mb-0"
        >
          <div className="d-flex gap-2 flex-wrap mb-1">
            <Badge bg="success">Succeeded: {result.succeeded_count || 0}</Badge>
            <Badge bg={result.failed_count ? "danger" : "secondary"}>
              Failed: {result.failed_count || 0}
            </Badge>
          </div>
          {failures.length > 0 && (
            <ul className="mb-0">
              {failures.map((failure, index) => (
                <li key={`${failure.id || failure.sample_id}-${index}`}>
                  {failure.label || failure.sample_id || `Record ${failure.id}`}: {failure.reason}
                </li>
              ))}
            </ul>
          )}
        </Alert>
      )}
    </div>
  );
}
