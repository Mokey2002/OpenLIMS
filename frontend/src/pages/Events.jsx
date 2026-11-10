import { useEffect, useMemo, useRef, useState } from "react";
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
import { apiDownload, apiGet } from "../api";
import { isAdmin } from "../authz";
import { useLanguage } from "../i18n";
import { auditAction, auditDescription, auditReason, auditRecord, humanizeAudit } from "../utils/auditDisplay";

function formatTimestamp(ts) {
  if (!ts) return "-";

  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function prettyPayload(payload) {
  if (!payload) return "{}";

  try {
    return JSON.stringify(payload, null, 2);
  } catch {
    return String(payload);
  }
}

function statusVariant(action) {
  const value = String(action || "").toUpperCase();

  if (value.includes("FAILED") || value.includes("ERROR")) return "danger";
  if (value.includes("COMPLETED") || value.includes("APPROVED")) return "success";
  if (value.includes("CREATED") || value.includes("IMPORTED")) return "primary";
  if (
    value.includes("UPDATED") ||
    value.includes("CHANGED") ||
    value.includes("REASON")
  ) {
    return "warning";
  }
  if (value.includes("QUEUED") || value.includes("RUNNING")) return "info";

  return "secondary";
}

function buildQueryString(filters) {
  const params = new URLSearchParams();

  if (filters.entity_type) params.append("entity_type", filters.entity_type);
  if (filters.action) params.append("action", filters.action);
  if (filters.actor) params.append("actor", filters.actor);
  if (filters.search) params.append("search", filters.search);
  if (filters.date_from) params.append("date_from", filters.date_from);
  if (filters.date_to) params.append("date_to", filters.date_to);

  const query = params.toString();
  return query ? `?${query}` : "";
}

async function downloadAuditExport(format, filters) {
  const queryString = buildQueryString(filters);
  const filename =
    format === "json" ? "openlims-audit-log.json" : "openlims-audit-log.csv";

  await apiDownload(`/api/events/export-${format}/${queryString}`, filename);
}

export default function Events() {
  const { t, language } = useLanguage();
  const requestRef = useRef(null);
  const [me, setMe] = useState(null);
  const [events, setEvents] = useState([]);
  const [summary, setSummary] = useState(null);

  const [filters, setFilters] = useState({
    entity_type: "",
    action: "",
    actor: "",
    search: "",
    date_from: "",
    date_to: "",
  });

  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState("");
  const [err, setErr] = useState("");

  async function load(nextFilters = filters) {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setErr("");
    setLoading(true);

    try {
      const queryString = buildQueryString(nextFilters);

      const [meData, eventsData, summaryData] = await Promise.all([
        apiGet("/api/me/", { signal: controller.signal }),
        apiGet(`/api/events/${queryString}`, { signal: controller.signal }),
        apiGet(`/api/events/summary/${queryString}`, { signal: controller.signal }),
      ]);
      if (controller.signal.aborted) return;
      setMe(meData);
      setEvents(eventsData.results || eventsData || []);
      setSummary(summaryData);
    } catch {
      if (!controller.signal.aborted) {
        setEvents([]); setSummary(null);
        setErr(t("Could not load audit activity. Refresh the page to try again."));
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => { window.clearTimeout(timer); requestRef.current?.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const userIsAdmin = isAdmin(me);

  const entityTypes = useMemo(() => {
    const fromSummary = summary?.entity_types || [];
    const fromEvents = events.map((event) => event.entity_type).filter(Boolean);

    return Array.from(new Set([...fromSummary, ...fromEvents])).sort();
  }, [events, summary]);

  const actions = useMemo(() => {
    const fromSummary = summary?.actions || [];
    const fromEvents = events.map((event) => event.action).filter(Boolean);

    return Array.from(new Set([...fromSummary, ...fromEvents])).sort();
  }, [events, summary]);

  function updateFilter(field, value) {
    setFilters((current) => ({
      ...current,
      [field]: value,
    }));
  }

  function clearFilters() {
    const cleared = {
      entity_type: "",
      action: "",
      actor: "",
      search: "",
      date_from: "",
      date_to: "",
    };
    setFilters(cleared);
    void load(cleared);
  }

  async function exportFile(format) {
    setErr("");
    setExporting(format);

    try {
      await downloadAuditExport(format, filters);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setExporting("");
    }
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Audit Events</h1>
          <p className="page-subtitle">
            Review system activity, imports, sample changes, sequence actions,
            alignments, and admin updates.
          </p>
        </div>

        <div className="inline-actions">
          <Button variant="outline-dark" size="sm" onClick={() => load()}>
            Refresh
          </Button>

          {userIsAdmin && (
            <>
              <Button
                variant="outline-primary"
                size="sm"
                onClick={() => exportFile("csv")}
                disabled={Boolean(exporting)}
              >
                {exporting === "csv" ? "Exporting..." : "Export CSV"}
              </Button>

              <Button
                variant="outline-secondary"
                size="sm"
                onClick={() => exportFile("json")}
                disabled={Boolean(exporting)}
              >
                {exporting === "json" ? "Exporting..." : "Export JSON"}
              </Button>
            </>
          )}
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      {!userIsAdmin && (
        <Alert variant="info">
          You can view and filter events for records you currently have access to. Audit exports are restricted to administrators.
        </Alert>
      )}

      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Filters</h5>
              <div className="feed-meta">
                Filter audit events before reviewing or exporting.
              </div>
            </div>

            <Badge bg="dark">
              {summary?.total_events ?? events.length} matching events
            </Badge>
          </div>

          <Row className="g-3">
            <Col md={3}>
              <Form.Group controlId="audit-filter-entity">
                <Form.Label>Entity Type</Form.Label>
                <Form.Select
                  value={filters.entity_type}
                  onChange={(e) => updateFilter("entity_type", e.target.value)}
                >
                  <option value="">All entity types</option>

                  {entityTypes.map((entityType) => (
                    <option key={entityType} value={entityType}>
                      {t(humanizeAudit(entityType))}
                    </option>
                  ))}
                </Form.Select>
              </Form.Group>
            </Col>

            <Col md={3}>
              <Form.Group controlId="audit-filter-action">
                <Form.Label>Action</Form.Label>
                <Form.Select
                  value={filters.action}
                  onChange={(e) => updateFilter("action", e.target.value)}
                >
                  <option value="">All actions</option>

                  {actions.map((action) => (
                    <option key={action} value={action}>
                      {auditAction({ action }, t)}
                    </option>
                  ))}
                </Form.Select>
              </Form.Group>
            </Col>

            <Col md={3}>
              <Form.Group controlId="audit-filter-actor">
                <Form.Label>Actor</Form.Label>
                <Form.Control
                  placeholder="director, peter, maria..."
                  value={filters.actor}
                  onChange={(e) => updateFilter("actor", e.target.value)}
                />
              </Form.Group>
            </Col>

            <Col md={3}>
              <Form.Group controlId="audit-filter-search">
                <Form.Label>Search</Form.Label>
                <Form.Control
                  placeholder="import, sequence, sample..."
                  value={filters.search}
                  onChange={(e) => updateFilter("search", e.target.value)}
                />
              </Form.Group>
            </Col>

            <Col md={3}>
              <Form.Group controlId="audit-filter-from">
                <Form.Label>Date From</Form.Label>
                <Form.Control
                  type="datetime-local"
                  value={filters.date_from}
                  onChange={(e) => updateFilter("date_from", e.target.value)}
                />
              </Form.Group>
            </Col>

            <Col md={3}>
              <Form.Group controlId="audit-filter-to">
                <Form.Label>Date To</Form.Label>
                <Form.Control
                  type="datetime-local"
                  value={filters.date_to}
                  onChange={(e) => updateFilter("date_to", e.target.value)}
                />
              </Form.Group>
            </Col>

            <Col md={6} className="d-flex align-items-end gap-2">
              <Button variant="dark" onClick={() => load()}>
                Apply Filters
              </Button>

              <Button variant="outline-secondary" onClick={clearFilters}>
                Clear
              </Button>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      <div className="stat-grid mb-4">
        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Matching Events</div>
            <div className="metric-value">
              {summary?.total_events ?? events.length}
            </div>
            <div className="metric-note">Based on current filters</div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Entity Types</div>
            <div className="metric-value">{entityTypes.length}</div>
            <div className="metric-note">Samples, imports, sequences, etc.</div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Actions</div>
            <div className="metric-value">{actions.length}</div>
            <div className="metric-note">Unique audit actions</div>
          </Card.Body>
        </Card>

        <Card className="app-card metric-card h-100">
          <Card.Body>
            <div className="metric-label">Export Limit</div>
            <div className="metric-value">10k</div>
            <div className="metric-note">Maximum rows per export</div>
          </Card.Body>
        </Card>
      </div>

      <Card className="app-card">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Audit Log</h5>
              <div className="feed-meta">
                Events are read-only and generated by system actions.
              </div>
            </div>
          </div>

          {loading ? (
            <div className="d-flex align-items-center gap-2">
              <Spinner animation="border" size="sm" />
              <span>Loading audit events...</span>
            </div>
          ) : events.length === 0 ? (
            <div className="empty-state">No audit events found.</div>
          ) : (
            <Table responsive hover className="app-table align-middle">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Actor</th>
                  <th>Entity</th>
                  <th>Action</th>
                  <th>Reason</th>
                  <th>Change Summary</th>
                  <th>Details</th>
                </tr>
              </thead>

              <tbody>
                {events.map((event) => (
                  <tr key={event.id}>
                    <td style={{ minWidth: "180px" }}>
                      {formatTimestamp(event.timestamp || event.created_at)}
                    </td>

                    <td>{event.actor_username || event.actor || "-"}</td>

                    <td>
                      <div className="fw-semibold" translate="no">{auditRecord(event, t)}</div>
                      <div className="feed-meta">{t(humanizeAudit(event.entity_type))}</div>
                    </td>

                    <td>
                      <Badge bg={statusVariant(event.action)}>
                        {auditAction(event, t)}
                      </Badge>
                      {event.source === "Assistant" && <div className="feed-meta mt-1">{t("Assistant")}</div>}
                    </td>

                    <td style={{ minWidth: "260px" }}>
                      {auditReason(event) ? (
                        <div className="reason-box mb-0">
                          <div className="fw-semibold">
                            {auditReason(event)}
                          </div>
                        </div>
                      ) : (
                        <span className="feed-meta">-</span>
                      )}
                    </td>

                    <td style={{ minWidth: "260px" }}>
                      <div className="small" translate="no">{auditDescription(event, t, language)}</div>
                    </td>

                    <td style={{ minWidth: "160px" }}>
                      <details><summary>{t("Technical details")}</summary>
                      <dl className="small mt-2"><dt>{t("Action code")}</dt><dd translate="no">{event.action}</dd>
                        <dt>{t("Record ID")}</dt><dd translate="no">{event.entity_type} #{event.entity_id}</dd>
                        <dt>{t("Event ID")}</dt><dd translate="no">{event.id}</dd></dl>
                      <pre
                        className="mb-0"
                        style={{
                          maxHeight: "160px",
                          overflow: "auto",
                          fontSize: "0.78rem",
                          background: "#f8fafc",
                          border: "1px solid #e5e7eb",
                          borderRadius: "12px",
                          padding: "10px",
                        }}
                      >
                        {prettyPayload(event.payload)}
                      </pre>
                      </details>
                    </td>
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
