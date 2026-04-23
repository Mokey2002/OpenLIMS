import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { Alert, Badge, Button, Card, Col, Form, Row } from "react-bootstrap";
import { apiGet, apiPatch, apiPost, apiPostForm } from "../api";

function statusVariant(status) {
  switch (status) {
    case "RECEIVED": return "secondary";
    case "IN_PROGRESS": return "primary";
    case "QC": return "warning";
    case "REPORTED": return "success";
    case "ARCHIVED": return "dark";
    default: return "light";
  }
}
function workItemVariant(status) {
  switch (status) {
    case "PENDING": return "secondary";
    case "IN_PROGRESS": return "primary";
    case "COMPLETED": return "success";
    case "FAILED": return "danger";
    default: return "light";
  }
}
function actionVariant(action) {
  switch (action) {
    case "CREATED": return "success";
    case "UPDATED": return "primary";
    case "DELETED": return "danger";
    case "STATUS_CHANGED": return "warning";
    case "CONTAINER_ASSIGNED": return "info";
    case "ATTACHMENT_UPLOADED": return "info";
    case "RESULTS_IMPORTED": return "dark";
    default: return "secondary";
  }
}
function formatTimestamp(ts) { try { return new Date(ts).toLocaleString(); } catch { return ts; } }

export default function SampleDetail() {
  const { id } = useParams();
  const [sample, setSample] = useState(null);
  const [allowed, setAllowed] = useState([]);
  const [events, setEvents] = useState([]);
  const [workItems, setWorkItems] = useState([]);
  const [containers, setContainers] = useState([]);
  const [sampleAttachments, setSampleAttachments] = useState([]);
  const [err, setErr] = useState("");
  const [newWorkItemName, setNewWorkItemName] = useState("");
  const [newWorkItemNotes, setNewWorkItemNotes] = useState("");
  const [resultForms, setResultForms] = useState({});
  const [selectedAttachmentFile, setSelectedAttachmentFile] = useState(null);
  const [selectedContainer, setSelectedContainer] = useState("");

  async function load() {
    setErr("");
    try {
      const [s, t, ev, wi, containersData, sampleAtts] = await Promise.all([
        apiGet(`/api/samples/${id}/`),
        apiGet(`/api/samples/${id}/allowed-transitions/`),
        apiGet(`/api/events/`),
        apiGet(`/api/work-items/?sample=${id}`),
        apiGet("/api/containers/"),
        apiGet(`/api/sample-attachments/?sample=${id}`),
      ]);

      const eventList = ev.results || ev || [];
      const workItemList = wi.results || wi || [];
      const containerList = containersData.results || containersData || [];
      const attachmentList = sampleAtts.results || sampleAtts || [];

      setSample(s);
      setAllowed(t.allowed_transitions || []);
      setWorkItems(workItemList);
      setContainers(containerList);
      setSelectedContainer(s.container || "");
      setSampleAttachments(attachmentList);

      const sampleEvents = eventList.filter(
        (event) => event.entity_type === "Sample" && (String(event.entity_id) === String(id) || String(event.payload?.sample_id) === String(id))
      );
      setEvents(sampleEvents);
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  useEffect(() => { load(); }, [id]);

  async function doTransition(newStatus) {
    try {
      await apiPost(`/api/samples/${id}/transition/`, { new_status: newStatus });
      await load();
    } catch (e) { setErr(e.message || String(e)); }
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
    } catch (e) { setErr(e.message || String(e)); }
  }

  function updateResultForm(workItemId, field, value) {
    setResultForms((prev) => ({
      ...prev,
      [workItemId]: { ...(prev[workItemId] || {}), [field]: value },
    }));
  }

  async function addResult(workItemId) {
    const form = resultForms[workItemId] || {};
    setErr("");
    try {
      const payload = { work_item: workItemId, key: form.key, value_type: form.value_type };
      if (form.value_type === "STRING") payload.value_string = form.value_string || "";
      else if (form.value_type === "NUMBER") payload.value_number = form.value_number ? Number(form.value_number) : null;
      else if (form.value_type === "BOOLEAN") payload.value_boolean = form.value_boolean === "true";

      await apiPost("/api/results/", payload);

      setResultForms((prev) => ({
        ...prev,
        [workItemId]: { key: "", value_type: "STRING", value_string: "", value_number: "", value_boolean: "true" },
      }));

      await load();
    } catch (e) { setErr(e.message || String(e)); }
  }

  async function uploadSampleAttachment(e) {
    e.preventDefault();
    if (!selectedAttachmentFile) return;
    setErr("");
    try {
      const formData = new FormData();
      formData.append("sample", id);
      formData.append("file", selectedAttachmentFile);
      await apiPostForm("/api/sample-attachments/", formData);
      setSelectedAttachmentFile(null);
      await load();
    } catch (e) { setErr(e.message || String(e)); }
  }

  async function assignContainer(e) {
    e.preventDefault();
    setErr("");
    try {
      await apiPatch(`/api/samples/${id}/`, { container: selectedContainer ? Number(selectedContainer) : null });
      await load();
    } catch (e) { setErr(e.message || String(e)); }
  }

  const sortedEvents = useMemo(() => [...events].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp)), [events]);

  return (
    <div className="w-100">
      {sample && (
        <>
          <div className="page-header">
            <div>
              <h1 className="page-title">{sample.sample_id}</h1>
              <p className="page-subtitle">Detailed sample record, work items, files, and timeline.</p>
            </div>
            <Badge bg={statusVariant(sample.status)}>{sample.status}</Badge>
          </div>

          {err && <Alert variant="danger">{err}</Alert>}

          <Card className="app-card mb-4">
            <Card.Body>
              <div className="row g-4">
                <div className="col-lg-8">
                  <div className="soft-card">
                    <div className="mb-2"><span className="feed-meta">Project</span><div>{sample.project_code || "Unassigned"}</div></div>
                    <div className="mb-2"><span className="feed-meta">Container</span><div>{sample.container_code || "Unassigned"}</div></div>
                    <div><span className="feed-meta">Location</span><div>{sample.location_name || "Unassigned"}</div></div>
                  </div>
                </div>
                <div className="col-lg-4">
                  <div className="feed-meta mb-2">Status Actions</div>
                  <div className="inline-actions">
                    {allowed.length === 0 ? <span className="empty-state">No further transitions</span> : allowed.map((s) => (
                      <Button key={s} variant="dark" size="sm" onClick={() => doTransition(s)}>Move to {s}</Button>
                    ))}
                  </div>
                </div>
              </div>
            </Card.Body>
          </Card>

          <Card className="app-card mb-4">
            <Card.Body>
              <h5 className="section-title">Storage Assignment</h5>
              <Form onSubmit={assignContainer}>
                <Row className="g-2 align-items-center">
                  <Col md={9}>
                    <Form.Select value={selectedContainer} onChange={(e) => setSelectedContainer(e.target.value)}>
                      <option value="">Unassigned</option>
                      {containers.map((c) => (
                        <option key={c.id} value={c.id}>{c.container_id} ({c.kind}) — {c.location_name || c.location}</option>
                      ))}
                    </Form.Select>
                  </Col>
                  <Col md={3}>
                    <Button type="submit" variant="dark" className="w-100">Save Container</Button>
                  </Col>
                </Row>
              </Form>
            </Card.Body>
          </Card>

          <Card className="app-card mb-4">
            <Card.Body>
              <h5 className="section-title">Work Items</h5>
              <Form onSubmit={createWorkItem} className="mb-4">
                <Row className="g-2">
                  <Col md={4}><Form.Control placeholder="Work item name" value={newWorkItemName} onChange={(e) => setNewWorkItemName(e.target.value)} /></Col>
                  <Col md={6}><Form.Control placeholder="Notes" value={newWorkItemNotes} onChange={(e) => setNewWorkItemNotes(e.target.value)} /></Col>
                  <Col md={2}><Button type="submit" variant="dark" className="w-100">Add</Button></Col>
                </Row>
              </Form>

              {workItems.length === 0 ? (
                <div className="empty-state">No work items yet.</div>
              ) : (
                <div className="d-grid gap-3">
                  {workItems.map((wi) => {
                    const form = resultForms[wi.id] || { key: "", value_type: "STRING", value_string: "", value_number: "", value_boolean: "true" };
                    return (
                      <div key={wi.id} className="feed-item">
                        <div className="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-3">
                          <div>
                            <div className="fw-semibold">{wi.name}</div>
                            <div className="feed-meta">{wi.notes}</div>
                          </div>
                          <Badge bg={workItemVariant(wi.status)}>{wi.status}</Badge>
                        </div>

                        <div className="mb-3">
                          <div className="feed-meta mb-2">Results</div>
                          {wi.results?.length === 0 ? (
                            <div className="empty-state">No results yet.</div>
                          ) : (
                            <ul className="mb-0">
                              {wi.results.map((r) => <li key={r.id}><strong>{r.key}</strong>: {String(r.value)}</li>)}
                            </ul>
                          )}
                        </div>

                        <div className="soft-card">
                          <div className="feed-meta mb-2">Add Result</div>
                          <Row className="g-2">
                            <Col md={3}>
                              <Form.Control placeholder="Key" value={form.key} onChange={(e) => updateResultForm(wi.id, "key", e.target.value)} />
                            </Col>
                            <Col md={3}>
                              <Form.Select value={form.value_type} onChange={(e) => updateResultForm(wi.id, "value_type", e.target.value)}>
                                <option value="STRING">STRING</option>
                                <option value="NUMBER">NUMBER</option>
                                <option value="BOOLEAN">BOOLEAN</option>
                              </Form.Select>
                            </Col>

                            {form.value_type === "STRING" && (
                              <Col md={4}><Form.Control placeholder="Value" value={form.value_string} onChange={(e) => updateResultForm(wi.id, "value_string", e.target.value)} /></Col>
                            )}
                            {form.value_type === "NUMBER" && (
                              <Col md={4}><Form.Control type="number" placeholder="Value" value={form.value_number} onChange={(e) => updateResultForm(wi.id, "value_number", e.target.value)} /></Col>
                            )}
                            {form.value_type === "BOOLEAN" && (
                              <Col md={4}>
                                <Form.Select value={form.value_boolean} onChange={(e) => updateResultForm(wi.id, "value_boolean", e.target.value)}>
                                  <option value="true">True</option>
                                  <option value="false">False</option>
                                </Form.Select>
                              </Col>
                            )}

                            <Col md={2}><Button variant="outline-dark" className="w-100" onClick={() => addResult(wi.id)}>Save</Button></Col>
                          </Row>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </Card.Body>
          </Card>

          <div className="row g-4 mb-4">
            <div className="col-lg-5">
              <Card className="app-card h-100">
                <Card.Body>
                  <h5 className="section-title">Sample Attachments</h5>
                  <Form onSubmit={uploadSampleAttachment} className="mb-4">
                    <Row className="g-2 align-items-center">
                      <Col md={8}><Form.Control type="file" onChange={(e) => setSelectedAttachmentFile(e.target.files?.[0] || null)} /></Col>
                      <Col md={4}><Button type="submit" variant="dark" className="w-100">Upload</Button></Col>
                    </Row>
                  </Form>

                  {sampleAttachments.length === 0 ? (
                    <div className="empty-state">No sample attachments yet.</div>
                  ) : (
                    <ul className="mb-0">
                      {sampleAttachments.map((att) => (
                        <li key={att.id}>
                          <a href={`http://localhost:8000${att.file}`} target="_blank" rel="noreferrer">{att.filename}</a>{" "}
                          <span className="feed-meta">— uploaded by {att.uploaded_by_username || "Unknown"} on {new Date(att.uploaded_at).toLocaleString()}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card.Body>
              </Card>
            </div>

            <div className="col-lg-7">
              <Card className="app-card h-100">
                <Card.Body>
                  <h5 className="section-title">Timeline</h5>
                  {sortedEvents.length === 0 ? (
                    <div className="empty-state">No events found for this sample.</div>
                  ) : (
                    <div className="d-grid gap-3">
                      {sortedEvents.map((event) => (
                        <div key={event.id} className="feed-item">
                          <div className="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-2">
                            <div className="d-flex align-items-center gap-2 flex-wrap">
                              <Badge bg={actionVariant(event.action)}>{event.action}</Badge>
                              <span className="fw-semibold">{event.entity_type} #{event.entity_id}</span>
                            </div>
                            <div className="feed-meta">{formatTimestamp(event.timestamp)}{event.actor_username ? ` • by ${event.actor_username}` : ""}</div>
                          </div>
                          <pre className="app-pre">{JSON.stringify(event.payload, null, 2)}</pre>
                        </div>
                      ))}
                    </div>
                  )}
                </Card.Body>
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
