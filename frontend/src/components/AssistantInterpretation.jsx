export default function AssistantInterpretation({ interpretation }) {
  if (!interpretation) return null;
  return <details className="small text-muted my-2">
    <summary>{interpretation.provider === "openai" ? "OpenAI" : "Ollama"} interpreted this request / interpretó esta solicitud</summary>
    <div>OpenLIMS feature / Función: {interpretation.tool}</div>
    <pre className="text-wrap">{JSON.stringify(interpretation.arguments, null, 2)}</pre>
    <div>OpenLIMS checks access and executes the feature. Changes still require confirmation or explicit saving. / OpenLIMS comprueba el acceso. Los cambios requieren confirmación o guardado explícito.</div>
  </details>;
}
