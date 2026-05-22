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

function actionVariant(action) {
  switch (action) {
    case "CREATED":
      return "success";
    case "UPDATED":
      return "primary";
    case "DELETED":
      return "danger";
    case "STATUS_CHANGED":
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

  if (event.action === "STATUS_CHANGED") {
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
  const [me, setMe] = useState(null);

  const [err, setErr] = useState("");
  const [success, setSuccess] = useState("");

  const [newWorkItemName, setNewWorkItemName] = useState("");
  const [newWorkItemNotes, setNewWorkItemNotes] = useState("");
  const [resultForms, setResultForms] = useState({});

  const [selectedAttachmentFile, setSelectedAttachmentFile] = useState(null);
  const [selectedContainer, setSelectedContainer] = useState("");

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
        meData,
      ] = await Promise.all([
        apiGet(`/api/samples/${id}/`),
        apiGet(`/api/samples/${id}/allowed-transitions/`),
        apiGet(`/api/events/`),
        apiGet(`/api/work-items/?sample=${id}`),
        apiGet("/api/containers/"),
        apiGet(`/api/sample-attachments/?sample=${id}`),
        apiGet(`/api/sequences/?sample=${id}`),
        apiGet("/api/me/"),
      ]);

      const eventList = eventsData.results || eventsData || [];
      const workItemList = workItemsData.results || workItemsData || [];
      const containerList = containersData.results || containersData || [];
      const attachmentList = attachmentsData.results || attachmentsData || [];
      const sequenceList = sequencesData.results || sequencesData || [];

      setSample(sampleData);
      setAllowed(transitionData.allowed_transitions || []);
      setWorkItems(workItemList);
      setContainers(containerList);
      setSelectedContainer(sampleData.container || "");
      setSampleAttachments(attachmentList);
      setSampleSequences(sequenceList);
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
  }, [id]);

  async function doTransition(newStatus) {
    if (!userCanWrite) return;

    setErr("");
    setSuccess("");

    try {
      await apiPost(`/api/samples/${id}/transition/`, {
        new_status: newStatus,
      });

      setSuccess(`Sample moved to ${newStatus}.`);
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

  const projectId = sample?.project || sample?.project_id;
  const userCanWrite = canWrite(me);
  const readOnlyText = readOnlyMessage(me);

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
            Complete sample record with workflow, results, storage, files,
            sequences, and chain of custody.
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
            <div className="metric-label">Attachments</div>
            <div className="metric-value">{sampleAttachments.length}</div>
            <div className="metric-note">Uploaded files</div>
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
                <h5 className="section-title">Status Actions</h5>

                <div className="inline-actions">
                  {allowed.length === 0 ? (
                    <span className="empty-state">No further transitions.</span>
                  ) : (
                    allowed.map((status) => (
                      <Button
                        key={status}
                        variant="dark"
                        size="sm"
                        onClick={() => doTransition(status)}
                      >
                        Move to {status}
                      </Button>
                    ))
                  )}
                </div>
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
                          </div>

                          <Badge bg={workItemVariant(workItem.status)}>
                            {workItem.status}
                          </Badge>
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