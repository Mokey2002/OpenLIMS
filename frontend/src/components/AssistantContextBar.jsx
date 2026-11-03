import { Button } from "react-bootstrap";
import { describeAssistantContext } from "../assistantContext";
import AssistantResultFilters from "./AssistantResultFilters";

export default function AssistantContextBar({
  context,
  onClear,
  compact = false,
  disabled = false,
  onRun,
}) {
  const summary = describeAssistantContext(context);
  if (!summary) return null;

  return (
    <div
      className={`assistant-context-bar ${compact ? "assistant-context-bar-compact" : ""}`}
      data-context-kind={summary.kind}
      aria-live="polite"
    >
      <div className="assistant-context-copy">
        <div className="assistant-context-eyebrow">Active context</div>
        <div className="assistant-context-label">{summary.label}</div>
        {summary.detail && (
          <div className="assistant-context-detail">{summary.detail}</div>
        )}
      </div>
      <Button
        type="button"
        size="sm"
        variant="outline-secondary"
        className="assistant-context-clear"
        onClick={onClear}
        disabled={disabled}
        aria-label={`Clear ${summary.label} context`}
      >
        Clear
      </Button>
      {onRun && <AssistantResultFilters context={context} onRun={onRun} disabled={disabled} />}
    </div>
  );
}
