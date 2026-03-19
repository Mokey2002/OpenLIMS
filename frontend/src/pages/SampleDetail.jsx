import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Alert, Badge, Button, Card, Spinner } from "react-bootstrap";
import { apiGet, apiPost } from "../api";

export default function SampleDetail() {
  const { id } = useParams();

  const [sample, setSample] = useState(null);
  const [allowed, setAllowed] = useState([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");

  async function load() {
    setLoading(true);
    setErr("");

    try {
      const s = await apiGet(`/api/samples/${id}/`);
      const t = await apiGet(`/api/samples/${id}/allowed-transitions/`);

      setSample(s);
      setAllowed(t.allowed_transitions || []);
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

      await load(); // refresh
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

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

  if (loading) return <Spinner />;

  return (
    <div className="w-100">
      <h2 className="mb-3">Sample Detail</h2>

      {err && <Alert variant="danger">{err}</Alert>}

      {sample && (
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
      )}
    </div>
  );
}
