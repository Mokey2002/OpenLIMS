import { useEffect, useState } from "react";
import { Alert, Badge, Button, Card, Col, Row, Spinner, Table } from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGet } from "../api";

function isPast(value) {
  return Boolean(value && new Date(value).getTime() < Date.now());
}

function statusVariant(status) {
  if (["FAILED", "REJECTED", "RERUN_REQUIRED"].includes(status)) return "danger";
  if (["PENDING_REVIEW", "TRIAGE", "SUBMITTED"].includes(status)) return "warning";
  if (["IN_PROGRESS", "APPROVED"].includes(status)) return "info";
  if (["COMPLETED", "REVIEWED", "LOCKED"].includes(status)) return "success";
  return "secondary";
}

function SummaryCard({ label, value, hint, to }) {
  const body = (
    <Card className="h-100 shadow-sm border-0">
      <Card.Body>
        <div className="text-muted small text-uppercase fw-semibold">{label}</div>
        <div className="display-6 fw-bold mb-1">{value}</div>
        <div className="small text-muted">{hint}</div>
      </Card.Body>
    </Card>
  );
  return to ? <Link className="text-decoration-none text-reset" to={to}>{body}</Link> : body;
}

export default function MyWork() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setLoading(true);
    setError("");
    try {
      setData(await apiGet("/api/v1/my-work/"));
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  if (loading) {
    return <div className="py-5 text-center"><Spinner animation="border" /></div>;
  }

  if (error) {
    return <Alert variant="danger">{error}</Alert>;
  }

  const summary = data.summary;
  const alertCount = summary.inventory_alerts + summary.unread_notifications;

  return (
    <div data-testid="my-work-page">
      <div className="d-flex justify-content-between align-items-start gap-3 mb-4 flex-wrap">
        <div>
          <h2 className="mb-1">My Work</h2>
          <p className="text-muted mb-0">
            One place for assigned work, requests, experiments, QC, alerts, and overdue items.
          </p>
        </div>
        <Button variant="outline-dark" size="sm" onClick={load}>Refresh</Button>
      </div>

      <Row className="g-3 mb-4">
        <Col sm={6} xl={2}><SummaryCard label="Assigned" value={summary.assigned} hint="Active work items" to="/work-queue" /></Col>
        <Col sm={6} xl={2}><SummaryCard label="Requests" value={summary.requests} hint="Visible active requests" to="/workflow-requests" /></Col>
        <Col sm={6} xl={2}><SummaryCard label="Experiments" value={summary.experiments} hint={data.notebook_enabled ? "Assigned or created" : "Notebook disabled"} to={data.notebook_enabled ? "/notebook" : null} /></Col>
        <Col sm={6} xl={2}><SummaryCard label="QC" value={summary.qc} hint="Pending / rerun" to="/qc-review" /></Col>
        <Col sm={6} xl={2}><SummaryCard label="Alerts" value={alertCount} hint="Inventory + notifications" to="/notifications" /></Col>
        <Col sm={6} xl={2}><SummaryCard label="Overdue" value={summary.overdue} hint="Needs attention" /></Col>
      </Row>

      <Row className="g-4">
        <Col xl={7}>
          <Card className="shadow-sm border-0 h-100">
            <Card.Body>
              <div className="d-flex justify-content-between align-items-center mb-3">
                <h5 className="mb-0">Assigned work</h5>
                <Link to="/work-queue">Open queue</Link>
              </div>
              {data.assigned_work.length === 0 ? (
                <div className="text-muted">No active work is assigned to you.</div>
              ) : (
                <Table responsive hover size="sm" className="align-middle mb-0">
                  <thead><tr><th>Work</th><th>Sample</th><th>Status</th><th>QC</th><th>Due</th></tr></thead>
                  <tbody>
                    {data.assigned_work.map((item) => (
                      <tr key={item.id}>
                        <td><div className="fw-semibold">{item.name}</div><div className="small text-muted">{item.project_code || "No project"}</div></td>
                        <td>{item.sample_code || "—"}</td>
                        <td><Badge bg={statusVariant(item.status)}>{item.status}</Badge></td>
                        <td><Badge bg={statusVariant(item.qc_status)}>{item.qc_status}</Badge></td>
                        <td className={isPast(item.due_at) ? "text-danger fw-semibold" : ""}>{item.due_at ? new Date(item.due_at).toLocaleString() : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </Col>

        <Col xl={5}>
          <Card className="shadow-sm border-0 mb-4">
            <Card.Body>
              <h5>Overdue</h5>
              {data.overdue.length === 0 ? <div className="text-muted">Nothing overdue.</div> : data.overdue.map((item) => (
                <div key={item.key} className="border-top py-2">
                  <div className="d-flex justify-content-between gap-2"><Link to={item.to} className="fw-semibold">{item.name}</Link><Badge bg="danger">{item.type}</Badge></div>
                  <div className="small text-muted">{item.context}</div>
                  <div className="small text-danger">Due {new Date(item.due_at).toLocaleString()}</div>
                </div>
              ))}
            </Card.Body>
          </Card>

          <Card className="shadow-sm border-0">
            <Card.Body>
              <div className="d-flex justify-content-between align-items-center mb-2"><h5 className="mb-0">Attention</h5><Link to="/notifications">Notifications</Link></div>
              <div className="d-flex gap-2 flex-wrap mb-3">
                <Badge bg="warning" text="dark">{summary.qc} QC</Badge>
                <Badge bg="danger">{summary.inventory_alerts} inventory alerts</Badge>
                <Badge bg="info">{summary.unread_notifications} unread</Badge>
              </div>
              {data.notifications.map((item) => (
                <div key={item.id} className="border-top py-2"><div className="fw-semibold">{item.title}</div><div className="small text-muted">{item.message}</div></div>
              ))}
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
