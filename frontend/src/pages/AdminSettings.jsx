import { useEffect, useState } from "react";
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
import { apiGet, apiPatch, apiPost } from "../api";
import { isAdmin, readOnlyMessage } from "../authz";

function formatTimestamp(value) {
  if (!value) return "-";

  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function parseExtensionText(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean)
    .map((item) => (item.startsWith(".") ? item : `.${item}`));
}

export default function AdminSettings() {
  const [me, setMe] = useState(null);
  const [settings, setSettings] = useState(null);
  const [form, setForm] = useState(null);

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);

  const [err, setErr] = useState("");
  const [success, setSuccess] = useState("");

  async function load() {
    setErr("");
    setLoading(true);

    try {
      const [meData, settingsData] = await Promise.all([
        apiGet("/api/me/"),
        apiGet("/api/system-settings/"),
      ]);

      setMe(meData);
      setSettings(settingsData);
      setForm({
        ...settingsData,
        allowed_fasta_extensions_text: (
          settingsData.allowed_fasta_extensions || []
        ).join(", "),
      });
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const userIsAdmin = isAdmin(me);
  const readOnlyText = !userIsAdmin
    ? readOnlyMessage(me) || "Only admin/director users can update system settings."
    : "";

  function updateField(field, value) {
    setForm((current) => ({
      ...current,
      [field]: value,
    }));
  }

  async function saveSettings(e) {
    e.preventDefault();

    setErr("");
    setSuccess("");

    if (!userIsAdmin) {
      setErr("Only admin/director users can update system settings.");
      return;
    }

    setSaving(true);

    try {
      const payload = {
        lab_name: form.lab_name,
        organization_name: form.organization_name,
        default_timezone: form.default_timezone,
        default_sample_status: form.default_sample_status,
        max_upload_size_mb: Number(form.max_upload_size_mb),
        require_import_preview: Boolean(form.require_import_preview),
        allowed_fasta_extensions: parseExtensionText(
          form.allowed_fasta_extensions_text
        ),
        alignments_enabled: Boolean(form.alignments_enabled),
        max_sequences_per_alignment: Number(form.max_sequences_per_alignment),
        max_sequence_length: Number(form.max_sequence_length),
        viewer_read_only: Boolean(form.viewer_read_only),
        require_audit_reason: Boolean(form.require_audit_reason),
      };

      const data = await apiPatch("/api/system-settings/1/", payload);

      setSettings(data);
      setForm({
        ...data,
        allowed_fasta_extensions_text: (
          data.allowed_fasta_extensions || []
        ).join(", "),
      });
      setSuccess("System settings updated.");
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  async function resetDefaults() {
    setErr("");
    setSuccess("");

    if (!userIsAdmin) {
      setErr("Only admin/director users can reset system settings.");
      return;
    }

    setResetting(true);

    try {
      const data = await apiPost("/api/system-settings/reset-defaults/", {});

      setSettings(data);
      setForm({
        ...data,
        allowed_fasta_extensions_text: (
          data.allowed_fasta_extensions || []
        ).join(", "),
      });
      setSuccess("System settings reset to defaults.");
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setResetting(false);
    }
  }

  if (loading) {
    return (
      <div className="d-flex align-items-center gap-2">
        <Spinner animation="border" size="sm" />
        <span>Loading settings...</span>
      </div>
    );
  }

  if (!form) {
    return <Alert variant="danger">Unable to load system settings.</Alert>;
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Admin Settings</h1>
          <p className="page-subtitle">
            Configure OpenLIMS defaults, import limits, sequence alignment
            behavior, and security settings.
          </p>
        </div>

        <div className="inline-actions">
          <Badge bg={userIsAdmin ? "dark" : "secondary"}>
            {userIsAdmin ? "Admin editable" : "Read only"}
          </Badge>

          <Button variant="outline-dark" size="sm" onClick={load}>
            Refresh
          </Button>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}
      {success && <Alert variant="success">{success}</Alert>}
      {readOnlyText && <Alert variant="info">{readOnlyText}</Alert>}

      <Form onSubmit={saveSettings}>
        <Row className="g-4">
          <Col lg={6}>
            <Card className="app-card h-100">
              <Card.Body>
                <h5 className="section-title">General Settings</h5>

                <Form.Group className="mb-3">
                  <Form.Label>Lab Name</Form.Label>
                  <Form.Control
                    value={form.lab_name || ""}
                    disabled={!userIsAdmin}
                    onChange={(e) => updateField("lab_name", e.target.value)}
                  />
                  <div className="form-text">
                    Display name for the lab using this OpenLIMS instance.
                  </div>
                </Form.Group>

                <Form.Group className="mb-3">
                  <Form.Label>Organization Name</Form.Label>
                  <Form.Control
                    value={form.organization_name || ""}
                    disabled={!userIsAdmin}
                    onChange={(e) =>
                      updateField("organization_name", e.target.value)
                    }
                  />
                </Form.Group>

                <Form.Group className="mb-3">
                  <Form.Label>Default Timezone</Form.Label>
                  <Form.Control
                    value={form.default_timezone || ""}
                    disabled={!userIsAdmin}
                    onChange={(e) =>
                      updateField("default_timezone", e.target.value)
                    }
                  />
                </Form.Group>

                <Form.Group>
                  <Form.Label>Default Sample Status</Form.Label>
                  <Form.Control
                    value={form.default_sample_status || ""}
                    disabled={!userIsAdmin}
                    onChange={(e) =>
                      updateField("default_sample_status", e.target.value)
                    }
                  />
                </Form.Group>
              </Card.Body>
            </Card>
          </Col>

          <Col lg={6}>
            <Card className="app-card h-100">
              <Card.Body>
                <h5 className="section-title">Import Settings</h5>

                <Form.Group className="mb-3">
                  <Form.Label>Max Upload Size MB</Form.Label>
                  <Form.Control
                    type="number"
                    min="1"
                    max="500"
                    value={form.max_upload_size_mb ?? 10}
                    disabled={!userIsAdmin}
                    onChange={(e) =>
                      updateField("max_upload_size_mb", e.target.value)
                    }
                  />
                </Form.Group>

                <Form.Group className="mb-3">
                  <Form.Label>Allowed FASTA Extensions</Form.Label>
                  <Form.Control
                    value={form.allowed_fasta_extensions_text || ""}
                    disabled={!userIsAdmin}
                    onChange={(e) =>
                      updateField(
                        "allowed_fasta_extensions_text",
                        e.target.value
                      )
                    }
                  />
                  <div className="form-text">
                    Comma-separated. Example: .fasta, .fa, .fna, .txt
                  </div>
                </Form.Group>

                <Form.Check
                  type="switch"
                  className="mb-3"
                  label="Require import preview before confirm"
                  checked={Boolean(form.require_import_preview)}
                  disabled={!userIsAdmin}
                  onChange={(e) =>
                    updateField("require_import_preview", e.target.checked)
                  }
                />
              </Card.Body>
            </Card>
          </Col>

          <Col lg={6}>
            <Card className="app-card h-100">
              <Card.Body>
                <h5 className="section-title">Sequence & Alignment Settings</h5>

                <Form.Check
                  type="switch"
                  className="mb-3"
                  label="Enable alignment jobs"
                  checked={Boolean(form.alignments_enabled)}
                  disabled={!userIsAdmin}
                  onChange={(e) =>
                    updateField("alignments_enabled", e.target.checked)
                  }
                />

                <Form.Group className="mb-3">
                  <Form.Label>Max Sequences Per Alignment</Form.Label>
                  <Form.Control
                    type="number"
                    min="2"
                    max="1000"
                    value={form.max_sequences_per_alignment ?? 25}
                    disabled={!userIsAdmin}
                    onChange={(e) =>
                      updateField(
                        "max_sequences_per_alignment",
                        e.target.value
                      )
                    }
                  />
                </Form.Group>

                <Form.Group>
                  <Form.Label>Max Sequence Length</Form.Label>
                  <Form.Control
                    type="number"
                    min="100"
                    value={form.max_sequence_length ?? 100000}
                    disabled={!userIsAdmin}
                    onChange={(e) =>
                      updateField("max_sequence_length", e.target.value)
                    }
                  />
                </Form.Group>
              </Card.Body>
            </Card>
          </Col>

          <Col lg={6}>
            <Card className="app-card h-100">
              <Card.Body>
                <h5 className="section-title">Security Settings</h5>

                <Form.Check
                  type="switch"
                  className="mb-3"
                  label="Viewer role is read-only"
                  checked={Boolean(form.viewer_read_only)}
                  disabled={!userIsAdmin}
                  onChange={(e) =>
                    updateField("viewer_read_only", e.target.checked)
                  }
                />

                <Form.Check
                  type="switch"
                  className="mb-3"
                  label="Require audit reason for critical changes"
                  checked={Boolean(form.require_audit_reason)}
                  disabled={!userIsAdmin}
                  onChange={(e) =>
                    updateField("require_audit_reason", e.target.checked)
                  }
                />

                <div className="soft-card">
                  <div className="feed-meta">Last Updated</div>
                  <div className="fw-semibold">
                    {formatTimestamp(settings?.updated_at)}
                  </div>

                  <div className="feed-meta mt-3">Updated By</div>
                  <div className="fw-semibold">
                    {settings?.updated_by_username || "-"}
                  </div>
                </div>
              </Card.Body>
            </Card>
          </Col>
        </Row>

        <Card className="app-card mt-4">
          <Card.Body>
            <div className="d-flex justify-content-between align-items-center gap-3 flex-wrap">
              <div>
                <h5 className="section-title mb-1">Save Settings</h5>
                <div className="text-muted">
                  Changes are logged to the Events page as SETTINGS_UPDATED.
                </div>
              </div>

              <div className="d-flex gap-2">
                <Button
                  type="button"
                  variant="outline-secondary"
                  disabled={!userIsAdmin || resetting}
                  onClick={resetDefaults}
                >
                  {resetting ? "Resetting..." : "Reset Defaults"}
                </Button>

                <Button
                  type="submit"
                  variant="dark"
                  disabled={!userIsAdmin || saving}
                >
                  {saving ? "Saving..." : "Save Settings"}
                </Button>
              </div>
            </div>
          </Card.Body>
        </Card>
      </Form>
    </div>
  );
}