import { useState } from "react";
import { Button, Form } from "react-bootstrap";
import { useNavigate } from "react-router-dom";

export default function AssistantDraft({ draft }) {
  const navigate = useNavigate();
  const [text, setText] = useState(draft.text);
  const [notice, setNotice] = useState("");
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setNotice("Copied / Copiado");
    } catch {
      setNotice("Select the text and copy it manually. / Selecciona el texto y cópialo.");
    }
  }
  return <div className="my-3">
    <Form.Control as="textarea" rows={9} aria-label="Editable draft / Borrador editable"
      value={text} onChange={event => { setText(event.target.value); setNotice(""); }} />
    <div className="small text-muted my-1">Editable draft; changes stay in this chat view. / Borrador editable; los cambios quedan en esta vista.</div>
    <Button size="sm" variant="outline-secondary" onClick={copy}>Copy draft / Copiar borrador</Button>
    {draft.workflow && <Button size="sm" className="ms-2" onClick={() => navigate("/workflow-designer", { state: { assistantWorkflowDraft: draft.workflow } })}>
      Review workflow in designer / Revisar flujo en el diseñador
    </Button>}
    {draft.workflow && <div className="small text-muted">The designer uses the resolved procedure list. Text edits above only change the copyable note. / El diseñador usa los procedimientos resueltos; editar el texto solo cambia la nota.</div>}
    <span className="ms-2" role="status">{notice}</span>
  </div>;
}
