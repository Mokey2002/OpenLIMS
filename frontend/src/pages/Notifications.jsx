import { useEffect, useMemo, useState } from "react";
import { Alert, Badge, Button, Card, Spinner } from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGet, apiPost } from "../api";

function formatTimestamp(ts) {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

export default function Notifications() {
  const [notifications, setNotifications] = useState([]);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(true);

  async function load() {
    setErr("");
    setLoading(true);
    try {
      const data = await apiGet("/api/notifications/");
      setNotifications(data.results || data || []);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function markRead(id) {
    try {
      await apiPost(`/api/notifications/${id}/mark-read/`, {});
      setNotifications((prev) =>
        prev.map((n) => (n.id === id ? { ...n, is_read: true } : n))
      );
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function markAllRead() {
    try {
      await apiPost("/api/notifications/mark-all-read/", {});
      setNotifications((prev) => prev.map((n) => ({ ...n, is_read: true })));
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  const unreadCount = useMemo(
    () => notifications.filter((n) => !n.is_read).length,
    [notifications]
  );

  return (
    <div className="w-100">
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h2 className="mb-0">Notifications</h2>
        <Button
          variant="outline-dark"
          size="sm"
          onClick={markAllRead}
          disabled={unreadCount === 0}
        >
          Mark all as read
        </Button>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      {loading ? (
        <Spinner animation="border" />
      ) : notifications.length === 0 ? (
        <Alert variant="light">No notifications yet.</Alert>
      ) : (
        <div className="d-grid gap-3">
          {notifications.map((n) => (
            <Card
              key={n.id}
              className={`shadow-sm border-0 ${n.is_read ? "" : "border border-primary"}`}
            >
              <Card.Body>
                <div className="d-flex justify-content-between align-items-start gap-2 flex-wrap">
                  <div>
                    <div className="d-flex align-items-center gap-2 mb-2">
                      <div className="fw-semibold">{n.title}</div>
                      {!n.is_read && <Badge bg="primary">Unread</Badge>}
                    </div>

                    <div className="text-muted small mb-2">
                      {formatTimestamp(n.created_at)}
                    </div>

                    <div>{n.message}</div>

                    {n.link && (
                      <div className="mt-2">
                        <Link to={n.link}>Open</Link>
                      </div>
                    )}
                  </div>

                  {!n.is_read && (
                    <Button
                      variant="outline-dark"
                      size="sm"
                      onClick={() => markRead(n.id)}
                    >
                      Mark read
                    </Button>
                  )}
                </div>
              </Card.Body>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}