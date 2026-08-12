import { Accordion, Alert, Badge, Card, Table } from "react-bootstrap";
import { Link } from "react-router-dom";

function tone(value) {
  if (value === "high") return "danger";
  if (value === "medium") return "warning";
  return "secondary";
}

function shortDate(value) {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

export default function InvestigationPanel({ investigation, compact = false }) {
  if (!investigation) return null;
  const summary = investigation.summary || {};
  const subject = investigation.subject || {};

  return (
    <div className="mt-3">
      <Alert variant="warning" className="py-2">
        <strong>Decision support:</strong> findings rank recorded evidence and associations;
        they do not establish root cause by themselves.
      </Alert>

      <div className="d-flex gap-2 flex-wrap mb-3">
        <Badge bg="dark">{subject.sample_id}</Badge>
        {subject.project && <Badge bg="secondary">Project {subject.project}</Badge>}
        {subject.batch && <Badge bg="secondary">Batch {subject.batch}</Badge>}
        <Badge bg={summary.subject_qc_failures ? "danger" : "success"}>
          {summary.subject_qc_failures || 0} QC failure(s)
        </Badge>
        <Badge bg="danger">{summary.direct_findings || 0} direct</Badge>
        <Badge bg="primary">{summary.comparative_findings || 0} comparative</Badge>
        <Badge bg="secondary">{summary.contextual_findings || 0} contextual</Badge>
      </div>

      <Card className="app-card mb-3">
        <Card.Header className="fw-semibold">Ranked findings</Card.Header>
        <Card.Body className="p-0">
          {investigation.findings?.length ? (
            <div className="table-responsive">
              <Table hover className="mb-0 align-middle">
                <thead>
                  <tr>
                    <th>Severity</th>
                    <th>Confidence</th>
                    <th>Evidence</th>
                    <th>Finding</th>
                  </tr>
                </thead>
                <tbody>
                  {investigation.findings.map((finding) => (
                    <tr key={finding.id}>
                      <td><Badge bg={tone(finding.severity)}>{finding.severity}</Badge></td>
                      <td><Badge bg={tone(finding.confidence)}>{finding.confidence}</Badge></td>
                      <td>{finding.evidence_type}</td>
                      <td>
                        <div className="fw-semibold">{finding.title}</div>
                        <div className="small text-muted">{finding.detail}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          ) : (
            <div className="p-3 text-muted">No specific failure signal was identified.</div>
          )}
        </Card.Body>
      </Card>

      {!compact && (
        <Accordion alwaysOpen className="mb-3">
          <Accordion.Item eventKey="results">
            <Accordion.Header>Subject results ({investigation.results?.length || 0})</Accordion.Header>
            <Accordion.Body className="p-0">
              <div className="table-responsive">
                <Table hover className="mb-0">
                  <thead><tr><th>Result</th><th>Value</th><th>Reference</th><th>QC</th><th>Entered by</th></tr></thead>
                  <tbody>
                    {investigation.results?.map((row) => (
                      <tr key={row.id}>
                        <td>{row.key} <span className="text-muted">#{row.id}</span></td>
                        <td>{row.display_value}</td>
                        <td>{row.reference_min ?? "—"} to {row.reference_max ?? "—"} {row.unit}</td>
                        <td>{row.qc_status}{row.qc_passed === false ? " / failed" : ""}</td>
                        <td>{row.entered_by || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </div>
            </Accordion.Body>
          </Accordion.Item>

          <Accordion.Item eventKey="workflow">
            <Accordion.Header>Workflow evidence ({investigation.workflow?.length || 0})</Accordion.Header>
            <Accordion.Body className="p-0">
              <div className="table-responsive">
                <Table hover className="mb-0">
                  <thead><tr><th>Work</th><th>Type</th><th>Status</th><th>QC</th><th>Assigned</th><th>Due</th></tr></thead>
                  <tbody>
                    {investigation.workflow?.map((row) => (
                      <tr key={row.id} className={row.overdue ? "table-warning" : ""}>
                        <td>{row.name}</td><td>{row.work_type}</td><td>{row.status}</td>
                        <td>{row.qc_status}</td><td>{row.assigned_to || "—"}</td><td>{shortDate(row.due_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </div>
            </Accordion.Body>
          </Accordion.Item>

          <Accordion.Item eventKey="similar">
            <Accordion.Header>Similar cohort failures ({investigation.similar_failures?.length || 0})</Accordion.Header>
            <Accordion.Body className="p-0">
              <div className="table-responsive">
                <Table hover className="mb-0">
                  <thead><tr><th>Sample</th><th>Result</th><th>Value</th><th>QC</th><th>Reason</th></tr></thead>
                  <tbody>
                    {investigation.similar_failures?.map((row) => (
                      <tr key={row.result_id}>
                        <td><Link to={`/samples/${row.sample_pk}`}>{row.sample_id}</Link></td>
                        <td>{row.key} #{row.result_id}</td><td>{row.display_value}</td>
                        <td>{row.qc_status}</td><td>{row.failure_reason || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </div>
            </Accordion.Body>
          </Accordion.Item>

          <Accordion.Item eventKey="instruments">
            <Accordion.Header>Instrument connector evidence ({investigation.instrument_context?.length || 0})</Accordion.Header>
            <Accordion.Body className="p-0">
              <div className="table-responsive">
                <Table hover className="mb-0">
                  <thead><tr><th>Instrument</th><th>Run</th><th>Status</th><th>Link strength</th><th>Imported</th></tr></thead>
                  <tbody>
                    {investigation.instrument_context?.map((row) => (
                      <tr key={row.id}>
                        <td>{row.instrument_code} — {row.instrument_name}</td>
                        <td>{row.run_id || `Job ${row.id}`}</td><td>{row.status}</td>
                        <td>{row.direct_sample_link ? "Direct work-item provenance" : "Project/time context"}</td>
                        <td>{shortDate(row.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </div>
            </Accordion.Body>
          </Accordion.Item>

          <Accordion.Item eventKey="reagents">
            <Accordion.Header>Reagent lot context ({investigation.reagent_context?.length || 0})</Accordion.Header>
            <Accordion.Body className="p-0">
              <div className="table-responsive">
                <Table hover className="mb-0">
                  <thead><tr><th>Reagent</th><th>Lot</th><th>Lot status</th><th>Reservation</th><th>Expiration</th></tr></thead>
                  <tbody>
                    {investigation.reagent_context?.map((row) => (
                      <tr key={row.reservation_id} className={row.expired ? "table-warning" : ""}>
                        <td>{row.item_code} — {row.item_name}</td><td>{row.lot_code}</td>
                        <td>{row.lot_status}</td><td>{row.quantity} {row.unit} / {row.reservation_status}</td>
                        <td>{row.expiration_date || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </div>
            </Accordion.Body>
          </Accordion.Item>

          <Accordion.Item eventKey="timeline">
            <Accordion.Header>Audit timeline ({investigation.timeline?.length || 0})</Accordion.Header>
            <Accordion.Body>
              {investigation.timeline?.map((row, index) => (
                <div key={`${row.timestamp}-${index}`} className="border-start ps-3 pb-3">
                  <div className="fw-semibold">{row.action}</div>
                  <div className="small">{row.entity_type} {row.entity_id} · {row.actor || "system"}</div>
                  <div className="small text-muted">{shortDate(row.timestamp)} · {row.detail}</div>
                </div>
              ))}
            </Accordion.Body>
          </Accordion.Item>
        </Accordion>
      )}

      <Alert variant="secondary" className="small mb-0">
        <div className="fw-semibold mb-1">Limitations</div>
        <ul className="mb-0">
          {investigation.disclaimers?.map((note) => <li key={note}>{note}</li>)}
        </ul>
      </Alert>
    </div>
  );
}
