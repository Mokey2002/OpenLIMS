import { Link } from "react-router-dom";
import ComparisonTable from "./ComparisonTable";

export default function AssistantEvidence({ citations = [], readPlan = null }) {
  if (!citations.length && !readPlan) return null;
  return <details className="my-2 small" aria-label="Answer sources and scope">
    <summary>Sources and scope / Fuentes y alcance ({citations.length})</summary>
    {readPlan && <div className="mt-2">
      <div>{readPlan.partial ? "Some requested information was unavailable." : "Completed read-only checks."}</div>
      <div className="text-muted">{readPlan.scope}</div>
      <div className="text-muted">{readPlan.as_of}</div>
      {readPlan.steps.map((step, index) => <div className="mt-2" key={index}>
        <strong>{index + 1}. {step.operation.replaceAll("_", " ")} — {step.status}</strong>
        {step.comparison && <ComparisonTable comparison={step.comparison} />}
      </div>)}
    </div>}
    <ul className="mt-2">
      {citations.map((source, index) => <li className="mb-2" key={`${source.url}-${index}`}>
        {source.url?.startsWith("/") && !source.url.startsWith("//")
          ? <Link to={source.url}>{source.label}</Link> : <strong>{source.label}</strong>}
        {source.scope && <div className="text-muted">{source.scope}</div>}
        {source.excerpt && <blockquote className="mb-0">{source.excerpt}</blockquote>}
        {source.excerpt_truncated && <div className="text-muted">Excerpt; open the full section to review it.</div>}
      </li>)}
    </ul>
  </details>;
}
