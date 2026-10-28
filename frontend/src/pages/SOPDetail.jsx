import { useEffect, useState } from "react";
import { Alert, Spinner } from "react-bootstrap";
import { useParams } from "react-router-dom";
import { apiGet } from "../api";

export default function SOPDetail() {
  const { id } = useParams();
  const [state, setState] = useState({ id, loading: true });
  useEffect(() => {
    let active = true;
    apiGet(`/api/sop-documents/${encodeURIComponent(id)}/`).then(
      (document) => { if (active) setState({ id, document }); },
      () => { if (active) setState({ id, error: "This SOP section is unavailable or you no longer have access." }); },
    );
    return () => { active = false; };
  }, [id]);
  if (state.id !== id || state.loading) return <Spinner animation="border" role="status" aria-label="Loading SOP" />;
  if (state.error) return <Alert variant="warning">{state.error}</Alert>;
  const document = state.document;
  return <article className="card p-4">
    <h1 className="h4">{document.document_code} — {document.title}</h1>
    <p>Version {document.version} · Section {document.section}</p>
    <p className="text-muted">{document.status} · {document.approved ? "Approved" : "Not approved"} · Effective {document.effective_at}</p>
    <div style={{ whiteSpace: "pre-wrap" }}>{document.content}</div>
  </article>;
}
