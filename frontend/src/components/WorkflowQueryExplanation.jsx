import { describeWorkflowFilters } from "../assistantContext.js";

export default function WorkflowQueryExplanation({ explanation }) {
  if (!explanation) return null;
  const spanish = explanation.language === "es";
  return (
    <section className="border rounded p-3 my-2" aria-label={explanation.title}>
      <h3 className="h6">{explanation.title}</h3>
      <p className="mb-2">{explanation.match_description}</p>
      <p className="mb-2">{explanation.scope_description}</p>
      {explanation.assignee_description && <p>{explanation.assignee_description}</p>}
      <h4 className="h6">{spanish ? "Significado de los filtros" : "Filter meanings"}</h4>
      <ul>
        {explanation.filters.map((filter) => <li key={filter.key}><strong>{describeWorkflowFilters({ language: explanation.language, assignee: explanation.assignee, filters: [filter.key] })}:</strong> {filter.meaning}</li>)}
      </ul>
      {explanation.notes.map((note, index) => <p className="small mb-2" key={index}>{note}</p>)}
    </section>
  );
}
