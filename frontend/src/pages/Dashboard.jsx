import { useEffect, useMemo, useState } from "react";
import { Alert, Badge, Card, Col, Row, Spinner, Table } from "react-bootstrap";
import { Link } from "react-router-dom";
import { apiGet } from "../api";

import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Tooltip,
  Legend,
} from "chart.js";
import { Bar } from "react-chartjs-2";

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip, Legend);

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
    default:
      return "secondary";
  }
}

function StatCard({ title, value, subtitle }) {
  return (
    <Card className="shadow-sm border-0 h-100">
      <Card.Body>
        <div className="text-muted small mb-2">{title}</div>
        <div className="fs-3 fw-bold">{value}</div>
        {subtitle ? <div className="text-muted small mt-1">{subtitle}</div> : null}
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

  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  async function load() {
    setErr("");
    setLoading(true);
    try {
      const [samplesData, eventsData, workItemsData, projectsData, meData] = await Promise.all([
        apiGet("/api/samples/"),
        apiGet("/api/events/"),
        apiGet("/api/work-items/"),
        apiGet("/api/projects/"),
        apiGet("/api/me/"),
      ]);

      setSamples(samplesData);
      setEvents(eventsData);
      setWorkItems(workItemsData);
      setProjects(projectsData);
      setMe(meData);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
  }, []);

  const statusCounts = useMemo(() => {
    const counts = {
      RECEIVED: 0,
      IN_PROGRESS: 0,
      QC: 0,
      REPORTED: 0,
      ARCHIVED: 0,
    };

    for (const s of samples) {
      counts[s.status] = (counts[s.status] || 0) + 1;
    }

    return counts;
  }, [samples]);

  const recentEvents = useMemo(() => {
    return [...events]
      .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
      .slice(0, 8);
  }, [events]);

  const chartData = useMemo(() => {
    return {
      labels: Object.keys(statusCounts),
      datasets: [
        {
          label: "Samples",
          data: Object.values(statusCounts),
        },
      ],
    };
  }, [statusCounts]);

  const chartOptions = useMemo(() => {
    return {
      responsive: true,
      plugins: {
        legend: {
          display: false,
        },
      },
      scales: {
        y: {
          beginAtZero: true,
          ticks: {
            precision: 0,
          },
        },
      },
    };
  }, []);

  const isAdmin = me?.roles?.includes("admin");

  const myProjects = useMemo(() => {
    if (!me) return [];

    if (isAdmin) {
      return projects;
    }

    return projects.filter((p) =>
      (p.member_usernames || []).includes(me.username)
    );
  }, [projects, me, isAdmin]);

  const myProjectIds = useMemo(
    () => myProjects.map((p) => p.id),
    [myProjects]
  );

  const myActivity = useMemo(() => {
    return events
      .filter((e) => {
        const projectId = e.payload?.project_id;
        return projectId && myProjectIds.includes(projectId);
      })
      .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
      .slice(0, 8);
  }, [events, myProjectIds]);

  if (loading) {
    return <Spinner animation="border" />;
  }

  return (
    <div className="w-100">
      <div className="d-flex justify-content-between align-items-center mb-4">
        <div>
          <h2 className="mb-1">Dashboard</h2>
          <div className="text-muted">Operational overview of OpenLIMS</div>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      <Row className="g-3 mb-4">
        <Col md={3}>
          <StatCard title="Total Samples" value={samples.length} />
        </Col>
        <Col md={3}>
          <StatCard title="Total Work Items" value={workItems.length} />
        </Col>
        <Col md={3}>
          <StatCard title="Recent Events" value={events.length} />
        </Col>
        <Col md={3}>
          <StatCard
            title={isAdmin ? "Visible Projects" : "My Projects"}
            value={myProjects.length}
          />
        </Col>
      </Row>

      <Row className="g-4 mb-4">
        <Col lg={7}>
          <Card className="shadow-sm border-0 h-100">
            <Card.Body>
              <h5 className="mb-3">Samples by Status</h5>
              <Bar data={chartData} options={chartOptions} />
            </Card.Body>
          </Card>
        </Col>

        <Col lg={5}>
          <Card className="shadow-sm border-0 h-100">
            <Card.Body>
              <h5 className="mb-3">{isAdmin ? "Projects" : "My Projects"}</h5>

              {myProjects.length === 0 ? (
                <Alert variant="light" className="mb-0">
                  {isAdmin ? "No projects yet." : "You are not assigned to any projects."}
                </Alert>
              ) : (
                <div className="d-grid gap-2">
                  {myProjects.slice(0, 6).map((p) => (
                    <Link
                      key={p.id}
                      to={`/projects/${p.id}`}
                      className="text-decoration-none"
                    >
                      <Card className="border">
                        <Card.Body className="py-2">
                          <div className="d-flex justify-content-between align-items-center">
                            <div>
                              <div className="fw-semibold">
                                {p.code} - {p.name}
                              </div>
                              <div className="text-muted small">
                                {p.sample_count ?? 0} samples
                              </div>
                            </div>
                            <Badge bg="dark">Open</Badge>
                          </div>
                        </Card.Body>
                      </Card>
                    </Link>
                  ))}

                  <Link className="btn btn-outline-dark mt-2" to="/projects">
                    View All Projects
                  </Link>
                </div>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Card className="shadow-sm border-0 mb-4">
        <Card.Body>
          <h5 className="mb-3">My Project Activity</h5>

          {myActivity.length === 0 ? (
            <Alert variant="light" className="mb-0">
              No recent activity in your projects.
            </Alert>
          ) : (
            <Table responsive hover className="mb-0">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Action</th>
                  <th>Project</th>
                  <th>Actor</th>
                </tr>
              </thead>
              <tbody>
                {myActivity.map((event) => (
                  <tr key={event.id}>
                    <td>{formatTimestamp(event.timestamp)}</td>
                    <td>
                      <Badge bg={actionVariant(event.action)}>{event.action}</Badge>
                    </td>
                    <td>{event.payload?.project_code || "-"}</td>
                    <td>{event.actor_username || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>

      <Card className="shadow-sm border-0">
        <Card.Body>
          <h5 className="mb-3">Recent Activity</h5>

          {recentEvents.length === 0 ? (
            <Alert variant="light" className="mb-0">
              No events yet.
            </Alert>
          ) : (
            <Table responsive hover className="mb-0">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Action</th>
                  <th>Entity</th>
                  <th>Actor</th>
                </tr>
              </thead>
              <tbody>
                {recentEvents.map((event) => (
                  <tr key={event.id}>
                    <td>{formatTimestamp(event.timestamp)}</td>
                    <td>
                      <Badge bg={actionVariant(event.action)}>{event.action}</Badge>
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