import { useEffect, useState } from "react";
import { Alert, Button, Modal, Spinner } from "react-bootstrap";
import { apiGet } from "../api";
import { useLanguage } from "../i18n";
import RevisionComparison, { ValueComparison } from "./ChangeComparison";

function RevisionModal({ event, onClose }) {
  const { t } = useLanguage();
  const [comparison, setComparison] = useState(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    apiGet(`/api/events/${event.id}/comparison/`, { signal: controller.signal }).then(data => {
      if (!data.revision_comparison || !Array.isArray(data.revision_comparison.block_changes)) throw new Error("Comparison unavailable");
      if (!controller.signal.aborted) setComparison(data.revision_comparison);
    }).catch(() => {
      if (!controller.signal.aborted) setError("The comparison is unavailable. Access may have changed or the recorded revisions may no longer be available.");
    });
    return () => controller.abort();
  }, [event.id]);
  return <Modal show onHide={onClose} size="xl" aria-labelledby="audit-comparison-title"><Modal.Header closeButton>
    <Modal.Title id="audit-comparison-title">{t("Revision comparison")}: {event.entity_label}</Modal.Title></Modal.Header>
    <Modal.Body>{error ? <Alert variant="warning">{t(error)}</Alert> : comparison ? <RevisionComparison comparison={comparison} /> : <div role="status"><Spinner size="sm" animation="border" /> {t("Loading comparison...")}</div>}</Modal.Body>
    <Modal.Footer><Button variant="outline-secondary" onClick={onClose}>{t("Close")}</Button></Modal.Footer></Modal>;
}

export default function AuditChangeComparison({ event }) {
  const { t } = useLanguage();
  const [showRevision, setShowRevision] = useState(false);
  return <>
    {event.field_changes?.length > 0 && <details className="mt-2"><summary>{t("Compare changes")} ({event.field_changes.length})</summary>
      {event.field_changes.map(change => <section className="mt-2" key={change.field}><strong>{t(change.label)}</strong>
        <ValueComparison before={change.before} after={change.after} beforePresent={change.before_present} afterPresent={change.after_present} />
        {change.historical_name_missing && <div className="feed-meta">{t("Historical names were not recorded. Original identifiers remain in Technical details.")}</div>}
      </section>)}
    </details>}
    {event.can_compare_revision && <Button size="sm" variant="outline-primary" className="mt-2" onClick={() => setShowRevision(true)}>{t("Compare revision text")}</Button>}
    {showRevision && <RevisionModal key={event.id} event={event} onClose={() => setShowRevision(false)} />}
  </>;
}
