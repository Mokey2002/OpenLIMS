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
import { apiGet, apiGetAll } from "../api";
import { canWrite, isQcReviewer } from "../authz";
import ConfirmedOperationCard from "../components/ConfirmedOperationCard";
import useConfirmedOperation from "../hooks/useConfirmedOperation";

function statusVariant(status) {
  if (status === "APPROVED") return "success";
  if (status === "REJECTED") return "danger";
  if (status === "REOPENED") return "warning";
  return "secondary";
}

function resultValue(result) {
  if (result.value !== null && result.value !== undefined) return String(result.value);
  return "—";
}

function referenceRange(result) {
  if (result.reference_min === null && result.reference_max === null) return "Not configured";
  return `${result.reference_min ?? "−∞"} to ${result.reference_max ?? "∞"}${
    result.unit ? ` ${result.unit}` : ""
  }`;
}

export default function QCReview() {
  const [results, setResults] = useState([]);
  const [projects, setProjects] = useState([]);
  const [me, setMe] = useState(null);
  const [error, setError] = useState("");
  const [projectId, setProjectId] = useState("");
  const [qcStatus, setQcStatus] = useState("PENDING_REVIEW");
  const [qcOutcome, setQcOutcome] = useState("");
  const [selectedResultId, setSelectedResultId] = useState("");
  const [reason, setReason] = useState("");
  const [reviewerUsername, setReviewerUsername] = useState("");

  async function load() {
    setError("");
    try {
      const [resultRows, projectRows, meData] = await Promise.all([
        apiGetAll("/api/results/"),
        apiGetAll("/api/projects/"),
        apiGet("/api/me/"),
      ]);
      setResults(resultRows);
      setProjects(projectRows);
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

  const filteredResults = useMemo(
    () =>
      results.filter((result) => {
        if (projectId && String(result.project_id) !== String(projectId)) return false;
        if (qcStatus && result.qc_status !== qcStatus) return false;
        if (qcOutcome === "PASS" && result.qc_passed !== true) return false;
        if (qcOutcome === "FAIL" && result.qc_passed !== false) return false;
        if (qcOutcome === "UNKNOWN" && result.qc_passed !== null) return false;
        return true;
      }),
    [results, projectId, qcStatus, qcOutcome]
  );

  const selectedResult = results.find(
    (result) => String(result.id) === String(selectedResultId)
  );
  const canFlagOrAssign = canWrite(me) || isQcReviewer(me);
  const canDecide = isQcReviewer(me);

  async function proposeDecision(decision) {
    if (!selectedResult) return;
    if (decision === "FLAG") {
      await operation.propose(`Flag result R-${selectedResult.id} for review`);
      return;
    }
    if (!reason.trim()) return;
    await operation.propose(
      `${decision.toLowerCase()} result R-${selectedResult.id} because ${reason.trim()}`
    );
  }

  async function proposeAssignment(event) {
    event.preventDefault();
    if (!reviewerUsername.trim()) return;
    await operation.propose(
      `Assign failed QC results to ${reviewerUsername.trim()}`
    );
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Result QC Review</h1>
          <p className="page-subtitle">
            Review, reopen, flag, and assign individual result records with an
            audited reason.
          </p>
        </div>
        <Button variant="outline-dark" size="sm" onClick={load}>Refresh</Button>
      </div>

      {error && <Alert variant="danger">{error}</Alert>}
      {!canFlagOrAssign && me && (
        <Alert variant="info">
          Result QC changes require a Tech, QC Reviewer, or Director role.
        </Alert>
      )}

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Filters</h5>
          <Row className="g-3">
            <Col md={4}>
              <Form.Select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
                <option value="">All accessible projects</option>
                {projects.map((project) => (
                  <option key={project.id} value={project.id}>{project.code} — {project.name}</option>
                ))}
              </Form.Select>
            </Col>
            <Col md={4}>
              <Form.Select value={qcStatus} onChange={(event) => setQcStatus(event.target.value)}>
                <option value="">All review states</option>
                <option value="PENDING_REVIEW">Pending review</option>
                <option value="REOPENED">Reopened</option>
                <option value="APPROVED">Approved</option>
                <option value="REJECTED">Rejected</option>
              </Form.Select>
            </Col>
            <Col md={4}>
              <Form.Select value={qcOutcome} onChange={(event) => setQcOutcome(event.target.value)}>
                <option value="">All automated QC outcomes</option>
                <option value="PASS">Passed</option>
                <option value="FAIL">Failed</option>
                <option value="UNKNOWN">Not evaluated</option>
              </Form.Select>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      {canFlagOrAssign && (
        <Row className="g-4 mb-4">
          <Col xl={7}>
            <Card className="app-card h-100">
              <Card.Body>
                <h5 className="section-title">Selected result action</h5>
                <Form.Select
                  className="mb-3"
                  value={selectedResultId}
                  onChange={(event) => setSelectedResultId(event.target.value)}
                >
                  <option value="">Select a visible result</option>
                  {filteredResults.map((result) => (
                    <option key={result.id} value={result.id}>
                      R-{result.id} — {result.sample_code} / {result.key} ({result.qc_status})
                    </option>
                  ))}
                </Form.Select>

                <Form.Control
                  as="textarea"
                  rows={3}
                  className="mb-3"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  placeholder="Required reason for approve, reject, or reopen"
                />

                <div className="inline-actions">
                  {canDecide && (
                    <>
                      <Button size="sm" variant="outline-success" disabled={!selectedResult || !reason.trim()} onClick={() => proposeDecision("APPROVE")}>Approve</Button>
                      <Button size="sm" variant="outline-danger" disabled={!selectedResult || !reason.trim()} onClick={() => proposeDecision("REJECT")}>Reject</Button>
                      <Button size="sm" variant="outline-warning" disabled={!selectedResult || !reason.trim()} onClick={() => proposeDecision("REOPEN")}>Reopen</Button>
                    </>
                  )}
                  <Button size="sm" variant="outline-secondary" disabled={!selectedResult} onClick={() => proposeDecision("FLAG")}>Flag for review</Button>
                </div>
                {!canDecide && (
                  <div className="feed-meta mt-2">
                    Only QC Reviewers and Directors can approve, reject, or reopen results.
                  </div>
                )}
              </Card.Body>
            </Card>
          </Col>

          <Col xl={5}>
            <Card className="app-card h-100">
              <Card.Body>
                <h5 className="section-title">Assign failed QC</h5>
                <Form onSubmit={proposeAssignment}>
                  <Form.Group className="mb-3">
                    <Form.Label>QC reviewer username</Form.Label>
                    <Form.Control
                      value={reviewerUsername}
                      onChange={(event) => setReviewerUsername(event.target.value)}
                      placeholder="Exact active QC reviewer username"
                    />
                  </Form.Group>
                  <Button type="submit" variant="dark" disabled={!reviewerUsername.trim()}>
                    Preview failed-result assignment
                  </Button>
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
            <h5 className="section-title mb-0">Results</h5>
            <Badge bg="dark">{filteredResults.length}</Badge>
          </div>
          {filteredResults.length === 0 ? (
            <div className="empty-state">No results match these filters.</div>
          ) : (
            <Table responsive hover className="app-table">
              <thead>
                <tr>
                  <th>Result</th><th>Sample</th><th>Test</th><th>Value</th>
                  <th>Reference</th><th>Automated QC</th><th>Review</th><th>Assigned</th>
                </tr>
              </thead>
              <tbody>
                {filteredResults.map((result) => (
                  <tr key={result.id}>
                    <td className="fw-semibold">R-{result.id}</td>
                    <td>{result.sample_code}</td>
                    <td>{result.key}</td>
                    <td>{resultValue(result)} {result.unit}</td>
                    <td>{referenceRange(result)}</td>
                    <td>
                      <Badge bg={result.qc_passed === true ? "success" : result.qc_passed === false ? "danger" : "secondary"}>
                        {result.qc_passed === true ? "PASS" : result.qc_passed === false ? "FAIL" : "UNKNOWN"}
                      </Badge>
                    </td>
                    <td><Badge bg={statusVariant(result.qc_status)}>{result.qc_status}</Badge></td>
                    <td>{result.qc_assigned_to_username || "—"}</td>
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
