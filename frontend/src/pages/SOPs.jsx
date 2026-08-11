import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  Row,
  Spinner,
  Table,
} from "react-bootstrap";
import { apiGet, apiPatch, apiPatchForm, apiPost } from "../api";
import { isAdmin } from "../authz";

const ACCESS_ROLES = [
  { value: "tech", label: "Lab tech" },
  { value: "viewer", label: "Viewer" },
  { value: "qc_reviewer", label: "QC reviewer" },
];

function toDateTimeLocal(value) {
  const date = value ? new Date(value) : new Date();
  if (Number.isNaN(date.getTime())) return "";
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function formatTimestamp(value) {
  if (!value) return "-";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function emptyForm() {
  return {
    document_code: "",
    title: "",
    version: "1",
    section: "",
    content: "",
    status: "CURRENT",
    approved: false,
    project: "",
    allowed_group_names: [],
    effective_at: toDateTimeLocal(),
  };
}

function normalizeCollection(data) {
  return Array.isArray(data) ? data : data?.results || [];
}

async function loadAllPages(path) {
  const records = [];
  let nextPath = path;

  while (nextPath) {
    const data = await apiGet(nextPath);
    records.push(...normalizeCollection(data));

    if (!data?.next) break;
    const nextUrl = new URL(data.next, window.location.origin);
    nextPath = `${nextUrl.pathname}${nextUrl.search}`;
  }

  return records;
}

function accessText(document) {
  const roleNames = document.allowed_group_names || [];
  const roleText = roleNames.length ? roleNames.join(", ") : "All roles";
  return document.project_code
    ? `${document.project_code} · ${roleText}`
    : roleText;
}

export default function SOPs() {
  const [me, setMe] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [projects, setProjects] = useState([]);
  const [form, setForm] = useState(emptyForm);
  const [editingId, setEditingId] = useState(null);
  const [sourceFile, setSourceFile] = useState(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [success, setSuccess] = useState("");

  async function load() {
    setErr("");
    setLoading(true);

    try {
      const meData = await apiGet("/api/me/");
      setMe(meData);

      if (!isAdmin(meData)) {
        setDocuments([]);
        setProjects([]);
        return;
      }

      const [documentData, projectData] = await Promise.all([
        loadAllPages("/api/sop-documents/"),
        loadAllPages("/api/projects/"),
      ]);
      setDocuments(documentData);
      setProjects(projectData);
    } catch (error) {
      setErr(error.message || String(error));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // Loading is intentionally triggered once when the management page mounts.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, []);

  const userIsAdmin = isAdmin(me);

  const filteredDocuments = useMemo(() => {
    const query = search.trim().toLowerCase();
    return documents.filter((document) => {
      if (statusFilter !== "ALL" && document.status !== statusFilter) {
        return false;
      }

      if (!query) return true;
      return [
        document.document_code,
        document.title,
        document.version,
        document.section,
        document.project_code,
        document.uploaded_by_username,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query));
    });
  }, [documents, search, statusFilter]);

  const stats = useMemo(
    () => ({
      total: documents.length,
      current: documents.filter((document) => document.status === "CURRENT")
        .length,
      approved: documents.filter(
        (document) => document.status === "CURRENT" && document.approved
      ).length,
      archived: documents.filter((document) => document.status === "ARCHIVED")
        .length,
    }),
    [documents]
  );

  function updateField(field, value) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  function toggleRole(role) {
    setForm((current) => {
      const selected = current.allowed_group_names.includes(role);
      return {
        ...current,
        allowed_group_names: selected
          ? current.allowed_group_names.filter((item) => item !== role)
          : [...current.allowed_group_names, role],
      };
    });
  }

  function resetForm() {
    setForm(emptyForm());
    setEditingId(null);
    setSourceFile(null);
    setFileInputKey((value) => value + 1);
  }

  function startEdit(document) {
    setEditingId(document.id);
    setForm({
      document_code: document.document_code || "",
      title: document.title || "",
      version: document.version || "",
      section: document.section || "",
      content: document.content || "",
      status: document.status || "CURRENT",
      approved: Boolean(document.approved),
      project: document.project ? String(document.project) : "",
      allowed_group_names: document.allowed_group_names || [],
      effective_at: toDateTimeLocal(document.effective_at),
    });
    setSourceFile(null);
    setFileInputKey((value) => value + 1);
    setErr("");
    setSuccess("");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function submit(e) {
    e.preventDefault();
    setErr("");
    setSuccess("");

    if (!userIsAdmin) {
      setErr("Only Director/admin users can manage SOP documents.");
      return;
    }

    if (
      !form.document_code.trim() ||
      !form.title.trim() ||
      !form.version.trim() ||
      !form.section.trim() ||
      !form.content.trim() ||
      !form.effective_at
    ) {
      setErr("Document code, title, version, section, content, and effective date are required.");
      return;
    }

    const effectiveDate = new Date(form.effective_at);
    if (Number.isNaN(effectiveDate.getTime())) {
      setErr("Enter a valid effective date and time.");
      return;
    }

    const payload = {
      document_code: form.document_code.trim(),
      title: form.title.trim(),
      version: form.version.trim(),
      section: form.section.trim(),
      content: form.content.trim(),
      status: form.status,
      approved: Boolean(form.approved),
      project: form.project ? Number(form.project) : null,
      allowed_group_names: form.allowed_group_names,
      effective_at: effectiveDate.toISOString(),
    };

    setSaving(true);

    try {
      let document = editingId
        ? await apiPatch(`/api/sop-documents/${editingId}/`, payload)
        : await apiPost("/api/sop-documents/", payload);

      if (sourceFile) {
        const fileData = new FormData();
        fileData.append("source_file", sourceFile);
        document = await apiPatchForm(
          `/api/sop-documents/${document.id}/`,
          fileData
        );
      }

      setSuccess(
        editingId
          ? `SOP ${document.document_code} updated.`
          : `SOP ${document.document_code} created.`
      );
      resetForm();
      await load();
    } catch (error) {
      setErr(error.message || String(error));
    } finally {
      setSaving(false);
    }
  }

  async function setDocumentStatus(document, nextStatus) {
    const verb = nextStatus === "ARCHIVED" ? "Archive" : "Restore";
    if (!window.confirm(`${verb} SOP ${document.document_code} version ${document.version}?`)) {
      return;
    }

    setErr("");
    setSuccess("");

    try {
      await apiPatch(`/api/sop-documents/${document.id}/`, {
        status: nextStatus,
      });
      if (editingId === document.id) resetForm();
      setSuccess(`${document.document_code} ${verb.toLowerCase()}d.`);
      await load();
    } catch (error) {
      setErr(error.message || String(error));
    }
  }

  if (loading) {
    return (
      <div className="d-flex align-items-center gap-2">
        <Spinner animation="border" size="sm" />
        <span>Loading SOP management...</span>
      </div>
    );
  }

  if (!userIsAdmin) {
    return (
      <Alert variant="warning">
        Director/admin access is required to create or manage SOP documents.
      </Alert>
    );
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">SOP Management</h1>
          <p className="page-subtitle">
            Create, approve, scope, update, and archive the procedures used by
            the OpenLIMS Assistant.
          </p>
        </div>
        <div className="inline-actions">
          <Badge bg="dark">Director only</Badge>
          <Button variant="outline-dark" size="sm" onClick={load}>
            Refresh
          </Button>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}
      {success && <Alert variant="success">{success}</Alert>}

      <Row className="g-3 mb-4">
        {[
          ["All SOPs", stats.total, "dark"],
          ["Current", stats.current, "primary"],
          ["Approved & current", stats.approved, "success"],
          ["Archived", stats.archived, "secondary"],
        ].map(([label, value, color]) => (
          <Col sm={6} xl={3} key={label}>
            <Card className="app-card h-100">
              <Card.Body>
                <div className="feed-meta">{label}</div>
                <div className={`display-6 fw-semibold text-${color}`}>
                  {value}
                </div>
              </Card.Body>
            </Card>
          </Col>
        ))}
      </Row>

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="d-flex justify-content-between align-items-center gap-3 flex-wrap mb-3">
            <div>
              <h5 className="section-title mb-1">
                {editingId ? "Edit SOP" : "Create SOP"}
              </h5>
              <div className="text-muted">
                Only approved, current, effective SOPs are used in Assistant
                answers.
              </div>
            </div>
            {editingId && (
              <Button variant="outline-secondary" size="sm" onClick={resetForm}>
                Cancel edit
              </Button>
            )}
          </div>

          <Form onSubmit={submit}>
            <Row className="g-3">
              <Col md={4} lg={3}>
                <Form.Group>
                  <Form.Label>Document code</Form.Label>
                  <Form.Control
                    maxLength={64}
                    value={form.document_code}
                    onChange={(e) => updateField("document_code", e.target.value)}
                    placeholder="SOP-SAMPLE-001"
                    required
                  />
                </Form.Group>
              </Col>
              <Col md={8} lg={5}>
                <Form.Group>
                  <Form.Label>Title</Form.Label>
                  <Form.Control
                    maxLength={255}
                    value={form.title}
                    onChange={(e) => updateField("title", e.target.value)}
                    placeholder="Sample receipt"
                    required
                  />
                </Form.Group>
              </Col>
              <Col sm={6} md={4} lg={2}>
                <Form.Group>
                  <Form.Label>Version</Form.Label>
                  <Form.Control
                    maxLength={32}
                    value={form.version}
                    onChange={(e) => updateField("version", e.target.value)}
                    placeholder="3"
                    required
                  />
                </Form.Group>
              </Col>
              <Col sm={6} md={8} lg={2}>
                <Form.Group>
                  <Form.Label>Section</Form.Label>
                  <Form.Control
                    maxLength={128}
                    value={form.section}
                    onChange={(e) => updateField("section", e.target.value)}
                    placeholder="4.2"
                    required
                  />
                </Form.Group>
              </Col>

              <Col xs={12}>
                <Form.Group>
                  <Form.Label>Procedure content</Form.Label>
                  <Form.Control
                    as="textarea"
                    rows={7}
                    value={form.content}
                    onChange={(e) => updateField("content", e.target.value)}
                    placeholder="Enter the approved procedure text the Assistant may cite..."
                    required
                  />
                </Form.Group>
              </Col>

              <Col md={4}>
                <Form.Group>
                  <Form.Label>Effective date and time</Form.Label>
                  <Form.Control
                    type="datetime-local"
                    value={form.effective_at}
                    onChange={(e) => updateField("effective_at", e.target.value)}
                    required
                  />
                </Form.Group>
              </Col>
              <Col md={4}>
                <Form.Group>
                  <Form.Label>Project access</Form.Label>
                  <Form.Select
                    value={form.project}
                    onChange={(e) => updateField("project", e.target.value)}
                  >
                    <option value="">All projects</option>
                    {projects.map((project) => (
                      <option key={project.id} value={project.id}>
                        {project.code} — {project.name}
                      </option>
                    ))}
                  </Form.Select>
                </Form.Group>
              </Col>
              <Col md={4}>
                <Form.Group>
                  <Form.Label>Status</Form.Label>
                  <Form.Select
                    value={form.status}
                    onChange={(e) => updateField("status", e.target.value)}
                  >
                    <option value="CURRENT">Current</option>
                    <option value="ARCHIVED">Archived</option>
                  </Form.Select>
                </Form.Group>
              </Col>

              <Col md={6}>
                <Form.Group>
                  <Form.Label>Allowed roles</Form.Label>
                  <div className="d-flex flex-wrap gap-3 pt-2">
                    {ACCESS_ROLES.map((role) => (
                      <Form.Check
                        key={role.value}
                        type="checkbox"
                        id={`sop-role-${role.value}`}
                        label={role.label}
                        checked={form.allowed_group_names.includes(role.value)}
                        onChange={() => toggleRole(role.value)}
                      />
                    ))}
                  </div>
                  <div className="form-text">
                    Leave all unchecked to make the SOP visible to every role
                    with project access.
                  </div>
                </Form.Group>
              </Col>
              <Col md={6}>
                <Form.Group>
                  <Form.Label>Source file (optional)</Form.Label>
                  <Form.Control
                    key={fileInputKey}
                    type="file"
                    onChange={(e) => setSourceFile(e.target.files?.[0] || null)}
                  />
                  <div className="form-text">
                    Attach the approved source document. Procedure content must
                    still be entered above for Assistant answers.
                  </div>
                </Form.Group>
              </Col>

              <Col xs={12}>
                <div className="d-flex justify-content-between align-items-center gap-3 flex-wrap border-top pt-3">
                  <Form.Check
                    type="switch"
                    id="sop-approved"
                    label="Approved for Assistant answers"
                    checked={form.approved}
                    onChange={(e) => updateField("approved", e.target.checked)}
                  />
                  <Button type="submit" variant="dark" disabled={saving}>
                    {saving
                      ? "Saving..."
                      : editingId
                        ? "Save SOP changes"
                        : "Create SOP"}
                  </Button>
                </div>
              </Col>
            </Row>
          </Form>
        </Card.Body>
      </Card>

      <Card className="app-card">
        <Card.Body>
          <div className="d-flex justify-content-between align-items-end gap-3 flex-wrap mb-3">
            <div>
              <h5 className="section-title mb-1">SOP library</h5>
              <div className="text-muted">
                {filteredDocuments.length} of {documents.length} documents shown
              </div>
            </div>
            <div className="d-flex gap-2 flex-wrap">
              <Form.Control
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search SOPs..."
                style={{ minWidth: "240px" }}
              />
              <Form.Select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                style={{ width: "160px" }}
              >
                <option value="ALL">All statuses</option>
                <option value="CURRENT">Current</option>
                <option value="ARCHIVED">Archived</option>
              </Form.Select>
            </div>
          </div>

          <div className="table-responsive">
            <Table hover align="middle" className="mb-0">
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Version / section</th>
                  <th>Access</th>
                  <th>Status</th>
                  <th>Effective</th>
                  <th>Owner</th>
                  <th className="text-end">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredDocuments.map((document) => (
                  <tr key={document.id}>
                    <td>
                      <div className="fw-semibold">{document.document_code}</div>
                      <div className="text-muted small">{document.title}</div>
                      {document.source_file && (
                        <a
                          href={document.source_file}
                          target="_blank"
                          rel="noreferrer"
                          className="small"
                        >
                          Open source file
                        </a>
                      )}
                    </td>
                    <td>
                      <div>Version {document.version}</div>
                      <div className="text-muted small">{document.section}</div>
                    </td>
                    <td className="small">{accessText(document)}</td>
                    <td>
                      <div className="d-flex gap-1 flex-wrap">
                        <Badge
                          bg={document.status === "CURRENT" ? "primary" : "secondary"}
                        >
                          {document.status === "CURRENT" ? "Current" : "Archived"}
                        </Badge>
                        <Badge bg={document.approved ? "success" : "warning"}>
                          {document.approved ? "Approved" : "Not approved"}
                        </Badge>
                      </div>
                    </td>
                    <td className="small">{formatTimestamp(document.effective_at)}</td>
                    <td className="small">
                      <div>{document.uploaded_by_username || "-"}</div>
                      <div className="text-muted">{formatTimestamp(document.updated_at)}</div>
                    </td>
                    <td>
                      <div className="d-flex gap-2 justify-content-end">
                        <Button
                          variant="outline-dark"
                          size="sm"
                          onClick={() => startEdit(document)}
                        >
                          Edit
                        </Button>
                        <Button
                          variant={
                            document.status === "CURRENT"
                              ? "outline-secondary"
                              : "outline-primary"
                          }
                          size="sm"
                          onClick={() =>
                            setDocumentStatus(
                              document,
                              document.status === "CURRENT" ? "ARCHIVED" : "CURRENT"
                            )
                          }
                        >
                          {document.status === "CURRENT" ? "Archive" : "Restore"}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
                {filteredDocuments.length === 0 && (
                  <tr>
                    <td colSpan={7} className="text-center text-muted py-5">
                      No SOP documents match the current filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </Table>
          </div>
        </Card.Body>
      </Card>
    </div>
  );
}
