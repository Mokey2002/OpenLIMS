import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  Pagination,
  Row,
  Spinner,
} from "react-bootstrap";
import { apiGet } from "../api";

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
    case "PROJECT_POSTED":
      return "info";
    case "ATTACHMENT_UPLOADED":
      return "info";
    case "PROJECT_ASSIGNED":
      return "secondary";
    case "RESULTS_IMPORTED":
      return "dark";
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
  if (event.action === "STATUS_CHANGED") {
    return `Status changed from ${event.payload?.old_status} to ${event.payload?.new_status}`;
  }

  if (event.action === "CONTAINER_ASSIGNED") {
    return `Container changed from ${
      event.payload?.old_container_code || "Unassigned"
    } to ${
      event.payload?.new_container_code || "Unassigned"
    }`;
  }

  if (event.action === "PROJECT_POSTED") {
    return `Project post added${event.payload?.has_image ? " with image" : ""}`;
  }

  if (event.action === "ATTACHMENT_UPLOADED") {
    return `Attachment uploaded: ${event.payload?.filename || "file"}`;
  }

  if (event.action === "PROJECT_ASSIGNED") {
    return `Project changed to ${event.payload?.new_project_id || "Unassigned"}`;
  }

  if (event.action === "RESULTS_IMPORTED") {
    return `Results imported from ${event.payload?.instrument_code || "instrument"}`;
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

  return `${event.entity_type} #${event.entity_id}`;
}

export default function Events() {
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  const [entityFilter, setEntityFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [search, setSearch] = useState("");

  const [page, setPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const [nextPageUrl, setNextPageUrl] = useState(null);
  const [previousPageUrl, setPreviousPageUrl] = useState(null);

  async function load() {
    setErr("");
    setLoading(true);

    try {
      const params = new URLSearchParams();
      params.set("page", page);

      const data = await apiGet(`/api/events/?${params.toString()}`);

      const pageEvents = data.results || [];
      const allEntityTypes = [...new Set(pageEvents.map((e) => e.entity_type))];
      const allActions = [...new Set(pageEvents.map((e) => e.action))];

      let filtered = pageEvents;

      if (entityFilter) {
        filtered = filtered.filter((e) => e.entity_type === entityFilter);
      }

      if (actionFilter) {
        filtered = filtered.filter((e) => e.action === actionFilter);
      }

      if (search.trim()) {
        const q = search.trim().toLowerCase();
        filtered = filtered.filter((e) => {
          const actor = (e.actor_username || "").toLowerCase();
          const entityType = (e.entity_type || "").toLowerCase();
          const entityId = String(e.entity_id || "").toLowerCase();
          const payload = JSON.stringify(e.payload || {}).toLowerCase();
          const action = (e.action || "").toLowerCase();

          return (
            actor.includes(q) ||
            entityType.includes(q) ||
            entityId.includes(q) ||
            payload.includes(q) ||
            action.includes(q)
          );
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
    } finally {
      setLoading(false);
    }
  }

  const [entityOptions, setEntityOptions] = useState([""]);
  const [actionOptions, setActionOptions] = useState([""]);

  useEffect(() => {
    load();
  }, [page, entityFilter, actionFilter, search]);

  useEffect(() => {
    setPage(1);
  }, [entityFilter, actionFilter, search]);

  const totalPages = Math.max(1, Math.ceil(totalCount / 10));

  const summaryText = useMemo(() => {
    return `Showing ${events.length} of ${totalCount} events`;
  }, [events.length, totalCount]);

  return (
    <div className="w-100">
      <Row className="align-items-center mb-3">
        <Col>
          <h2 className="mb-0">Event Timeline</h2>
        </Col>
      </Row>

      <Card className="shadow-sm border-0 mb-4">
        <Card.Body>
          <Row className="g-3">
            <Col md={4}>
              <Form.Control
                placeholder="Search actor, action, entity, or payload"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </Col>

            <Col md={4}>
              <Form.Select
                value={entityFilter}
                onChange={(e) => setEntityFilter(e.target.value)}
              >
                <option value="">All entities</option>
                {entityOptions.filter(Boolean).map((type) => (
                  <option key={type} value={type}>
                    {type}
                  </option>
                ))}
              </Form.Select>
            </Col>

            <Col md={4}>
              <Form.Select
                value={actionFilter}
                onChange={(e) => setActionFilter(e.target.value)}
              >
                <option value="">All actions</option>
                {actionOptions.filter(Boolean).map((action) => (
                  <option key={action} value={action}>
                    {action}
                  </option>
                ))}
              </Form.Select>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      {err && <Alert variant="danger">{err}</Alert>}

      <Card className="shadow-sm border-0">
        <Card.Body>
          <div className="d-flex justify-content-between align-items-center mb-3 flex-wrap gap-2">
            <div className="text-muted small">{summaryText}</div>

            <Pagination className="mb-0">
              <Pagination.Prev
                disabled={!previousPageUrl || page === 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              />
              <Pagination.Item active>{page}</Pagination.Item>
              <Pagination.Next
                disabled={!nextPageUrl || page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              />
            </Pagination>
          </div>

          {loading ? (
            <Spinner animation="border" />
          ) : events.length === 0 ? (
            <Alert variant="light">No events found.</Alert>
          ) : (
            <div className="d-grid gap-3">
              {events.map((event) => (
                <Card key={event.id} className="shadow-sm border">
                  <Card.Body>
                    <div className="d-flex justify-content-between align-items-start flex-wrap gap-2">
                      <div>
                        <div className="d-flex align-items-center gap-2 mb-2 flex-wrap">
                          <Badge bg={actionVariant(event.action)}>
                            {event.action}
                          </Badge>
                          <span className="fw-semibold">
                            {describeEvent(event)}
                          </span>
                        </div>

                        <div className="text-muted small mb-2">
                          {formatTimestamp(event.timestamp)}
                          {event.actor_username ? ` • by ${event.actor_username}` : ""}
                        </div>
                      </div>
                    </div>

                    <div>
                      <div className="fw-semibold mb-2">Payload</div>
                      <pre
                        className="bg-light p-3 rounded small mb-0"
                        style={{
                          overflowX: "auto",
                          whiteSpace: "pre-wrap",
                          wordBreak: "break-word",
                        }}
                      >
                        {JSON.stringify(event.payload, null, 2)}
                      </pre>
                    </div>
                  </Card.Body>
                </Card>
              ))}
            </div>
          )}
        </Card.Body>
      </Card>
    </div>
  );
}