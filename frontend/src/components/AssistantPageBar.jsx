import { Button, Form } from "react-bootstrap";
import { Link } from "react-router-dom";
import { useAssistantPage } from "../assistantPageContext";

export default function AssistantPageBar({ onRun, disabled, selection, onClear, onOpen }) {
  const shared = useAssistantPage();
  const selected = selection !== undefined;
  const available = selected ? selection : shared?.available;
  if (!available) return null;
  const page = selected ? selection : shared.page;
  const kind = available.kind;
  const questions = kind === "sample" ? ["Summarize this sample", "Why is this blocked?", "Show results for this sample"]
    : ["Summarize this project", "Show samples in this project", "Show results for this project"];
  return <div className="assistant-context-bar" aria-label="Current page context">
    <div className="w-100">
      {selected ? <div className="d-flex justify-content-between gap-2"><strong>Selected {kind}: {available.label}</strong>
        <Button size="sm" variant="outline-secondary" onClick={onClear} disabled={disabled}>Clear page selection</Button></div>
        : <Form.Check type="switch" id="assistant-use-page" label={`Use this ${kind}: ${available.label}`} checked={Boolean(page)}
          onChange={event => shared.setEnabled(event.target.checked)} disabled={disabled} />}
      <div className="small text-muted">{page ? "Applies to supported questions about “this” record. Other questions keep their own targets."
        : "Page context is off. Existing conversation context still applies."}</div>
      {page && <div className="d-flex flex-wrap gap-1 mt-2">
        {questions.map(question => <Button key={question} variant="outline-secondary" size="sm" disabled={disabled} onClick={() => onRun(question)}>{question}</Button>)}
      </div>}
      {!selected && page && <Link className="small" to="/assistant" state={{ assistantPage: page }} onClick={onOpen}>Open assistant with this record</Link>}
    </div>
  </div>;
}
