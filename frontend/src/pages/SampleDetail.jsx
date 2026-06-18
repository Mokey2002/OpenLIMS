import { useEffect, useMemo, useState } from "react";
import { useParams, Link } from "react-router-dom";
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
import { apiGet, apiPatch, apiPost, apiPostForm } from "../api";
import { canWrite, readOnlyMessage } from "../authz";

function statusVariant(status) {
  switch (status) {
    case "RECEIVED":
      return "secondary";
    case "IN_PROGRESS":
      return "primary";
    case "QC":
      return "warning";
    case "REPORTED":
      return "success";
    case "ARCHIVED":
      return "dark";
    default:
      return "light";
  }
}

function workItemVariant(status) {
  switch (status) {
    case "PENDING":
      return "secondary";
    case "IN_PROGRESS":
      return "primary";
    case "COMPLETED":
      return "success";
    case "FAILED":
      return "danger";
    default:
      return "light";
  }
}

function qcVariant(status) {
  switch (status) {
    case "APPROVED":
      return "success";
    case "REJECTED":
      return "danger";
    case "RERUN_REQUIRED":
      return "warning";
    case "PENDING_REVIEW":
      return "secondary";
    default:
      return "light";
  }
}

function qcLabel(status) {
  switch (status) {
    case "APPROVED":
      return "Approved";
    case "REJECTED":
      return "Rejected";
    case "RERUN_REQUIRED":
      return "Re-run Required";
    case "PENDING_REVIEW":
      return "Pending Review";
    default:
      return status || "Pending Review";
  }
}

function massSpecStatusVariant(status) {
  switch (status) {
    case "COMPLETED":
      return "success";
    case "FAILED":
      return "danger";
    case "RUNNING":
      return "info";
    case "PENDING":
      return "secondary";
    default:
      return "secondary";
  }
}

function actionVariant(action) {
  switch (action) {
    case "CREATED":
      return "success";
    case "UPDATED":
      return "primary";
    case "DELETED":
      return "danger";
    case "STATUS_CHANGED":
    case "SAMPLE_STATUS_CHANGED":
    case "BULK_SAMPLE_STATUS_CHANGED":
      return "warning";
    case "CONTAINER_ASSIGNED":
      return "info";
    case "ATTACHMENT_UPLOADED":
      return "info";
    case "RESULTS_IMPORTED":
      return "dark";
    case "IMPORT_RETRY_QUEUED":
      return "secondary";
    case "SEQUENCE_WORKSPACE_CREATED":
      return "success";
    case "SEQUENCE_WORKSPACE_UPDATED":
      return "primary";
    case "SEQUENCE_WORKSPACE_DELETED":
      return "danger";
    case "QC_APPROVED":
      return "success";
    case "QC_REJECTED":
      return "danger";
    case "QC_RERUN_REQUIRED":
      return "warning";
    case "QC_PENDING_REVIEW":
      return "secondary";
    case "QC_REVIEW_UPDATED":
      return "info";
    default:
      return "secondary";
  }
}

function formatTimestamp(ts) {
  if (!ts) return "-";

  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function getTimelineTitle(event) {
  const payload = event.payload || {};

  if (event.action === "CREATED") {
    if (payload.source === "instrument_import") {
      return `Sample created from ${
        payload.instrument_code || "instrument import"
      }`;
    }

    return "Sample created";
  }

  if (
    event.action === "STATUS_CHANGED" ||
    event.action === "SAMPLE_STATUS_CHANGED" ||
    event.action === "BULK_SAMPLE_STATUS_CHANGED"
  ) {
    const before = payload.before?.status;
    const after = payload.after?.status;

    if (before && after) {
      return `Status changed from ${before} to ${after}`;
    }

    return "Status changed";
  }

  if (event.action === "UPDATED") {
    const changed = payload.changed_fields || [];

    if (changed.includes("container_id")) {
      return "Container assignment changed";
    }

    if (changed.includes("project_id")) {
      return "Project assignment changed";
    }

    return "Sample updated";
  }

  if (event.action === "ATTACHMENT_UPLOADED") {
    return "File attached";
  }

  if (event.action === "RESULTS_IMPORTED") {
    return "Results imported";
  }

  if (event.action === "SEQUENCE_WORKSPACE_CREATED") {
    return "Sequence workspace created";
  }

  if (event.action === "SEQUENCE_WORKSPACE_UPDATED") {
    return "Sequence workspace updated";
  }

  if (event.action === "SEQUENCE_WORKSPACE_DELETED") {
    return "Sequence workspace deleted";
  }

  if (event.action === "QC_APPROVED") {
    return `QC approved for ${payload.work_item_name || "work item"}`;
  }

  if (event.action === "QC_REJECTED") {
    return `QC rejected for ${payload.work_item_name || "work item"}`;
  }

  if (event.action === "QC_RERUN_REQUIRED") {
    return `Re-run requested for ${payload.work_item_name || "work item"}`;
  }

  if (event.action === "QC_PENDING_REVIEW") {
    return `QC marked pending for ${payload.work_item_name || "work item"}`;
  }

  return event.action;
}

function renderBeforeAfter(event) {
  const payload = event.payload || {};
  const before = payload.before || null;
  const after = payload.after || null;

  if (!before || !after) return null;

  const keys = Array.from(
    new Set([...Object.keys(before), ...Object.keys(after)])
  );

  return (
    <Table responsive size="sm" className="app-table mt-3">
      <thead>
        <tr>
          <th>Field</th>
          <th>Before</th>
          <th>After</th>
        </tr>
      </thead>

      <tbody>
        {keys.map((key) => {
          const beforeValue = before[key] ?? "-";
          const afterValue = after[key] ?? "-";

          if (beforeValue === afterValue) return null;

          return (
            <tr key={key}>
              <td>{key}</td>
              <td>{String(beforeValue)}</td>
              <td>{String(afterValue)}</td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

function renderReason(event) {
  const payload = event.payload || {};
  const reason = payload.reason;

  if (!reason) return null;

  return (
    <div className="reason-box mt-3">
      <div className="feed-meta mb-1">Reason for change</div>
      <div className="fw-semibold">{reason}</div>
    </div>
  );
}

function renderLineageLinks(event) {
  const payload = event.payload || {};
  const importJobId = payload.import_job_id;

  if (!importJobId) return null;

  return (
    <div className="mt-2">
      <Link to={`/imports/${importJobId}`}>View Import Job #{importJobId}</Link>
    </div>
  );
}

function resultDisplayValue(result) {
  if (result.value !== undefined && result.value !== null) {
    return String(result.value);
  }

  if (result.value_number !== undefined && result.value_number !== null) {
    return String(result.value_number);
  }

  if (result.value_string !== undefined && result.value_string !== null) {
    return String(result.value_string);
  }

  if (result.value_boolean !== undefined && result.value_boolean !== null) {
    return String(result.value_boolean);
  }

  return "-";
}

export default function SampleDetail() {
  const { id } = useParams();

  const [sample, setSample] = useState(null);
  const [allowed, setAllowed] = useState([]);
  const [events, setEvents] = useState([]);
  const [workItems, setWorkItems] = useState([]);
  const [containers, setContainers] = useState([]);
  const [sampleAttachments, setSampleAttachments] = useState([]);
  const [sampleSequences, setSampleSequences] = useState([]);
  const [massSpecRuns, setMassSpecRuns] = useState([]);
  const [me, setMe] = useState(null);

  const [err, setErr] = useState("");
  const [success, setSuccess] = useState("");

  const [newWorkItemName, setNewWorkItemName] = useState("");
  const [newWorkItemNotes, setNewWorkItemNotes] = useState("");
  const [resultForms, setResultForms] = useState({});
  const [reviewNotes, setReviewNotes] = useState({});

  const [selectedAttachmentFile, setSelectedAttachmentFile] = useState(null);
  const [selectedContainer, setSelectedContainer] = useState("");

  const [statusTransitionTarget, setStatusTransitionTarget] = useState("");
  const [statusChangeReason, setStatusChangeReason] = useState("");

  async function load() {
    setErr("");

    try {
      const [
        sampleData,
        transitionData,
        eventsData,
        workItemsData,
        containersData,
        attachmentsData,
        sequencesData,
        massSpecData,
        meData,
      ] = await Promise.all([
        apiGet(`/api/samples/${id}/`),
        apiGet(`/api/samples/${id}/allowed-transitions/`),
        apiGet(`/api/events/`),
        apiGet(`/api/work-items/?sample=${id}`),
        apiGet("/api/containers/"),
        apiGet(`/api/sample-attachments/?sample=${id}`),
        apiGet(`/api/sequences/?sample=${id}`),
        apiGet(`/api/mass-spec-runs/?sample=${id}`),
        apiGet("/api/me/"),
      ]);

      const eventList = eventsData.results || eventsData || [];
      const workItemList = workItemsData.results || workItemsData || [];
      const containerList = containersData.results || containersData || [];
      const attachmentList = attachmentsData.results || attachmentsData || [];
      const sequenceList = sequencesData.results || sequencesData || [];
      const massSpecList = massSpecData.results || massSpecData || [];

      const allowedTransitions = transitionData.allowed_transitions || [];

      setSample(sampleData);
      setAllowed(allowedTransitions);
      setStatusTransitionTarget((current) =>
        current && allowedTransitions.includes(current)
          ? current
          : allowedTransitions[0] || ""
      );
      setWorkItems(workItemList);
      setContainers(containerList);
      setSelectedContainer(sampleData.container || "");
      setSampleAttachments(attachmentList);
      setSampleSequences(sequenceList);
      setMassSpecRuns(massSpecList);
      setMe(meData);

      const sampleEvents = eventList.filter((event) => {
        const payload = event.payload || {};

        return (
          event.entity_type === "Sample" &&
          (String(event.entity_id) === String(id) ||
            String(payload.sample_id) === String(id))
        );
      });

      setEvents(sampleEvents);
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  const projectId = sample?.project || sample?.project_id;
  const userCanWrite = canWrite(me);
  const readOnlyText = readOnlyMessage(me);

  const sortedEvents = useMemo(() => {
    return [...events].sort(
      (a, b) => new Date(b.timestamp) - new Date(a.timestamp)
    );
  }, [events]);

  const resultRows = useMemo(() => {
    const rows = [];

    for (const workItem of workItems) {
      for (const result of workItem.results || []) {
        rows.push({
          id: result.id,
          workItemId: workItem.id,
          workItemName: workItem.name,
          key: result.key,
          value: resultDisplayValue(result),
          valueType: result.value_type,
        });
      }
    }

    return rows;
  }, [workItems]);

  const importEvents = useMemo(() => {
    return sortedEvents.filter((event) => {
      const payload = event.payload || {};

      return (
        event.action === "RESULTS_IMPORTED" ||
        event.action === "IMPORT_RETRY_QUEUED" ||
        payload.import_job_id
      );
    });
  }, [sortedEvents]);

  const qcStats = useMemo(() => {
    return {
      pending: workItems.filter((item) => item.qc_status === "PENDING_REVIEW")
        .length,
      approved: workItems.filter((item) => item.qc_status === "APPROVED")
        .length,
      rejected: workItems.filter((item) => item.qc_status === "REJECTED")
        .length,
      rerun: workItems.filter((item) => item.qc_status === "RERUN_REQUIRED")
        .length,
    };
  }, [workItems]);

  async function doTransition(e) {
    e.preventDefault();

    if (!userCanWrite) return;

    setErr("");
    setSuccess("");

    const reason = statusChangeReason.trim();

    if (!statusTransitionTarget) {
      setErr("Select a new status.");
      return;
    }

    if (reason.length < 10) {
      setErr("Reason for change is required and must be at least 10 characters.");
      return;
    }

    try {
      await apiPost(`/api/samples/${id}/transition/`, {
        new_status: statusTransitionTarget,
        reason,
      });

      setStatusChangeReason("");
      setSuccess(
        `Sample moved to ${statusTransitionTarget}. Reason recorded in audit trail.`
      );
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function createWorkItem(e) {
    e.preventDefault();

    if (!userCanWrite) return;

    setErr("");
    setSuccess("");

    try {
      await apiPost("/api/work-items/", {
        sample: Number(id),
        name: newWorkItemName,
        status: "PENDING",
        notes: newWorkItemNotes,
      });

      setNewWorkItemName("");
      setNewWorkItemNotes("");
      setSuccess("Work item created.");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  function updateResultForm(workItemId, field, value) {
    setResultForms((prev) => ({
      ...prev,
      [workItemId]: {
        ...(prev[workItemId] || {}),
        [field]: value,
      },
    }));
  }

  async function addResult(workItemId) {
    if (!userCanWrite) return;

    const form = resultForms[workItemId] || {};
    setErr("");
    setSuccess("");

    try {
      const payload = {
        work_item: workItemId,
        key: form.key,
        value_type: form.value_type,
      };

      if (form.value_type === "STRING") {
        payload.value_string = form.value_string || "";
      } else if (form.value_type === "NUMBER") {
        payload.value_number =
          form.value_number === "" || form.value_number === undefined
            ? null
            : Number(form.value_number);
      } else if (form.value_type === "BOOLEAN") {
        payload.value_boolean = form.value_boolean === "true";
      }

      await apiPost("/api/results/", payload);

      setResultForms((prev) => ({
        ...prev,
        [workItemId]: {
          key: "",
          value_type: "STRING",
          value_string: "",
          value_number: "",
          value_boolean: "true",
        },
      }));

      setSuccess("Result added.");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  function updateReviewNote(workItemId, value) {
    setReviewNotes((prev) => ({
      ...prev,
      [workItemId]: value,
    }));
  }

  async function reviewWorkItem(workItemId, qcStatus) {
    if (!userCanWrite) return;

    setErr("");
    setSuccess("");

    try {
      await apiPost(`/api/work-items/${workItemId}/qc-review/`, {
        qc_status: qcStatus,
        review_note: reviewNotes[workItemId] || "",
      });

      setReviewNotes((prev) => ({
        ...prev,
        [workItemId]: "",
      }));

      setSuccess(`QC review updated to ${qcLabel(qcStatus)}.`);
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function uploadSampleAttachment(e) {
    e.preventDefault();

    if (!userCanWrite) return;
    if (!selectedAttachmentFile) return;

    setErr("");
    setSuccess("");

    try {
      const formData = new FormData();
      formData.append("sample", id);
      formData.append("file", selectedAttachmentFile);

      await apiPostForm("/api/sample-attachments/", formData);

      setSelectedAttachmentFile(null);
      setSuccess("Attachment uploaded.");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function assignContainer(e) {
    e.preventDefault();

    if (!userCanWrite) return;

    setErr("");
    setSuccess("");

    try {
      await apiPatch(`/api/samples/${id}/`, {
        container: selectedContainer ? Number(selectedContainer) : null,
      });

      setSuccess("Container assignment updated.");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  if (!sample) {
    return (
      <div className="w-100">
        {err ? (
          <Alert variant="danger">{err}</Alert>
        ) : (
          <Card className="app-card">
            <Card.Body>Loading sample...</Card.Body>
          </Card>
        )}
      </div>
    );
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">{sample.sample_id}</h1>
          <p className="page-subtitle">
            Complete sample record with workflow, results, QC review, storage,
            files, sequences, and chain of custody.
          </p>
        </div>

        <Badge bg={statusVariant(sample.status)}>{sample.status}</Badge>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}
      {success && <Alert variant="success">{success}</Alert>}
      {readOnlyText && <Alert variant="info">{readOnlyText}</Alert>}

      <div className="stat-grid mb-4">
        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Work Items</div>
            <div className="metric-value">{workItems.length}</div>
            <div className="metric-note">Tasks linked to this sample</div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Result Values</div>
            <div className="metric-value">{resultRows.length}</div>
            <div className="metric-note">Recorded measurements</div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">QC Pending</div>
            <div className="metric-value">{qcStats.pending}</div>
            <div className="metric-note">
              Approved: {qcStats.approved} · Re-run: {qcStats.rerun}
            </div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Mass Spec Runs</div>
            <div className="metric-value">{massSpecRuns.length}</div>
            <div className="metric-note">Linked mzML/mzXML/mzData runs</div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Events</div>
            <div className="metric-value">{sortedEvents.length}</div>
            <div className="metric-note">Audit trail records</div>
          </Card.Body>
        </Card>
      </div>

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="row g-4">
            <div className="col-lg-8">
              <h5 className="section-title">Sample Overview</h5>

              <div className="row g-3">
                <div className="col-md-4">
                  <div className="soft-card">
                    <div className="feed-meta">Linked Project</div>
                    <div className="fw-semibold">
                      {projectId ? (
                        <Link to={`/projects/${projectId}`}>
                          {sample.project_code || `Project #${projectId}`}
                        </Link>
                      ) : (
                        "Unassigned"
                      )}
                    </div>
                  </div>
                </div>

                <div className="col-md-4">
                  <div className="soft-card">
                    <div className="feed-meta">Container</div>
                    <div className="fw-semibold">
                      {sample.container_code || "Unassigned"}
                    </div>
                  </div>
                </div>

                <div className="col-md-4">
                  <div className="soft-card">
                    <div className="feed-meta">Location</div>
                    <div className="fw-semibold">
                      {sample.location_name || "Unassigned"}
                    </div>
                  </div>
                </div>

                <div className="col-md-4">
                  <div className="soft-card">
                    <div className="feed-meta">Created</div>
                    <div className="fw-semibold">
                      {formatTimestamp(sample.created_at)}
                    </div>
                  </div>
                </div>

                <div className="col-md-4">
                  <div className="soft-card">
                    <div className="feed-meta">Updated</div>
                    <div className="fw-semibold">
                      {formatTimestamp(sample.updated_at)}
                    </div>
                  </div>
                </div>

                <div className="col-md-4">
                  <div className="soft-card">
                    <div className="feed-meta">Status</div>
                    <Badge bg={statusVariant(sample.status)}>
                      {sample.status}
                    </Badge>
                  </div>
                </div>
              </div>
            </div>

            {userCanWrite && (
              <div className="col-lg-4">
                <h5 className="section-title">Change Status</h5>

                {allowed.length === 0 ? (
                  <span className="empty-state">No further transitions.</span>
                ) : (
                  <Form onSubmit={doTransition}>
                    <Form.Group className="mb-3">
                      <Form.Label>New Status</Form.Label>
                      <Form.Select
                        value={statusTransitionTarget}
                        onChange={(e) =>
                          setStatusTransitionTarget(e.target.value)
                        }
                      >
                        {allowed.map((status) => (
                          <option key={status} value={status}>
                            {status}
                          </option>
                        ))}
                      </Form.Select>
                    </Form.Group>

                    <Form.Group className="mb-3">
                      <Form.Label>Reason for change</Form.Label>
                      <Form.Control
                        as="textarea"
                        rows={3}
                        value={statusChangeReason}
                        onChange={(e) => setStatusChangeReason(e.target.value)}
                        placeholder="Example: QC review completed and results approved for reporting."
                      />
                      <div className="feed-meta mt-1">
                        Required for status changes. This reason is saved in the
                        audit trail.
                      </div>
                    </Form.Group>

                    <Button
                      type="submit"
                      variant="dark"
                      size="sm"
                      disabled={
                        !statusTransitionTarget ||
                        statusChangeReason.trim().length < 10
                      }
                    >
                      Update Status
                    </Button>
                  </Form>
                )}
              </div>
            )}
          </div>
        </Card.Body>
      </Card>

      <div className="row g-4 mb-4">
        {userCanWrite && (
          <div className="col-lg-5">
            <Card className="app-card h-100">
              <Card.Body>
                <h5 className="section-title">Storage Assignment</h5>

                <Form onSubmit={assignContainer}>
                  <Row className="g-2 align-items-center">
                    <Col md={8}>
                      <Form.Select
                        value={selectedContainer}
                        onChange={(e) => setSelectedContainer(e.target.value)}
                      >
                        <option value="">Unassigned</option>

                        {containers.map((container) => (
                          <option key={container.id} value={container.id}>
                            {container.container_id} ({container.kind}) —{" "}
                            {container.location_name || container.location}
                          </option>
                        ))}
                      </Form.Select>
                    </Col>

                    <Col md={4}>
                      <Button type="submit" variant="dark" className="w-100">
                        Save
                      </Button>
                    </Col>
                  </Row>
                </Form>
              </Card.Body>
            </Card>
          </div>
        )}

        <div className="col-lg-7">
          <Card className="app-card h-100">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">
                  Linked Sequence Workspaces
                </h5>
                <Badge bg="dark">{sampleSequences.length}</Badge>
              </div>

              {sampleSequences.length === 0 ? (
                <div className="empty-state">
                  No sequence workspaces linked to this sample yet.
                </div>
              ) : (
                <Table responsive hover className="app-table">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Type</th>
                      <th>Length</th>
                      <th>Updated</th>
                      <th></th>
                    </tr>
                  </thead>

                  <tbody>
                    {sampleSequences.map((sequence) => (
                      <tr key={sequence.id}>
                        <td className="fw-semibold">{sequence.name}</td>
                        <td>{sequence.sequence_type}</td>
                        <td>{sequence.sequence?.length ?? 0} bp</td>
                        <td>{formatTimestamp(sequence.updated_at)}</td>
                        <td>
                          <Link to={`/sequences?workspace=${sequence.id}`}>
                            Open
                          </Link>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </div>
      </div>

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <h5 className="section-title mb-0">Result Values</h5>
            <Badge bg="dark">{resultRows.length}</Badge>
          </div>

          {resultRows.length === 0 ? (
            <div className="empty-state">No result values yet.</div>
          ) : (
            <Table responsive hover className="app-table">
              <thead>
                <tr>
                  <th>Work Item</th>
                  <th>Key</th>
                  <th>Value</th>
                  <th>Type</th>
                </tr>
              </thead>

              <tbody>
                {resultRows.map((result) => (
                  <tr key={`${result.workItemId}-${result.id}`}>
                    <td>{result.workItemName}</td>
                    <td>{result.key}</td>
                    <td>{result.value}</td>
                    <td>{result.valueType}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <h5 className="section-title mb-0">Import History</h5>
            <Badge bg="dark">{importEvents.length}</Badge>
          </div>

          {importEvents.length === 0 ? (
            <div className="empty-state">
              No import lineage events found for this sample.
            </div>
          ) : (
            <Table responsive hover className="app-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Action</th>
                  <th>Import Job</th>
                  <th>Actor</th>
                </tr>
              </thead>

              <tbody>
                {importEvents.map((event) => {
                  const importJobId = event.payload?.import_job_id;

                  return (
                    <tr key={event.id}>
                      <td>{formatTimestamp(event.timestamp)}</td>
                      <td>
                        <Badge bg={actionVariant(event.action)}>
                          {event.action}
                        </Badge>
                      </td>
                      <td>
                        {importJobId ? (
                          <Link to={`/imports/${importJobId}`}>
                            Import Job #{importJobId}
                          </Link>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td>{event.actor_username || "-"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>


      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Mass Spec Runs</h5>
              <div className="feed-meta">
                Mass spectrometry runs linked to this sample.
              </div>
            </div>

            <Badge bg="dark">{massSpecRuns.length}</Badge>
          </div>

          {massSpecRuns.length === 0 ? (
            <div className="empty-state">
              No mass spec runs linked to this sample yet.
            </div>
          ) : (
            <Table responsive hover className="app-table">
              <thead>
                <tr>
                  <th>Run</th>
                  <th>Status</th>
                  <th>Spectra</th>
                  <th>MS1 / MS2</th>
                  <th>TIC Points</th>
                  <th>Processed</th>
                  <th></th>
                </tr>
              </thead>

              <tbody>
                {massSpecRuns.map((run) => (
                  <tr key={run.id}>
                    <td className="fw-semibold">{run.name}</td>
                    <td>
                      <Badge bg={massSpecStatusVariant(run.status)}>
                        {run.status}
                      </Badge>
                    </td>
                    <td>{run.spectra_count}</td>
                    <td>
                      {run.ms1_count} / {run.ms2_count}
                    </td>
                    <td>{run.chromatogram_data?.length || 0}</td>
                    <td>{formatTimestamp(run.processed_at)}</td>
                    <td>
                      <Link to={`/mass-spec/${run.id}`}>Open</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>

      <div className="row g-4 mb-4">
        <div className="col-lg-5">
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Sample Attachments</h5>

              {userCanWrite && (
                <Form onSubmit={uploadSampleAttachment} className="mb-4">
                  <Row className="g-2 align-items-center">
                    <Col md={8}>
                      <Form.Control
                        type="file"
                        onChange={(e) =>
                          setSelectedAttachmentFile(e.target.files?.[0] || null)
                        }
                      />
                    </Col>

                    <Col md={4}>
                      <Button type="submit" variant="dark" className="w-100">
                        Upload
                      </Button>
                    </Col>
                  </Row>
                </Form>
              )}

              {sampleAttachments.length === 0 ? (
                <div className="empty-state">No attachments yet.</div>
              ) : (
                <Table responsive hover className="app-table">
                  <thead>
                    <tr>
                      <th>File</th>
                      <th>Uploaded By</th>
                      <th>Uploaded</th>
                    </tr>
                  </thead>

                  <tbody>
                    {sampleAttachments.map((attachment) => (
                      <tr key={attachment.id}>
                        <td>
                          <a
                            href={attachment.file}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {attachment.filename || "Attachment"}
                          </a>
                        </td>
                        <td>{attachment.uploaded_by_username || "-"}</td>
                        <td>{formatTimestamp(attachment.uploaded_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </div>

        <div className="col-lg-7">
          <Card className="app-card h-100">
            <Card.Body>
              <h5 className="section-title">Work Items</h5>

              {userCanWrite && (
                <Form onSubmit={createWorkItem} className="mb-4">
                  <Row className="g-2">
                    <Col md={4}>
                      <Form.Control
                        placeholder="Work item name"
                        value={newWorkItemName}
                        onChange={(e) => setNewWorkItemName(e.target.value)}
                      />
                    </Col>

                    <Col md={6}>
                      <Form.Control
                        placeholder="Notes"
                        value={newWorkItemNotes}
                        onChange={(e) => setNewWorkItemNotes(e.target.value)}
                      />
                    </Col>

                    <Col md={2}>
                      <Button
                        type="submit"
                        variant="dark"
                        className="w-100"
                        disabled={!newWorkItemName}
                      >
                        Add
                      </Button>
                    </Col>
                  </Row>
                </Form>
              )}

              {workItems.length === 0 ? (
                <div className="empty-state">No work items yet.</div>
              ) : (
                <div className="d-grid gap-3">
                  {workItems.map((workItem) => {
                    const form = resultForms[workItem.id] || {
                      key: "",
                      value_type: "STRING",
                      value_string: "",
                      value_number: "",
                      value_boolean: "true",
                    };

                    return (
                      <div key={workItem.id} className="feed-item">
                        <div className="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-3">
                          <div>
                            <div className="fw-semibold">{workItem.name}</div>
                            <div className="feed-meta">{workItem.notes}</div>

                            {workItem.reviewed_by_username && (
                              <div className="feed-meta mt-1">
                                Reviewed by {workItem.reviewed_by_username} at{" "}
                                {formatTimestamp(workItem.reviewed_at)}
                              </div>
                            )}

                            {workItem.review_note && (
                              <div className="small mt-2">
                                <strong>Review note:</strong>{" "}
                                {workItem.review_note}
                              </div>
                            )}
                          </div>

                          <div className="d-flex gap-2 flex-wrap">
                            <Badge bg={workItemVariant(workItem.status)}>
                              {workItem.status}
                            </Badge>

                            <Badge bg={qcVariant(workItem.qc_status)}>
                              {qcLabel(workItem.qc_status)}
                            </Badge>
                          </div>
                        </div>

                        <div className="mb-3">
                          <div className="feed-meta mb-2">Results</div>

                          {workItem.results?.length === 0 ? (
                            <div className="empty-state">No results yet.</div>
                          ) : (
                            <Table
                              responsive
                              hover
                              size="sm"
                              className="app-table"
                            >
                              <thead>
                                <tr>
                                  <th>Key</th>
                                  <th>Value</th>
                                  <th>Type</th>
                                </tr>
                              </thead>

                              <tbody>
                                {workItem.results.map((result) => (
                                  <tr key={result.id}>
                                    <td>{result.key}</td>
                                    <td>{resultDisplayValue(result)}</td>
                                    <td>{result.value_type}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </Table>
                          )}
                        </div>

                        {userCanWrite && (
                          <div className="soft-card mb-3">
                            <div className="feed-meta mb-2">QC Review</div>

                            <Form.Control
                              as="textarea"
                              rows={2}
                              className="mb-2"
                              placeholder="Optional review note..."
                              value={reviewNotes[workItem.id] || ""}
                              onChange={(e) =>
                                updateReviewNote(workItem.id, e.target.value)
                              }
                            />

                            <div className="inline-actions">
                              <Button
                                size="sm"
                                variant="outline-success"
                                onClick={() =>
                                  reviewWorkItem(workItem.id, "APPROVED")
                                }
                              >
                                Approve
                              </Button>

                              <Button
                                size="sm"
                                variant="outline-danger"
                                onClick={() =>
                                  reviewWorkItem(workItem.id, "REJECTED")
                                }
                              >
                                Reject
                              </Button>

                              <Button
                                size="sm"
                                variant="outline-warning"
                                onClick={() =>
                                  reviewWorkItem(workItem.id, "RERUN_REQUIRED")
                                }
                              >
                                Request Re-run
                              </Button>

                              <Button
                                size="sm"
                                variant="outline-secondary"
                                onClick={() =>
                                  reviewWorkItem(workItem.id, "PENDING_REVIEW")
                                }
                              >
                                Mark Pending
                              </Button>
                            </div>
                          </div>
                        )}

                        {userCanWrite && (
                          <div className="soft-card">
                            <div className="feed-meta mb-2">Add Result</div>

                            <Row className="g-2">
                              <Col md={3}>
                                <Form.Control
                                  placeholder="Key"
                                  value={form.key}
                                  onChange={(e) =>
                                    updateResultForm(
                                      workItem.id,
                                      "key",
                                      e.target.value
                                    )
                                  }
                                />
                              </Col>

                              <Col md={3}>
                                <Form.Select
                                  value={form.value_type}
                                  onChange={(e) =>
                                    updateResultForm(
                                      workItem.id,
                                      "value_type",
                                      e.target.value
                                    )
                                  }
                                >
                                  <option value="STRING">STRING</option>
                                  <option value="NUMBER">NUMBER</option>
                                  <option value="BOOLEAN">BOOLEAN</option>
                                </Form.Select>
                              </Col>

                              {form.value_type === "STRING" && (
                                <Col md={4}>
                                  <Form.Control
                                    placeholder="Value"
                                    value={form.value_string}
                                    onChange={(e) =>
                                      updateResultForm(
                                        workItem.id,
                                        "value_string",
                                        e.target.value
                                      )
                                    }
                                  />
                                </Col>
                              )}

                              {form.value_type === "NUMBER" && (
                                <Col md={4}>
                                  <Form.Control
                                    type="number"
                                    placeholder="Value"
                                    value={form.value_number}
                                    onChange={(e) =>
                                      updateResultForm(
                                        workItem.id,
                                        "value_number",
                                        e.target.value
                                      )
                                    }
                                  />
                                </Col>
                              )}

                              {form.value_type === "BOOLEAN" && (
                                <Col md={4}>
                                  <Form.Select
                                    value={form.value_boolean}
                                    onChange={(e) =>
                                      updateResultForm(
                                        workItem.id,
                                        "value_boolean",
                                        e.target.value
                                      )
                                    }
                                  >
                                    <option value="true">True</option>
                                    <option value="false">False</option>
                                  </Form.Select>
                                </Col>
                              )}

                              <Col md={2}>
                                <Button
                                  variant="outline-dark"
                                  className="w-100"
                                  onClick={() => addResult(workItem.id)}
                                  disabled={!form.key}
                                >
                                  Save
                                </Button>
                              </Col>
                            </Row>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </Card.Body>
          </Card>
        </div>
      </div>

      <Card className="app-card">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <h5 className="section-title mb-0">Chain of Custody Timeline</h5>
            <div className="feed-meta">{sortedEvents.length} events</div>
          </div>

          {sortedEvents.length === 0 ? (
            <div className="empty-state">No timeline events yet.</div>
          ) : (
            <div className="d-grid gap-3">
              {sortedEvents.map((event) => (
                <div key={event.id} className="feed-item">
                  <div className="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-2">
                    <div>
                      <div className="d-flex align-items-center gap-2 flex-wrap">
                        <Badge bg={actionVariant(event.action)}>
                          {event.action}
                        </Badge>

                        <span className="fw-semibold">
                          {getTimelineTitle(event)}
                        </span>
                      </div>

                      <div className="feed-meta mt-1">
                        {event.actor_username
                          ? `By ${event.actor_username}`
                          : "System / Instrument"}
                      </div>
                    </div>

                    <div className="feed-meta">
                      {formatTimestamp(event.timestamp)}
                    </div>
                  </div>

                  {renderLineageLinks(event)}
                  {renderReason(event)}
                  {renderBeforeAfter(event)}

                  <details className="mt-3">
                    <summary className="feed-meta">Raw payload</summary>
                    <pre className="app-pre mt-2">
                      {JSON.stringify(event.payload, null, 2)}
                    </pre>
                  </details>
                </div>
              ))}
            </div>
          )}
        </Card.Body>
      </Card>
    </div>
  );
}