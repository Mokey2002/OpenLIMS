const labels = {
  handover: "Shift handover", workflow_draft: "Workflow draft", compare_runs: "Experiment comparison",
  sample_history: "Sample history", similar_experiments: "Related experiments", reagent_plan: "Reagent planning",
  project_update: "Project update", quarantine_impact: "Quarantine impact preview", data_quality: "Data-quality review",
  guided_actions: "Guided work change", sample_guidance: "Next-step guidance", project_workflows: "Project work overview",
};
const fieldLabels = { source: "Work assigned to", recipient: "Handing over to", left: "First experiment", right: "Second experiment", count: "Number of samples", command: "Request" };

export default function AssistantInterpretation({ interpretation }) {
  if (!interpretation) return null;
  return <details className="small text-muted my-2">
    <summary>How I understood your request / Cómo entendí tu solicitud</summary>
    <div>{labels[interpretation.tool] || String(interpretation.tool || "").replaceAll("_", " ")}</div>
    <dl>{Object.entries(interpretation.arguments || {}).map(([key, value]) => <div key={key}>
      <dt>{fieldLabels[key] || key.replaceAll("_", " ")}</dt><dd>{String(value)}</dd>
    </div>)}</dl>
    <div>Interpreted by / Interpretado por: {interpretation.provider === "openai" ? "OpenAI" : interpretation.provider === "ollama" ? "Ollama" : "OpenLIMS"}</div>
    <div>OpenLIMS checks access and executes the feature. Changes still require confirmation or explicit saving. / OpenLIMS comprueba el acceso. Los cambios requieren confirmación o guardado explícito.</div>
  </details>;
}
