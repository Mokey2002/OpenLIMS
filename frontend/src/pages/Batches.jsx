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
import { canWrite } from "../authz";
import ConfirmedOperationCard from "../components/ConfirmedOperationCard";
import useConfirmedOperation from "../hooks/useConfirmedOperation";

export default function Batches() {
  const [batches, setBatches] = useState([]);
  const [projects, setProjects] = useState([]);
  const [samples, setSamples] = useState([]);
  const [me, setMe] = useState(null);
  const [error, setError] = useState("");
  const [projectId, setProjectId] = useState("");
  const [batchCode, setBatchCode] = useState("");
  const [selectedSampleIds, setSelectedSampleIds] = useState([]);
  const [assignmentBatchId, setAssignmentBatchId] = useState("");
  const [assignee, setAssignee] = useState("");

  async function load() {
    setError("");
    try {
      const [batchRows, projectRows, sampleRows, meData] = await Promise.all([
        apiGetAll("/api/sample-batches/"),
        apiGetAll("/api/projects/"),
        apiGetAll("/api/samples/"),
        apiGet("/api/me/"),
      ]);
      setBatches(batchRows);
      setProjects(projectRows);
      setSamples(sampleRows);
      setMe(meData);
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    }
  }

  const operation = useConfirmedOperation(async () => {
    setSelectedSampleIds([]);
    await load();
  });

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, []);

  const writable = canWrite(me);
  const projectSamples = useMemo(
    () =>
      samples.filter(
        (sample) => !projectId || String(sample.project_id) === String(projectId)
      ),
    [samples, projectId]
  );

  const selectedSamples = useMemo(
    () => samples.filter((sample) => selectedSampleIds.includes(sample.id)),
    [samples, selectedSampleIds]
  );

  function toggleSample(sampleId) {
    setSelectedSampleIds((current) =>
      current.includes(sampleId)
        ? current.filter((id) => id !== sampleId)
        : [...current, sampleId]
    );
  }

  async function proposeMembership(event) {
    event.preventDefault();
    const code = batchCode.trim();
    if (!code || selectedSamples.length === 0) return;
    const sampleCodes = selectedSamples.map((sample) => sample.sample_id).join(", ");
    await operation.propose(`Add samples ${sampleCodes} to batch ${code}`);
  }

  async function proposeAssignment(event) {
    event.preventDefault();
    const batch = batches.find(
      (row) => String(row.id) === String(assignmentBatchId)
    );
    if (!batch || !assignee.trim()) return;
    await operation.propose(
      `Assign all unassigned samples in batch ${batch.code} to ${assignee.trim()}`
    );
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Sample Batches</h1>
          <p className="page-subtitle">
            Create batch membership and assign unassigned batch samples without
            using the Assistant chat.
          </p>
        </div>
        <Button variant="outline-dark" size="sm" onClick={load}>
          Refresh
        </Button>
      </div>

      {error && <Alert variant="danger">{error}</Alert>}
      {!writable && me && (
        <Alert variant="info">Batch changes require a Tech or Director role.</Alert>
      )}

      {writable && (
        <Row className="g-4 mb-4">
          <Col xl={7}>
            <Card className="app-card h-100">
              <Card.Body>
                <h5 className="section-title">Add samples to a batch</h5>
                <Form onSubmit={proposeMembership}>
                  <Row className="g-2 mb-3">
                    <Col md={5}>
                      <Form.Select
                        value={projectId}
                        onChange={(event) => {
                          setProjectId(event.target.value);
                          setSelectedSampleIds([]);
                        }}
                      >
                        <option value="">All accessible projects</option>
                        {projects.map((project) => (
                          <option key={project.id} value={project.id}>
                            {project.code} — {project.name}
                          </option>
                        ))}
                      </Form.Select>
                    </Col>
                    <Col md={5}>
                      <Form.Control
                        value={batchCode}
                        onChange={(event) => setBatchCode(event.target.value)}
                        placeholder="Batch code, e.g. B-100"
                      />
                    </Col>
                    <Col md={2}>
                      <Button
                        type="submit"
                        variant="dark"
                        className="w-100"
                        disabled={!batchCode.trim() || selectedSampleIds.length === 0}
                      >
                        Preview
                      </Button>
                    </Col>
                  </Row>

                  <div className="table-responsive" style={{ maxHeight: 360 }}>
                    <Table hover size="sm" className="app-table">
                      <thead>
                        <tr>
                          <th></th>
                          <th>Sample</th>
                          <th>Project</th>
                          <th>Current batch</th>
                          <th>Assignee</th>
                        </tr>
                      </thead>
                      <tbody>
                        {projectSamples.map((sample) => (
                          <tr key={sample.id}>
                            <td>
                              <Form.Check
                                checked={selectedSampleIds.includes(sample.id)}
                                onChange={() => toggleSample(sample.id)}
                                aria-label={`Select ${sample.sample_id}`}
                              />
                            </td>
                            <td className="fw-semibold">{sample.sample_id}</td>
                            <td>{sample.project_code || "Unassigned"}</td>
                            <td>{sample.batch_code || "—"}</td>
                            <td>{sample.assigned_to_username || "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  </div>
                  <div className="feed-meta mt-2">
                    {selectedSampleIds.length} selected. New batches require all
                    selected samples to share one primary project.
                  </div>
                </Form>
              </Card.Body>
            </Card>
          </Col>

          <Col xl={5}>
            <Card className="app-card h-100">
              <Card.Body>
                <h5 className="section-title">Assign a batch</h5>
                <Form onSubmit={proposeAssignment}>
                  <Form.Group className="mb-3">
                    <Form.Label>Batch</Form.Label>
                    <Form.Select
                      value={assignmentBatchId}
                      onChange={(event) => setAssignmentBatchId(event.target.value)}
                    >
                      <option value="">Select a batch</option>
                      {batches.map((batch) => (
                        <option key={batch.id} value={batch.id}>
                          {batch.code} — {batch.project_code} ({batch.sample_count} samples)
                        </option>
                      ))}
                    </Form.Select>
                  </Form.Group>
                  <Form.Group className="mb-3">
                    <Form.Label>Assignee username</Form.Label>
                    <Form.Control
                      value={assignee}
                      onChange={(event) => setAssignee(event.target.value)}
                      placeholder="Exact active Tech/Director username"
                    />
                    <div className="feed-meta mt-1">
                      The assignee must be eligible and a member of the batch project.
                    </div>
                  </Form.Group>
                  <Button
                    type="submit"
                    variant="dark"
                    disabled={!assignmentBatchId || !assignee.trim()}
                  >
                    Preview assignment
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
            <h5 className="section-title mb-0">Existing batches</h5>
            <Badge bg="dark">{batches.length}</Badge>
          </div>
          {batches.length === 0 ? (
            <div className="empty-state">No batches found.</div>
          ) : (
            <Table responsive hover className="app-table">
              <thead>
                <tr>
                  <th>Batch</th>
                  <th>Project</th>
                  <th>Samples</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {batches.map((batch) => (
                  <tr key={batch.id}>
                    <td className="fw-semibold">{batch.code}</td>
                    <td>{batch.project_code} — {batch.project_name}</td>
                    <td>{batch.sample_count}</td>
                    <td>{new Date(batch.created_at).toLocaleString()}</td>
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
