import { useEffect, useMemo, useState } from "react";
import { Alert, Badge, Button, Card } from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGet, apiPost } from "../api";

function formatTimestamp(ts) {
  try { return new Date(ts).toLocaleString(); } catch { return ts; }
}

export default function Notifications() {
  const [notifications, setNotifications] = useState([]);
  const [err, setErr] = useState("");

  async function load() {
    setErr("");
    try {
      const data = await apiGet("/api/notifications/");
      setNotifications(data.results || data || []);
    } catch (e) {
      setErr(e.message || String(e));
    }
  }
  useEffect(() => { load(); }, []);

  async function markRead(id) {
    try {
      await apiPost(`/api/notifications/${id}/mark-read/`, {});
      setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, is_read: true } : n)));
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

  const unreadCount = useMemo(() => notifications.filter((n) => !n.is_read).length, [notifications]);

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Notifications</h1>
          <p className="page-subtitle">Recent alerts and system activity relevant to you.</p>
        </div>
        <Button variant="outline-dark" size="sm" onClick={markAllRead} disabled={unreadCount === 0}>Mark all as read</Button>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      {notifications.length === 0 ? (
        <Card className="app-card"><Card.Body><div className="empty-state">No notifications yet.</div></Card.Body></Card>
      ) : (
        <div className="d-grid gap-3">
          {notifications.map((n) => (
            <Card key={n.id} className="app-card">
              <Card.Body>
                <div className="d-flex justify-content-between align-items-start gap-2 flex-wrap">
                  <div>
                    <div className="d-flex align-items-center gap-2 mb-2">
                      <div className="fw-semibold">{n.title}</div>
                      {!n.is_read && <Badge bg="primary">Unread</Badge>}
                    </div>
                    <div className="feed-meta mb-2">{formatTimestamp(n.created_at)}</div>
                    <div>{n.message}</div>
                    {n.link && <div className="mt-2"><Link to={n.link}>Open</Link></div>}
                  </div>
                  {!n.is_read && <Button variant="outline-dark" size="sm" onClick={() => markRead(n.id)}>Mark read</Button>}
                </div>
              </Card.Body>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
