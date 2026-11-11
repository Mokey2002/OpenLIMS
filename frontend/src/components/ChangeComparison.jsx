import { useMemo } from "react";
import { Alert, Badge, Table } from "react-bootstrap";
import { useLanguage } from "../i18n";
import { compareText, comparisonText } from "../utils/textComparison";
import "./ChangeComparison.css";

function Highlight({ parts }) {
  return <div className="change-value" translate="no">{parts.map((part, index) => part.type === "removed"
    ? <del key={index}>{part.text}</del> : part.type === "added" ? <ins key={index}>{part.text}</ins> : <span key={index}>{part.text}</span>)}</div>;
}

function blockData(block) {
  const data = block?.data;
  return data && Object.keys(data).length === 1 && typeof data.text === "string" ? data.text : data;
}

export function ValueComparison({ before, after, beforePresent = true, afterPresent = true }) {
  const { t } = useLanguage();
  const diff = useMemo(() => compareText(comparisonText(beforePresent ? before : undefined), comparisonText(afterPresent ? after : undefined)), [before, after, beforePresent, afterPresent]);
  return <>
    <Table bordered responsive size="sm" className="change-comparison mb-2"><thead><tr><th scope="col">{t("Before")}</th><th scope="col">{t("After")}</th></tr></thead>
      <tbody><tr><td><Highlight parts={diff.before} /></td><td><Highlight parts={diff.after} /></td></tr></tbody></Table>
    {diff.truncated && <p className="feed-meta">{t("Long values are shortened in this preview. The complete values remain in Technical details.")}</p>}
  </>;
}

export default function RevisionComparison({ comparison }) {
  const { t } = useLanguage();
  if (!comparison) return null;
  return <div className="notebook-comparison mt-3">
    <div className="inline-actions mb-2"><Badge bg="primary">r{comparison.before?.number ?? 0} → r{comparison.after?.number}</Badge>
      <span>{t("Deleted text is struck through. Added text is underlined.")}</span></div>
    {!comparison.block_changes?.length && !comparison.link_changes?.length && <Alert variant="info">{t("These revisions have identical content.")}</Alert>}
    {(comparison.block_changes || []).map(change => <section className="notebook-change mb-3" key={`${change.position}-${change.change}`}>
      <h6>{t("Block")} {change.position + 1} · {t(change.change === "added" ? "Added" : change.change === "removed" ? "Removed" : "Modified")}</h6>
      {change.before?.block_type !== change.after?.block_type && <p>{t("Block type")}: {change.before?.block_type || "—"} → {change.after?.block_type || "—"}</p>}
      <ValueComparison before={blockData(change.before)} after={blockData(change.after)} beforePresent={Boolean(change.before)} afterPresent={Boolean(change.after)} />
    </section>)}
    {(comparison.link_changes || []).map((change, index) => <section className="mb-3" key={index}><h6>{t("Linked record")}: {change.after?.label || change.before?.label || t("Name unavailable")}</h6>
      <ValueComparison before={change.before ? { label: change.before.label, relationship: change.before.relation_type, version: change.before.version } : undefined}
        after={change.after ? { label: change.after.label, relationship: change.after.relation_type, version: change.after.version } : undefined}
        beforePresent={Boolean(change.before)} afterPresent={Boolean(change.after)} /></section>)}
    <details><summary>{t("Technical details")}</summary><pre className="change-value" translate="no">{JSON.stringify(comparison, null, 2)}</pre></details>
  </div>;
}
