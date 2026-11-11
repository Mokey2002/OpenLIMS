import { useState } from "react";
import { Alert, Button, Form, Modal } from "react-bootstrap";
import { ValueComparison } from "../ChangeComparison";
import { useLanguage } from "../../i18n";

export default function DraftRecovery({ draft, current, canRestore, onRestore, onDiscard }) {
  const { t, locale } = useLanguage();
  const [show, setShow] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const stale = draft.baseRevision !== (current.current_revision_detail?.public_id || "");
  const savedBlocks = current.current_revision_detail?.blocks || [];
  const count = Math.max(savedBlocks.length, draft.blocks.length);
  return <>
    <Alert variant="warning" role="status">
      <strong>{t("A recovery copy is available for this experiment.")}</strong>
      <p className="mb-2">{t("Recovered edits have not been saved to the server.")} {new Date(draft.savedAt).toLocaleString(locale)}</p>
      {stale && <p>{t("The saved experiment changed after this copy was made. Review both versions before restoring.")}</p>}
      {!canRestore && <p>{t("This experiment is read-only. You can review or download your recovery copy.")}</p>}
      <div className="d-flex flex-wrap gap-2"><Button size="sm" variant="dark" onClick={() => setShow(true)}>{t("Review recovered draft")}</Button><Button size="sm" variant="outline-secondary" onClick={() => { if (window.confirm(t("Discard this recovery copy permanently?"))) onDiscard(); }}>{t("Discard recovery copy")}</Button></div>
    </Alert>
    <Modal show={show} onHide={() => setShow(false)} size="xl" scrollable><Modal.Header closeButton><Modal.Title>{t("Review recovered draft")}</Modal.Title></Modal.Header>
      <Modal.Body>
        <p>{t("Before is the current saved experiment. After is your recovery copy.")}</p>
        {Array.from({ length: count }, (_, index) => <section key={index} className="mb-3"><h6>{t("Block")} {index + 1}</h6><ValueComparison before={savedBlocks[index] ? { block_type: savedBlocks[index].block_type, data: savedBlocks[index].data } : undefined} after={draft.blocks[index]} beforePresent={Boolean(savedBlocks[index])} afterPresent={Boolean(draft.blocks[index])} /></section>)}
        <h6>{t("Linked records")}</h6><ValueComparison before={current.current_revision_detail?.links || []} after={draft.links} />
        <details><summary>{t("Complete recovery copy")}</summary><pre className="change-value" translate="no">{JSON.stringify(draft, null, 2)}</pre></details>
        {stale && canRestore && <Form.Check id="review-recovered-draft" checked={reviewed} onChange={event => setReviewed(event.target.checked)} label={t("I reviewed the current saved content and want to use this recovered draft.")} />}
      </Modal.Body><Modal.Footer>
        <Button variant="outline-secondary" onClick={() => {
          const url = URL.createObjectURL(new Blob([JSON.stringify(draft, null, 2)], { type: "application/json" }));
          const link = document.createElement("a"); link.href = url; link.download = `openlims-recovery-${current.public_id}.json`; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
        }}>{t("Download recovery copy")}</Button>
        <Button variant="secondary" onClick={() => setShow(false)}>{t("Close")}</Button>
        {canRestore && <Button variant="primary" disabled={stale && !reviewed} onClick={() => { onRestore(); setShow(false); }}>{t("Restore draft for editing")}</Button>}
      </Modal.Footer>
    </Modal>
  </>;
}
