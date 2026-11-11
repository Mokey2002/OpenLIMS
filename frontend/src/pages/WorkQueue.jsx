import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  Row,
} from "react-bootstrap";
import { apiGet, apiGetAll, apiPatch } from "../api";
import { canWrite } from "../authz";
import ConfirmedOperationCard from "../components/ConfirmedOperationCard";
import useConfirmedOperation from "../hooks/useConfirmedOperation";
import PersonalTable from "../components/PersonalTable";
import useRememberedTableScroll from "../hooks/useRememberedTableScroll";
import { AccessDetails, AccessNotice } from "../components/ActionGuidance";

const BASE_WORK_TYPES = ["GENERAL", "SEQUENCING", "EXTRACTION", "PCR", "ANALYSIS"];
const WORK_COLUMNS = [
  { key: "work", label: "Work", value: row => `${row.id} ${row.name}`, render: row => `#${row.id} ${row.name}`, optional: false },
  { key: "sample", label: "Sample", value: row => row.sample_code },
  { key: "batch", label: "Batch", value: row => row.batch_code },
  { key: "project", label: "Project", value: row => row.project_code },
  { key: "work_type", label: "Type", value: row => row.work_type },
  { key: "status", label: "Status", value: row => row.status, render: row => <Badge bg={statusVariant(row.status)}>{row.status}</Badge> },
  { key: "assignee", label: "Assignee", value: row => row.assigned_to_username || "Unassigned" },
  { key: "due", label: "Due", value: row => row.due_at, render: row => row.due_at ? new Date(row.due_at).toLocaleString() : "—" },
];

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
  useRememberedTableScroll(me?.id, "work-queue", Boolean(me));
  const [error, setError] = useState("");
  const [batchId, setBatchId] = useState("");
  const [createType, setCreateType] = useState("SEQUENCING");
  const [assignType, setAssignType] = useState("SEQUENCING");
  const [assignmentMode, setAssignmentMode] = useState("ASSIGN");
  const [scope, setScope] = useState("ALL");
  const [targetUsername, setTargetUsername] = useState("");
  const [sourceUsername, setSourceUsername] = useState("");

  const load = useCallback(async () => {
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
  }, []);

  const operation = useConfirmedOperation(load);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, [load]);

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

  const updateWorkStatus = useCallback(async (item, nextStatus) => {
    if (!nextStatus || nextStatus === item.status) return;
    setError("");
    try {
      await apiPatch(`/api/work-items/${item.id}/`, { status: nextStatus });
      await load();
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    }
  }, [load]);

  const writable = canWrite(me);
  const columns = useMemo(() => writable ? [...WORK_COLUMNS, {
    key: "update", label: "Update", optional: false, sortable: false, value: () => "",
    render: item => item.can_update === false ? item.update_access ? <AccessDetails access={item.update_access} /> : <span className="feed-meta">Read-only</span> : ["COMPLETED", "FAILED", "CANCELLED"].includes(item.status) ? <details className="small"><summary>Final</summary>Work Queue treats this work as final. Ask a lab manager about corrections.</details> : <Form.Select size="sm" aria-label={`Update work ${item.id}`} value={item.status} onChange={event => updateWorkStatus(item, event.target.value)}>{["PENDING", "IN_PROGRESS", "COMPLETED", "FAILED", "CANCELLED"].map(status => <option key={status}>{status}</option>)}</Form.Select>,
  }] : WORK_COLUMNS, [writable, updateWorkStatus]);
  const filterOptions = useMemo(() => [
    { key: "work_type", label: "Work type", options: workTypes },
    { key: "status", label: "Work status", options: ["PENDING", "IN_PROGRESS", "COMPLETED", "FAILED", "CANCELLED"] },
  ], [workTypes]);

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
      {me && !writable && <AccessNotice access={{ allowed: false, reason: "Updating work requires a technician or administrator role.", next_step: "Request the appropriate role or ask an administrator.", href: "/access-requests" }} />}
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
            <Badge bg="dark">{workItems.length}</Badge>
          </div>
          <PersonalTable userId={me?.id} name="work-queue" title="Active and recent work" rows={workItems} columns={columns} filterOptions={filterOptions} emptyMessage="No work items match these filters." />
        </Card.Body>
      </Card>
    </div>
  );
}
