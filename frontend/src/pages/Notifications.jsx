import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  Row,
  Table,
} from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGetAll, apiPost } from "../api";
import ConfirmedOperationCard from "../components/ConfirmedOperationCard";
import useConfirmedOperation from "../hooks/useConfirmedOperation";

function formatTimestamp(value) {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

export default function Notifications() {
  const [notifications, setNotifications] = useState([]);
  const [subscriptions, setSubscriptions] = useState([]);
  const [items, setItems] = useState([]);
  const [samples, setSamples] = useState([]);
  const [blastJobs, setBlastJobs] = useState([]);
  const [results, setResults] = useState([]);
  const [err, setErr] = useState("");
  const [trigger, setTrigger] = useState("INVENTORY_BELOW");
  const [targetId, setTargetId] = useState("");
  const [threshold, setThreshold] = useState("");
  const [channel, setChannel] = useState("IN_APP");
  const [frequency, setFrequency] = useState("ONCE");

  async function load() {
    setErr("");
    try {
      const [notificationRows, subscriptionRows, itemRows, sampleRows, blastRows, resultRows] =
        await Promise.all([
          apiGetAll("/api/notifications/"),
          apiGetAll("/api/notification-subscriptions/"),
          apiGetAll("/api/inventory-items/"),
          apiGetAll("/api/samples/"),
          apiGetAll("/api/blast-jobs/"),
          apiGetAll("/api/results/"),
        ]);
      setNotifications(notificationRows);
      setSubscriptions(subscriptionRows);
      setItems(itemRows);
      setSamples(sampleRows);
      setBlastJobs(blastRows);
      setResults(resultRows);
    } catch (requestError) {
      setErr(requestError.message || String(requestError));
    }
  }

  const operation = useConfirmedOperation(load);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
  }, []);

  async function proposeSubscription(event) {
    event.preventDefault();
    const prefix = `Alert me${channel === "EMAIL" ? " by email" : ""}${
      frequency === "DAILY" ? " daily" : ""
    } when`;
    let command = "";

    if (trigger === "INVENTORY_BELOW") {
      const item = items.find((row) => String(row.id) === String(targetId));
      if (!item || !threshold) return;
      command = `${prefix} reagent ${item.code} falls below ${threshold} units`;
    } else if (trigger === "SAMPLE_APPROVED") {
      const sample = samples.find((row) => String(row.id) === String(targetId));
      if (!sample) return;
      command = `${prefix} sample ${sample.sample_id} is approved`;
    } else if (trigger === "BLAST_COMPLETED") {
      const job = blastJobs.find((row) => String(row.id) === String(targetId));
      if (!job) return;
      command = `${prefix} BLAST job #${job.id} completes`;
    } else {
      const result = results.find((row) => String(row.id) === String(targetId));
      if (!result) return;
      command = `${prefix} QC result #${result.id} remains pending`;
    }

    await operation.propose(command);
  }

  async function proposeCancellation(subscription) {
    await operation.propose(`Cancel notification ${subscription.id}`);
  }

  async function markRead(id) {
    try {
      await apiPost(`/api/notifications/${id}/mark-read/`, {});
      setNotifications((current) =>
        current.map((notification) =>
          notification.id === id ? { ...notification, is_read: true } : notification
        )
      );
    } catch (requestError) {
      setErr(requestError.message || String(requestError));
    }
  }

  async function markAllRead() {
    try {
      await apiPost("/api/notifications/mark-all-read/", {});
      setNotifications((current) => current.map((notification) => ({ ...notification, is_read: true })));
    } catch (requestError) {
      setErr(requestError.message || String(requestError));
    }
  }

  const activeSubscriptions = useMemo(
    () => subscriptions.filter((subscription) => subscription.active),
    [subscriptions]
  );
  const unreadCount = useMemo(
    () => notifications.filter((notification) => !notification.is_read).length,
    [notifications]
  );

  const targetOptions =
    trigger === "INVENTORY_BELOW"
      ? items.map((item) => ({ id: item.id, label: `${item.code} — ${item.name}` }))
      : trigger === "SAMPLE_APPROVED"
        ? samples.map((sample) => ({ id: sample.id, label: `${sample.sample_id} — ${sample.project_code || "No project"}` }))
        : trigger === "BLAST_COMPLETED"
          ? blastJobs.map((job) => ({ id: job.id, label: `#${job.id} — ${job.name}` }))
          : results.map((result) => ({ id: result.id, label: `R-${result.id} — ${result.sample_code} / ${result.key}` }));

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Notifications</h1>
          <p className="page-subtitle">
            Create and cancel alert subscriptions, then review delivered notifications.
          </p>
        </div>
        <div className="inline-actions">
          <Button variant="outline-dark" size="sm" onClick={load}>Refresh</Button>
          <Button variant="outline-dark" size="sm" onClick={markAllRead} disabled={unreadCount === 0}>Mark all read</Button>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Create alert subscription</h5>
          <Form onSubmit={proposeSubscription}>
            <Row className="g-3 align-items-end">
              <Col lg={3}>
                <Form.Label>Trigger</Form.Label>
                <Form.Select value={trigger} onChange={(event) => {
                  setTrigger(event.target.value);
                  setTargetId("");
                  setThreshold("");
                }}>
                  <option value="INVENTORY_BELOW">Inventory below threshold</option>
                  <option value="SAMPLE_APPROVED">Sample approved</option>
                  <option value="BLAST_COMPLETED">BLAST job completed</option>
                  <option value="QC_REMAINS_PENDING">QC remains pending</option>
                </Form.Select>
              </Col>
              <Col lg={4}>
                <Form.Label>Target</Form.Label>
                <Form.Select value={targetId} onChange={(event) => setTargetId(event.target.value)}>
                  <option value="">Select target</option>
                  {targetOptions.map((target) => <option key={target.id} value={target.id}>{target.label}</option>)}
                </Form.Select>
              </Col>
              {trigger === "INVENTORY_BELOW" && (
                <Col lg={2}>
                  <Form.Label>Threshold</Form.Label>
                  <Form.Control type="number" min="0" step="any" value={threshold} onChange={(event) => setThreshold(event.target.value)} />
                </Col>
              )}
              <Col lg={trigger === "INVENTORY_BELOW" ? 1 : 2}>
                <Form.Label>Channel</Form.Label>
                <Form.Select value={channel} onChange={(event) => setChannel(event.target.value)}>
                  <option value="IN_APP">In-app</option><option value="EMAIL">Email</option>
                </Form.Select>
              </Col>
              <Col lg={trigger === "INVENTORY_BELOW" ? 1 : 2}>
                <Form.Label>Frequency</Form.Label>
                <Form.Select value={frequency} onChange={(event) => setFrequency(event.target.value)}>
                  <option value="ONCE">Once</option><option value="DAILY">Daily</option>
                </Form.Select>
              </Col>
              <Col lg={trigger === "INVENTORY_BELOW" ? 1 : 1}>
                <Button type="submit" variant="dark" className="w-100" disabled={!targetId || (trigger === "INVENTORY_BELOW" && !threshold)}>Preview</Button>
              </Col>
            </Row>
          </Form>
          <div className="feed-meta mt-2">
            Subscriptions default to a 30-day expiration. Email delivery requires an email address on your OpenLIMS account.
          </div>
        </Card.Body>
      </Card>

      <ConfirmedOperationCard operation={operation} />

      <Card className="app-card mt-4 mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <h5 className="section-title mb-0">Active subscriptions</h5>
            <Badge bg="dark">{activeSubscriptions.length}</Badge>
          </div>
          {activeSubscriptions.length === 0 ? (
            <div className="empty-state">No active subscriptions.</div>
          ) : (
            <Table responsive hover className="app-table">
              <thead><tr><th>ID</th><th>Trigger</th><th>Target</th><th>Channel</th><th>Frequency</th><th>Threshold</th><th>Next check</th><th></th></tr></thead>
              <tbody>
                {activeSubscriptions.map((subscription) => (
                  <tr key={subscription.id}>
                    <td>#{subscription.id}</td><td>{subscription.trigger}</td>
                    <td>{subscription.target_type} {subscription.target_id}</td>
                    <td>{subscription.delivery_channel}</td><td>{subscription.frequency}</td>
                    <td>{subscription.threshold || "—"}</td><td>{formatTimestamp(subscription.next_run_at)}</td>
                    <td><Button size="sm" variant="outline-danger" onClick={() => proposeCancellation(subscription)}>Cancel</Button></td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>

      <div className="toolbar-row mb-3">
        <h5 className="section-title mb-0">Delivered notifications</h5>
        <Badge bg="primary">{unreadCount} unread</Badge>
      </div>
      {notifications.length === 0 ? (
        <Card className="app-card"><Card.Body><div className="empty-state">No notifications yet.</div></Card.Body></Card>
      ) : (
        <div className="d-grid gap-3">
          {notifications.map((notification) => (
            <Card key={notification.id} className="app-card">
              <Card.Body>
                <div className="d-flex justify-content-between align-items-start gap-2 flex-wrap">
                  <div>
                    <div className="d-flex align-items-center gap-2 mb-2">
                      <div className="fw-semibold">{notification.title}</div>
                      {!notification.is_read && <Badge bg="primary">Unread</Badge>}
                    </div>
                    <div className="feed-meta mb-2">{formatTimestamp(notification.created_at)}</div>
                    <div>{notification.message}</div>
                    {notification.link && <div className="mt-2"><Link to={notification.link}>Open</Link></div>}
                  </div>
                  {!notification.is_read && <Button variant="outline-dark" size="sm" onClick={() => markRead(notification.id)}>Mark read</Button>}
                </div>
              </Card.Body>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
