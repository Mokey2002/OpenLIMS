import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  Row,
  Table,
} from "react-bootstrap";
import { apiGet, apiGetAll, apiPatch } from "../api";
import { canWrite } from "../authz";
import ConfirmedOperationCard from "../components/ConfirmedOperationCard";
import useConfirmedOperation from "../hooks/useConfirmedOperation";

const BASE_WORK_TYPES = ["GENERAL", "SEQUENCING", "EXTRACTION", "PCR", "ANALYSIS"];

function statusVariant(status) {
  if (status === "COMPLETED") return "success";
  if (status === "FAILED" || status === "CANCELLED") return "danger";
  if (status === "IN_PROGRESS") return "primary";
  return "secondary";
}

export default function WorkQueue() {
  const [workItems, setWorkItems] = useState([]);
  const [batches, setBatches] = useState([]);
  const [analysisDefinitions, setAnalysisDefinitions] = useState([]);
  const [me, setMe] = useState(null);
  const [error, setError] = useState("");
  const [batchId, setBatchId] = useState("");
  const [createType, setCreateType] = useState("SEQUENCING");
  const [assignType, setAssignType] = useState("SEQUENCING");
  const [assignmentMode, setAssignmentMode] = useState("ASSIGN");
  const [scope, setScope] = useState("ALL");
  const [targetUsername, setTargetUsername] = useState("");
  const [sourceUsername, setSourceUsername] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  async function load() {
    setError("");
    try {
      const [workRows, batchRows, analysisRows, meData] = await Promise.all([
        apiGetAll("/api/work-items/"),
        apiGetAll("/api/sample-batches/"),
        apiGetAll("/api/analysis-definitions/"),
        apiGet("/api/me/"),
      ]);
      setWorkItems(workRows);
      setBatches(batchRows);
      setAnalysisDefinitions(analysisRows);
      setMe(meData);
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    }
  }

  const operation = useConfirmedOperation(load);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, []);

  const filteredItems = useMemo(
    () =>
      workItems.filter((item) => {
        if (statusFilter && item.status !== statusFilter) return false;
        if (typeFilter && item.work_type !== typeFilter) return false;
        return true;
      }),
    [workItems, statusFilter, typeFilter]
  );

  const workTypes = useMemo(
    () => Array.from(new Set([
      ...BASE_WORK_TYPES,
      ...analysisDefinitions.filter((analysis) => analysis.active).map((analysis) => analysis.code),
    ])).sort(),
    [analysisDefinitions]
  );

  async function proposeCreation(event) {
    event.preventDefault();
    const batch = batches.find((row) => String(row.id) === String(batchId));
    if (!batch) return;
    await operation.propose(
      `Create ${createType.toLowerCase()} work for samples in batch ${batch.code}`
    );
  }

  async function proposeAssignment(event) {
    event.preventDefault();
    if (!targetUsername.trim()) return;
    const scopeText = scope === "OVERDUE" ? "overdue " : scope === "TODAY" ? "today's " : "";
    if (assignmentMode === "REASSIGN") {
      if (!sourceUsername.trim()) return;
      await operation.propose(
        `Reassign ${scopeText}${assignType.toLowerCase()} work from ${sourceUsername.trim()} to ${targetUsername.trim()}`
      );
      return;
    }
    await operation.propose(
      `Assign ${scopeText}unassigned ${assignType.toLowerCase()} work to ${targetUsername.trim()}`
    );
  }

  async function updateWorkStatus(item, nextStatus) {
    if (!nextStatus || nextStatus === item.status) return;
    setError("");
    try {
      await apiPatch(`/api/work-items/${item.id}/`, { status: nextStatus });
      await load();
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    }
  }

  const writable = canWrite(me);

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Work Queue</h1>
          <p className="page-subtitle">
            Create work for an entire batch and assign active work from regular forms.
          </p>
        </div>
        <Button variant="outline-dark" size="sm" onClick={load}>Refresh</Button>
      </div>

      {error && <Alert variant="danger">{error}</Alert>}
      {!writable && me && (
        <Alert variant="info">Work creation and assignment require a Tech or Director role.</Alert>
      )}

      {writable && (
        <Row className="g-4 mb-4">
          <Col xl={5}>
            <Card className="app-card h-100">
              <Card.Body>
                <h5 className="section-title">Create batch work</h5>
                <Form onSubmit={proposeCreation}>
                  <Form.Group className="mb-3">
                    <Form.Label>Batch</Form.Label>
                    <Form.Select value={batchId} onChange={(event) => setBatchId(event.target.value)}>
                      <option value="">Select a batch</option>
                      {batches.map((batch) => (
                        <option key={batch.id} value={batch.id}>
                          {batch.code} — {batch.project_code} ({batch.sample_count} samples)
                        </option>
                      ))}
                    </Form.Select>
                  </Form.Group>
                  <Form.Group className="mb-3">
                    <Form.Label>Work type</Form.Label>
                    <Form.Select value={createType} onChange={(event) => setCreateType(event.target.value)}>
                      {workTypes.map((type) => <option key={type}>{type}</option>)}
                    </Form.Select>
                  </Form.Group>
                  <Button type="submit" variant="dark" disabled={!batchId}>Preview work creation</Button>
                </Form>
              </Card.Body>
            </Card>
          </Col>

          <Col xl={7}>
            <Card className="app-card h-100">
              <Card.Body>
                <h5 className="section-title">Assign active work</h5>
                <Form onSubmit={proposeAssignment}>
                  <Row className="g-3">
                    <Col md={4}>
                      <Form.Label>Mode</Form.Label>
                      <Form.Select value={assignmentMode} onChange={(event) => setAssignmentMode(event.target.value)}>
                        <option value="ASSIGN">Assign unassigned</option>
                        <option value="REASSIGN">Reassign</option>
                      </Form.Select>
                    </Col>
                    <Col md={4}>
                      <Form.Label>Work type</Form.Label>
                      <Form.Select value={assignType} onChange={(event) => setAssignType(event.target.value)}>
                        {workTypes.map((type) => <option key={type}>{type}</option>)}
                      </Form.Select>
                    </Col>
                    <Col md={4}>
                      <Form.Label>Scope</Form.Label>
                      <Form.Select value={scope} onChange={(event) => setScope(event.target.value)}>
                        <option value="ALL">All active</option>
                        <option value="TODAY">Due today</option>
                        <option value="OVERDUE">Overdue</option>
                      </Form.Select>
                    </Col>
                    {assignmentMode === "REASSIGN" && (
                      <Col md={6}>
                        <Form.Label>Current assignee username</Form.Label>
                        <Form.Control value={sourceUsername} onChange={(event) => setSourceUsername(event.target.value)} />
                      </Col>
                    )}
                    <Col md={assignmentMode === "REASSIGN" ? 6 : 12}>
                      <Form.Label>New assignee username</Form.Label>
                      <Form.Control value={targetUsername} onChange={(event) => setTargetUsername(event.target.value)} />
                    </Col>
                    <Col xs={12}>
                      <Button
                        type="submit"
                        variant="dark"
                        disabled={!targetUsername.trim() || (assignmentMode === "REASSIGN" && !sourceUsername.trim())}
                      >
                        Preview assignment
                      </Button>
                    </Col>
                  </Row>
                </Form>
              </Card.Body>
            </Card>
          </Col>
        </Row>
      )}

      <ConfirmedOperationCard operation={operation} />

      <Card className="app-card mt-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <h5 className="section-title mb-0">Active and recent work</h5>
            <Badge bg="dark">{filteredItems.length}</Badge>
          </div>
          <Row className="g-2 mb-3">
            <Col md={4}>
              <Form.Select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
                <option value="">All work types</option>
                {workTypes.map((type) => <option key={type}>{type}</option>)}
              </Form.Select>
            </Col>
            <Col md={4}>
              <Form.Select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                <option value="">All statuses</option>
                <option value="PENDING">PENDING</option>
                <option value="IN_PROGRESS">IN_PROGRESS</option>
                <option value="COMPLETED">COMPLETED</option>
                <option value="FAILED">FAILED</option>
                <option value="CANCELLED">CANCELLED</option>
              </Form.Select>
            </Col>
          </Row>
          {filteredItems.length === 0 ? (
            <div className="empty-state">No work items match these filters.</div>
          ) : (
            <Table responsive hover className="app-table">
              <thead><tr><th>Work</th><th>Sample</th><th>Batch</th><th>Project</th><th>Type</th><th>Status</th><th>Assignee</th><th>Due</th>{writable && <th>Update</th>}</tr></thead>
              <tbody>
                {filteredItems.map((item) => (
                  <tr key={item.id}>
                    <td>#{item.id} {item.name}</td>
                    <td>{item.sample_code}</td>
                    <td>{item.batch_code || "—"}</td>
                    <td>{item.project_code || "—"}</td>
                    <td>{item.work_type}</td>
                    <td><Badge bg={statusVariant(item.status)}>{item.status}</Badge></td>
                    <td>{item.assigned_to_username || "Unassigned"}</td>
                    <td>{item.due_at ? new Date(item.due_at).toLocaleString() : "—"}</td>
                    {writable && (
                      <td>
                        {["COMPLETED", "FAILED", "CANCELLED"].includes(item.status) ? (
                          <span className="feed-meta">Final</span>
                        ) : (
                          <Form.Select
                            size="sm"
                            value={item.status}
                            onChange={(event) => updateWorkStatus(item, event.target.value)}
                          >
                            <option value="PENDING">PENDING</option>
                            <option value="IN_PROGRESS">IN_PROGRESS</option>
                            <option value="COMPLETED">COMPLETED</option>
                            <option value="FAILED">FAILED</option>
                            <option value="CANCELLED">CANCELLED</option>
                          </Form.Select>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>
    </div>
  );
}
