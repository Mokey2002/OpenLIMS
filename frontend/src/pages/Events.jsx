import { useEffect, useMemo, useState } from "react";
import { Alert, Badge, Card, Col, Form, Row, Spinner } from "react-bootstrap";
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
  const [entityFilter, setEntityFilter] = useState("ALL");

  async function load() {
    setErr("");
    setLoading(true);
    try {
      const data = await apiGet("/api/events/");
      setEvents(data);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const entityTypes = useMemo(() => {
    const types = [...new Set(events.map((e) => e.entity_type))];
    return ["ALL", ...types];
  }, [events]);

  const filteredEvents = useMemo(() => {
    if (entityFilter === "ALL") return events;
    return events.filter((e) => e.entity_type === entityFilter);
  }, [events, entityFilter]);

  return (
    <div className="w-100">
      <Row className="align-items-center mb-3">
        <Col>
          <h2 className="mb-0">Event Timeline</h2>
        </Col>
        <Col xs="auto">
          <Form.Select
            value={entityFilter}
            onChange={(e) => setEntityFilter(e.target.value)}
          >
            {entityTypes.map((type) => (
              <option key={type} value={type}>
                {type === "ALL" ? "All entities" : type}
              </option>
            ))}
          </Form.Select>
        </Col>
      </Row>

      {err && <Alert variant="danger">{err}</Alert>}

      {loading ? (
        <Spinner animation="border" />
      ) : filteredEvents.length === 0 ? (
        <Alert variant="light">No events found.</Alert>
      ) : (
        <div className="d-grid gap-3">
          {filteredEvents.map((event) => (
            <Card key={event.id} className="shadow-sm border-0">
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
    </div>
  );
}