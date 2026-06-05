import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  Row,
  Spinner,
} from "react-bootstrap";
import { apiGet } from "../api";

function useQuery() {
  return new URLSearchParams(useLocation().search);
}

function typeVariant(type) {
  switch (type) {
    case "Sample":
      return "primary";
    case "Project":
      return "dark";
    case "Sequence":
      return "success";
    case "Alignment":
      return "info";
    case "Import":
      return "warning";
    case "Event":
      return "secondary";
    case "User":
      return "danger";
    default:
      return "secondary";
  }
}

function resultGroups(results) {
  if (!results) return [];

  return [
    ["samples", "Samples"],
    ["projects", "Projects"],
    ["sequences", "Sequences"],
    ["alignments", "Alignments"],
    ["imports", "Imports"],
    ["instruments", "Instruments"],
    ["events", "Events"],
    ["users", "Users"],
  ].map(([key, label]) => ({
    key,
    label,
    items: results[key] || [],
  }));
}

export default function Search() {
  const query = useQuery();
  const nav = useNavigate();

  const initialQuery = query.get("q") || "";

  const [searchText, setSearchText] = useState(initialQuery);
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  async function runSearch(value) {
    const q = value.trim();

    setErr("");

    if (q.length < 2) {
      setData(null);
      return;
    }

    setLoading(true);

    try {
      const result = await apiGet(`/api/search/?q=${encodeURIComponent(q)}`);
      setData(result);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setSearchText(initialQuery);
    runSearch(initialQuery);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuery]);

  const groups = useMemo(() => resultGroups(data?.results), [data]);

  function submit(e) {
    e.preventDefault();

    const q = searchText.trim();

    if (!q) return;

    nav(`/search?q=${encodeURIComponent(q)}`);
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Global Search</h1>
          <p className="page-subtitle">
            Search across samples, projects, imports, sequences, alignments,
            users, and audit events.
          </p>
        </div>

        {data && <Badge bg="dark">{data.total || 0} results</Badge>}
      </div>

      {err && <Alert variant="danger">{err}</Alert>}

      <Card className="app-card mb-4">
        <Card.Body>
          <Form onSubmit={submit}>
            <Row className="g-2">
              <Col md={10}>
                <Form.Control
                  value={searchText}
                  onChange={(e) => setSearchText(e.target.value)}
                  placeholder="Search sample ID, project code, instrument, sequence, user, event..."
                  autoFocus
                />
              </Col>

              <Col md={2}>
                <Button type="submit" variant="dark" className="w-100">
                  Search
                </Button>
              </Col>
            </Row>
          </Form>
        </Card.Body>
      </Card>

      {loading ? (
        <div className="d-flex align-items-center gap-2">
          <Spinner animation="border" size="sm" />
          <span>Searching...</span>
        </div>
      ) : !data ? (
        <Card className="app-card">
          <Card.Body>
            <div className="empty-state">
              Enter at least 2 characters to search.
            </div>
          </Card.Body>
        </Card>
      ) : data.total === 0 ? (
        <Card className="app-card">
          <Card.Body>
            <div className="empty-state">No results found.</div>
          </Card.Body>
        </Card>
      ) : (
        <div className="d-grid gap-4">
          {groups
            .filter((group) => group.items.length > 0)
            .map((group) => (
              <Card key={group.key} className="app-card">
                <Card.Body>
                  <div className="toolbar-row mb-3">
                    <h5 className="section-title mb-0">{group.label}</h5>
                    <Badge bg="dark">{group.items.length}</Badge>
                  </div>

                  <div className="d-grid gap-2">
                    {group.items.map((item) => (
                      <Link
                        key={`${group.key}-${item.id}`}
                        to={item.url}
                        className="soft-card text-decoration-none text-dark"
                      >
                        <div className="d-flex justify-content-between align-items-start gap-3">
                          <div>
                            <div className="fw-semibold">{item.title}</div>
                            <div className="feed-meta">{item.subtitle}</div>
                          </div>

                          <Badge bg={typeVariant(item.type)}>
                            {item.type}
                          </Badge>
                        </div>
                      </Link>
                    ))}
                  </div>
                </Card.Body>
              </Card>
            ))}
        </div>
      )}
    </div>
  );
}