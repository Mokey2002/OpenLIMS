import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Card,
  OverlayTrigger,
  ProgressBar,
  Table,
  Tooltip,
} from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGet } from "../api";

function formatTimestamp(ts) {
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
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
    case "PROJECT_POSTED":
      return "info";
    case "PROJECT_ASSIGNED":
      return "secondary";
    case "RESULTS_IMPORTED":
      return "dark";
    default:
      return "secondary";
  }
}

function InfoTooltip({ text }) {
  return (
    <OverlayTrigger
      placement="top"
      overlay={<Tooltip>{text}</Tooltip>}
    >
      <span
        aria-label="More information"
        role="button"
        style={{
          cursor: "help",
          marginLeft: "6px",
          color: "#6b7280",
          fontWeight: 700,
          fontSize: "0.85rem",
        }}
      >
        ⓘ
      </span>
    </OverlayTrigger>
  );
}

function MetricCard({ title, value, note, tooltip }) {
  return (
    <Card className="app-card metric-card h-100">
      <Card.Body>
        <div className="metric-label">
          {title}
          {tooltip && <InfoTooltip text={tooltip} />}
        </div>

        <div className="metric-value">{value}</div>

        {note ? <div className="metric-note">{note}</div> : null}
      </Card.Body>
    </Card>
  );
}

export default function Dashboard() {
  const [samples, setSamples] = useState([]);
  const [events, setEvents] = useState([]);
  const [workItems, setWorkItems] = useState([]);
  const [projects, setProjects] = useState([]);
  const [me, setMe] = useState(null);
  const [err, setErr] = useState("");

  async function load() {
    setErr("");

    try {
      const [samplesData, eventsData, workItemsData, projectsData, meData] =
        await Promise.all([
          apiGet("/api/samples/"),
          apiGet("/api/events/"),
          apiGet("/api/work-items/"),
          apiGet("/api/projects/"),
          apiGet("/api/me/"),
        ]);

      setSamples(samplesData.results || samplesData || []);
      setEvents(eventsData.results || eventsData || []);
      setWorkItems(workItemsData.results || workItemsData || []);
      setProjects(projectsData.results || projectsData || []);
      setMe(meData);
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  useEffect(() => {
    load();
  }, []);

  const isAdmin = me?.roles?.includes("admin");

  const myProjects = useMemo(() => {
    if (!me) return [];
    if (isAdmin) return projects;

    return projects.filter((project) =>
      (project.member_usernames || []).includes(me.username)
    );
  }, [projects, me, isAdmin]);

  const recentEvents = useMemo(() => {
    return [...events]
      .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
      .slice(0, 8);
  }, [events]);

  const statusCounts = useMemo(() => {
    const counts = {
      RECEIVED: 0,
      IN_PROGRESS: 0,
      QC: 0,
      REPORTED: 0,
      ARCHIVED: 0,
    };

    for (const sample of samples) {
      counts[sample.status] = (counts[sample.status] || 0) + 1;
    }

    return counts;
  }, [samples]);

  const totalSamples = samples.length || 1;

  const qcPercent = Math.round((statusCounts.QC / totalSamples) * 100);

  const reportedPercent = Math.round(
    (statusCounts.REPORTED / totalSamples) * 100
  );

  const inProgressPercent = Math.round(
    (statusCounts.IN_PROGRESS / totalSamples) * 100
  );

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Dashboard</h1>
          <p className="page-subtitle">
            Overview of samples, projects, work, and recent activity.
          </p>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      <div className="stat-grid mb-4">
        <MetricCard
          title="Total Samples"
          value={samples.length}
          note={`${statusCounts.REPORTED} reported`}
          tooltip="Samples are the main lab records tracked through OpenLIMS. They can be linked to projects, containers, results, imports, events, and sequence workspaces."
        />

        <MetricCard
          title="Work Items"
          value={workItems.length}
          note={`${statusCounts.IN_PROGRESS} samples in progress`}
          tooltip="Work items represent lab tasks or testing steps that need to be completed for samples, such as processing, QC review, or result generation."
        />

        <MetricCard
          title={isAdmin ? "Visible Projects" : "My Projects"}
          value={myProjects.length}
          note={`${projects.length} total projects`}
          tooltip="Projects group related samples, project notes, team members, imports, results, and saved sequence workspaces together."
        />

        <MetricCard
          title="Events Logged"
          value={events.length}
          note={`${recentEvents.length} recent items below`}
          tooltip="Events are the audit trail. They record important activity such as sample creation, updates, project posts, imports, and result processing."
        />
      </div>

      <div className="row g-4 mb-4">
        <div className="col-lg-7">
          <Card className="app-card h-100">
            <Card.Body>
              <div className="d-flex justify-content-between align-items-center mb-3">
                <h5 className="section-title mb-0">
                  Sample Pipeline
                  <InfoTooltip text="The sample pipeline shows where samples are in the lab workflow, from intake to in-progress processing, QC review, reporting, and archiving." />
                </h5>

                <span className="feed-meta">
                  {samples.length} total samples
                </span>
              </div>

              <div className="soft-card mb-3">
                <div className="d-flex justify-content-between mb-2">
                  <span className="fw-semibold">
                    Reported
                    <InfoTooltip text="Reported samples have completed processing and have final results available." />
                  </span>
                  <span className="feed-meta">{statusCounts.REPORTED}</span>
                </div>
                <ProgressBar now={reportedPercent} />
              </div>

              <div className="soft-card mb-3">
                <div className="d-flex justify-content-between mb-2">
                  <span className="fw-semibold">
                    In Progress
                    <InfoTooltip text="In-progress samples are actively being processed or reviewed by the lab team." />
                  </span>
                  <span className="feed-meta">{statusCounts.IN_PROGRESS}</span>
                </div>
                <ProgressBar now={inProgressPercent} variant="info" />
              </div>

              <div className="soft-card mb-3">
                <div className="d-flex justify-content-between mb-2">
                  <span className="fw-semibold">
                    QC
                    <InfoTooltip text="QC samples need quality control review before they can be reported or archived." />
                  </span>
                  <span className="feed-meta">{statusCounts.QC}</span>
                </div>
                <ProgressBar now={qcPercent} variant="warning" />
              </div>

              <div className="row g-3 mt-1">
                <div className="col-md-6">
                  <div className="soft-card">
                    <div className="feed-meta mb-1">
                      Received
                      <InfoTooltip text="Received samples have been entered into OpenLIMS but may not have started processing yet." />
                    </div>
                    <div className="fs-4 fw-bold">{statusCounts.RECEIVED}</div>
                  </div>
                </div>

                <div className="col-md-6">
                  <div className="soft-card">
                    <div className="feed-meta mb-1">
                      Archived
                      <InfoTooltip text="Archived samples are completed records kept for history, traceability, and audit purposes." />
                    </div>
                    <div className="fs-4 fw-bold">{statusCounts.ARCHIVED}</div>
                  </div>
                </div>
              </div>
            </Card.Body>
          </Card>
        </div>

        <div className="col-lg-5">
          <Card className="app-card h-100">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">
                  {isAdmin ? "Projects" : "My Projects"}
                  <InfoTooltip text="Projects organize related lab work. A project can include samples, team members, project feed notes, results, imports, and linked sequence workspaces." />
                </h5>

                <Link to="/projects" className="text-decoration-none">
                  View all
                </Link>
              </div>

              {myProjects.length === 0 ? (
                <div className="empty-state">No projects available yet.</div>
              ) : (
                <div className="d-grid gap-2">
                  {myProjects.slice(0, 6).map((project) => (
                    <Link
                      key={project.id}
                      to={`/projects/${project.id}`}
                      className="text-decoration-none"
                    >
                      <div className="soft-card">
                        <div className="d-flex justify-content-between align-items-center">
                          <div>
                            <div className="fw-semibold">
                              {project.code} - {project.name}
                            </div>

                            <div className="feed-meta">
                              {project.sample_count ?? 0} samples
                            </div>
                          </div>

                          <Badge bg="dark">Open</Badge>
                        </div>
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </Card.Body>
          </Card>
        </div>
      </div>

      <Card className="app-card">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <h5 className="section-title mb-0">
              Recent Activity
              <InfoTooltip text="Recent Activity shows the latest audit events in OpenLIMS, including sample changes, project updates, imports, result creation, and other tracked actions." />
            </h5>

            <Link to="/events" className="text-decoration-none">
              View all
            </Link>
          </div>

          {recentEvents.length === 0 ? (
            <div className="empty-state">No recent events yet.</div>
          ) : (
            <Table responsive hover className="app-table">
              <thead>
                <tr>
                  <th>
                    Time
                    <InfoTooltip text="When the event happened." />
                  </th>
                  <th>
                    Action
                    <InfoTooltip text="The type of action that was recorded, such as CREATED, UPDATED, STATUS_CHANGED, or RESULTS_IMPORTED." />
                  </th>
                  <th>
                    Entity
                    <InfoTooltip text="The OpenLIMS object affected by the event, such as a sample, project, import job, or sequence workspace." />
                  </th>
                  <th>
                    Actor
                    <InfoTooltip text="The user who performed the action. A blank actor can mean the system or an unauthenticated instrument process created the event." />
                  </th>
                </tr>
              </thead>

              <tbody>
                {recentEvents.map((event) => (
                  <tr key={event.id}>
                    <td>{formatTimestamp(event.timestamp)}</td>

                    <td>
                      <Badge bg={actionVariant(event.action)}>
                        {event.action}
                      </Badge>
                    </td>

                    <td>
                      {event.entity_type} #{event.entity_id}
                    </td>

                    <td>{event.actor_username || "-"}</td>
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