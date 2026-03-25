import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { Alert, Badge, Button, Card, Spinner } from "react-bootstrap";
import { apiGet, apiPost } from "../api";

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

  const [sample, setSample] = useState(null);
  const [allowed, setAllowed] = useState([]);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  async function load() {
    setLoading(true);
    setErr("");

    try {
      const [s, t, ev] = await Promise.all([
        apiGet(`/api/samples/${id}/`),
        apiGet(`/api/samples/${id}/allowed-transitions/`),
        apiGet(`/api/events/`),
      ]);

      setSample(s);
      setAllowed(t.allowed_transitions || []);

      // Filter only events related to this sample
      const sampleEvents = ev.filter(
        (event) =>
          event.entity_type === "Sample" &&
          (
            String(event.entity_id) === String(id) ||
            String(event.payload?.sample_id) === String(id)
          )
      );

      setEvents(sampleEvents);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, [id]);

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
