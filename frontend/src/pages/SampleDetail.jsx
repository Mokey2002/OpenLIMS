import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  Row,
  Spinner,
} from "react-bootstrap";
import { apiGet, apiPost,apiPostForm,apiPatch } from "../api";


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
    default:
      return "secondary";
  }
}

function formatTimestamp(ts) {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function describeEvent(event) {
  if (event.action === "CONTAINER_ASSIGNED") {
  return `Container changed from ${event.payload?.old_container_code || "Unassigned"} to ${event.payload?.new_container_code || "Unassigned"}`;
   }

  if (event.action === "STATUS_CHANGED") {
    return `Status changed from ${event.payload?.old_status} to ${event.payload?.new_status}`;
  }
  if (event.action === "CREATED") {
    return `${event.entity_type} was created`;
  }
  if (event.action === "UPDATED") {
    return `${event.entity_type} was updated`;
  }
  if (event.action === "DELETED") {
    return `${event.entity_type} was deleted`;
  }
  return event.action;
}

export default function SampleDetail() {
  const { id } = useParams();
  

  const [attachments, setAttachments] = useState([]);
  const [selectedFile, setSelectedFile] = useState(null);

  const [containers, setContainers] = useState([]);
  const [selectedContainer, setSelectedContainer] = useState("");
  const [sample, setSample] = useState(null);
  const [allowed, setAllowed] = useState([]);
  const [events, setEvents] = useState([]);
  const [workItems, setWorkItems] = useState([]);

  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const [newWorkItemName, setNewWorkItemName] = useState("");
  const [newWorkItemNotes, setNewWorkItemNotes] = useState("");

  const [resultForms, setResultForms] = useState({});

  async function load() {
    setLoading(true);
    setErr("");

    try {
      const [s, t, ev, wi,att,containersData] = await Promise.all([
        apiGet(`/api/samples/${id}/`),
        apiGet(`/api/samples/${id}/allowed-transitions/`),
        apiGet(`/api/events/`),
        apiGet(`/api/work-items/?sample=${id}`),
	apiGet(`/api/attachments/?sample=${id}`),
	apiGet('/api/containers/'),

      ]);
      
      setContainers(containersData)
      setSelectedContainer(s.container || "")
      setAttachments(att)
      setSample(s);
      setAllowed(t.allowed_transitions || [])

      const sampleEvents = ev.filter(
        (event) =>
          event.entity_type === "Sample" &&
          (
            String(event.entity_id) === String(id) ||
            String(event.payload?.sample_id) === String(id)
          )
      );

      setEvents(sampleEvents);
      setWorkItems(wi);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [id]);

async function uploadAttachment(e) {
  e.preventDefault();
  if (!selectedFile) return;

  setErr("");

  try {
    const formData = new FormData();
    formData.append("sample", id);
    formData.append("file", selectedFile);

    await apiPostForm("/api/attachments/", formData);
    setSelectedFile(null);
    await load();
  } catch (e) {
    setErr(e.message || String(e));
  }
}

  async function doTransition(newStatus) {
    try {
      await apiPost(`/api/samples/${id}/transition/`, {
        new_status: newStatus,
      });
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

async function assignContainer(e) {
  e.preventDefault();
  setErr("");

  try {
    await apiPatch(`/api/samples/${id}/`, {
      container: selectedContainer ? Number(selectedContainer) : null,
    });
    await load();
  } catch (e) {
    setErr(e.message || String(e));
  }
}
  async function createWorkItem(e) {
    e.preventDefault();
    setErr("");

    try {
      await apiPost("/api/work-items/", {
        sample: Number(id),
        name: newWorkItemName,
        status: "PENDING",
        notes: newWorkItemNotes,
      });

      setNewWorkItemName("");
      setNewWorkItemNotes("");
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
    const form = resultForms[workItemId] || {};
    setErr("");

    try {
      const payload = {
        work_item: workItemId,
        key: form.key,
        value_type: form.value_type,
      };

      if (form.value_type === "STRING") {
        payload.value_string = form.value_string || "";
      } else if (form.value_type === "NUMBER") {
        payload.value_number = form.value_number ? Number(form.value_number) : null;
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

  if (loading) return <Spinner animation="border" />;

  return (
    <div className="w-100">
      <h2 className="mb-3">Sample Detail</h2>

      {err && <Alert variant="danger">{err}</Alert>}

      {sample && (
        <>
          <Card className="shadow-sm border-0 mb-4">
            <Card.Body>
              <h5>{sample.sample_id}</h5>

              <div className="mb-3">
                Status:{" "}
                <Badge bg={statusVariant(sample.status)}>
                  {sample.status}
                </Badge>
              </div>

		<div className="mb-2">
  <strong>Container:</strong> {sample.container_code || "Unassigned"}
</div>

<div className="mb-3">
  <strong>Location:</strong> {sample.location_name || "Unassigned"}
</div>

              <div className="d-flex gap-2 flex-wrap">
                {allowed.length === 0 ? (
                  <span>No further transitions</span>
                ) : (
                  allowed.map((s) => (
                    <Button
                      key={s}
                      variant="dark"
                      size="sm"
                      onClick={() => doTransition(s)}
                    >
                      Move to {s}
                    </Button>
                  ))
                )}
              </div>
            </Card.Body>
          </Card>

          <Card className="shadow-sm border-0 mb-4">
            <Card.Body>
              <h5 className="mb-3">Work Items</h5>

              <Form onSubmit={createWorkItem} className="mb-4">
                <Row className="g-2">
                  <Col md={4}>
                    <Form.Control
                      placeholder="Work item name (e.g. DNA Extraction)"
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
                    <Button type="submit" variant="dark" className="w-100">
                      Add
                    </Button>
                  </Col>
                </Row>
              </Form>

              {workItems.length === 0 ? (
                <Alert variant="light" className="mb-0">
                  No work items yet.
                </Alert>
              ) : (
                <div className="d-grid gap-3">
                  {workItems.map((wi) => {
                    const form = resultForms[wi.id] || {
                      key: "",
                      value_type: "STRING",
                      value_string: "",
                      value_number: "",
                      value_boolean: "true",
                    };

                    return (
                      <Card key={wi.id} className="bg-light border-0">
                        <Card.Body>
                          <div className="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-2">
                            <div>
                              <div className="fw-semibold">{wi.name}</div>
                              <div className="text-muted small">{wi.notes}</div>
                            </div>
                            <Badge bg={workItemVariant(wi.status)}>
                              {wi.status}
                            </Badge>
                          </div>

                          <div className="mb-3">
                            <div className="fw-semibold mb-2">Results</div>
                            {wi.results?.length === 0 ? (
                              <div className="text-muted small">No results yet.</div>
                            ) : (
                              <ul className="mb-0">
                                {wi.results.map((r) => (
                                  <li key={r.id}>
                                    <strong>{r.key}</strong>: {String(r.value)}
                                  </li>
                                ))}
                              </ul>
                            )}
                          </div>

                          <div className="border-top pt-3">
                            <div className="fw-semibold mb-2">Add Result</div>
                            <Row className="g-2">
                              <Col md={3}>
                                <Form.Control
                                  placeholder="Key"
                                  value={form.key}
                                  onChange={(e) =>
                                    updateResultForm(wi.id, "key", e.target.value)
                                  }
                                />
                              </Col>
                              <Col md={3}>
                                <Form.Select
                                  value={form.value_type}
                                  onChange={(e) =>
                                    updateResultForm(wi.id, "value_type", e.target.value)
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
                                      updateResultForm(wi.id, "value_string", e.target.value)
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
                                      updateResultForm(wi.id, "value_number", e.target.value)
                                    }
                                  />
                                </Col>
                              )}

                              {form.value_type === "BOOLEAN" && (
                                <Col md={4}>
                                  <Form.Select
                                    value={form.value_boolean}
                                    onChange={(e) =>
                                      updateResultForm(wi.id, "value_boolean", e.target.value)
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
                                  onClick={() => addResult(wi.id)}
                                >
                                  Save
                                </Button>
                              </Col>
                            </Row>
                          </div>
                        </Card.Body>
                      </Card>
                    );
                  })}
                </div>
              )}
            </Card.Body>
          </Card>
<Card className="shadow-sm border-0 mb-4">
  <Card.Body>
    <h5 className="mb-3">Storage Assignment</h5>

    <Form onSubmit={assignContainer}>
      <Row className="g-2 align-items-center">
        <Col md={9}>
          <Form.Select
            value={selectedContainer}
            onChange={(e) => setSelectedContainer(e.target.value)}
          >
            <option value="">Unassigned</option>
            {containers.map((c) => (
              <option key={c.id} value={c.id}>
                {c.container_id} ({c.kind}) — {c.location}
              </option>
            ))}
          </Form.Select>
        </Col>
        <Col md={3}>
          <Button type="submit" variant="dark" className="w-100">
            Save Container
          </Button>
        </Col>
      </Row>
    </Form>
  </Card.Body>
</Card>
<Card className="shadow-sm border-0 mb-4">
  <Card.Body>
    <h5 className="mb-3">Attachments</h5>

    <Form onSubmit={uploadAttachment} className="mb-4">
      <Row className="g-2 align-items-center">
        <Col md={9}>
          <Form.Control
            type="file"
            onChange={(e) => setSelectedFile(e.target.files?.[0] || null)}
          />
        </Col>
        <Col md={3}>
          <Button type="submit" variant="dark" className="w-100">
            Upload
          </Button>
        </Col>
      </Row>
    </Form>

    {attachments.length === 0 ? (
      <Alert variant="light" className="mb-0">
        No attachments yet.
      </Alert>
    ) : (
      <ul className="mb-0">
        {attachments.map((att) => (
          <li key={att.id}>
            <a
              href={`http://localhost:8000${att.file}`}
              target="_blank"
              rel="noreferrer"
            >
              {att.filename}
            </a>{" "}
            <span className="text-muted small">
              ({new Date(att.uploaded_at).toLocaleString()})
            </span>
          </li>
        ))}
      </ul>
    )}
  </Card.Body>
</Card>
          <Card className="shadow-sm border-0">
            <Card.Body>
              <h5 className="mb-3">Timeline</h5>

              {sortedEvents.length === 0 ? (
                <Alert variant="light" className="mb-0">
                  No events found for this sample.
                </Alert>
              ) : (
                <div className="d-grid gap-3">
                  {sortedEvents.map((event) => (
                    <div
                      key={event.id}
                      className="border rounded p-3 bg-light"
                    >
                      <div className="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-2">
                        <div className="d-flex align-items-center gap-2 flex-wrap">
                          <Badge bg={actionVariant(event.action)}>
                            {event.action}
                          </Badge>
                          <span className="fw-semibold">
                            {describeEvent(event)}
                          </span>
                        </div>

                        <small className="text-muted">
                          {formatTimestamp(event.timestamp)}
                          {event.actor_username ? ` • by ${event.actor_username}` : ""}
                        </small>
                      </div>

                      <pre
                        className="mb-0 small"
                        style={{
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                        }}
                      >
                        {JSON.stringify(event.payload, null, 2)}
                      </pre>
                    </div>
                  ))}
                </div>
              )}
            </Card.Body>
          </Card>
        </>
      )}
    </div>
  );
}
