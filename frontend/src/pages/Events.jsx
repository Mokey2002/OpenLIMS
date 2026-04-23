import { useEffect, useState } from "react";
import { Alert, Badge, Card, Col, Form, Pagination, Row } from "react-bootstrap";
import { apiGet } from "../api";

function actionVariant(action) {
  switch (action) {
    case "CREATED": return "success";
    case "UPDATED": return "primary";
    case "DELETED": return "danger";
    case "STATUS_CHANGED": return "warning";
    case "CONTAINER_ASSIGNED": return "info";
    case "PROJECT_POSTED": return "info";
    case "ATTACHMENT_UPLOADED": return "info";
    case "PROJECT_ASSIGNED": return "secondary";
    case "RESULTS_IMPORTED": return "dark";
    default: return "secondary";
  }
}
function formatTimestamp(ts) { try { return new Date(ts).toLocaleString(); } catch { return ts; } }

export default function Events() {
  const [events, setEvents] = useState([]);
  const [err, setErr] = useState("");
  const [entityFilter, setEntityFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [nextPageUrl, setNextPageUrl] = useState(null);
  const [previousPageUrl, setPreviousPageUrl] = useState(null);
  const [entityOptions, setEntityOptions] = useState([""]);
  const [actionOptions, setActionOptions] = useState([""]);

  async function load() {
    setErr("");
    try {
      const params = new URLSearchParams();
      params.set("page", page);
      const data = await apiGet(`/api/events/?${params.toString()}`);
      const pageEvents = data.results || [];
      const allEntityTypes = [...new Set(pageEvents.map((e) => e.entity_type))];
      const allActions = [...new Set(pageEvents.map((e) => e.action))];

      let filtered = pageEvents;
      if (entityFilter) filtered = filtered.filter((e) => e.entity_type === entityFilter);
      if (actionFilter) filtered = filtered.filter((e) => e.action === actionFilter);
      if (search.trim()) {
        const q = search.trim().toLowerCase();
        filtered = filtered.filter((e) => {
          const actor = (e.actor_username || "").toLowerCase();
          const entityType = (e.entity_type || "").toLowerCase();
          const entityId = String(e.entity_id || "").toLowerCase();
          const payload = JSON.stringify(e.payload || {}).toLowerCase();
          const action = (e.action || "").toLowerCase();
          return actor.includes(q) || entityType.includes(q) || entityId.includes(q) || payload.includes(q) || action.includes(q);
        });
      }

      setEvents(filtered);
      setTotalCount(data.count || 0);
      setNextPageUrl(data.next || null);
      setPreviousPageUrl(data.previous || null);
      setEntityOptions(["", ...allEntityTypes.sort()]);
      setActionOptions(["", ...allActions.sort()]);
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  useEffect(() => { load(); }, [page, entityFilter, actionFilter, search]);
  useEffect(() => { setPage(1); }, [entityFilter, actionFilter, search]);

  const totalPages = Math.max(1, Math.ceil(totalCount / 10));

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Events</h1>
          <p className="page-subtitle">Audit trail and recent operational activity.</p>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      <Card className="app-card mb-4">
        <Card.Body>
          <Row className="g-3">
            <Col md={4}>
              <Form.Control placeholder="Search actor, action, entity, or payload" value={search} onChange={(e) => setSearch(e.target.value)} />
            </Col>
            <Col md={4}>
              <Form.Select value={entityFilter} onChange={(e) => setEntityFilter(e.target.value)}>
                <option value="">All entities</option>
                {entityOptions.filter(Boolean).map((type) => <option key={type} value={type}>{type}</option>)}
              </Form.Select>
            </Col>
            <Col md={4}>
              <Form.Select value={actionFilter} onChange={(e) => setActionFilter(e.target.value)}>
                <option value="">All actions</option>
                {actionOptions.filter(Boolean).map((action) => <option key={action} value={action}>{action}</option>)}
              </Form.Select>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      <Card className="app-card">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div className="feed-meta">Showing {events.length} of {totalCount} events</div>
            <Pagination className="mb-0">
              <Pagination.Prev disabled={!previousPageUrl || page === 1} onClick={() => setPage((p) => Math.max(1, p - 1))} />
              <Pagination.Item active>{page}</Pagination.Item>
              <Pagination.Next disabled={!nextPageUrl || page >= totalPages} onClick={() => setPage((p) => p + 1)} />
            </Pagination>
          </div>

          {events.length === 0 ? (
            <div className="empty-state">No events found.</div>
          ) : (
            <div className="d-grid gap-3">
              {events.map((event) => (
                <div key={event.id} className="feed-item">
                  <div className="d-flex justify-content-between align-items-start gap-2 flex-wrap mb-2">
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
  );
}
