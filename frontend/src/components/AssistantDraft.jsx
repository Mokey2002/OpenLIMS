import { useState } from "react";
import { Button, Form } from "react-bootstrap";

export default function AssistantDraft({ draft }) {
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
    <Form.Control as="textarea" rows={9} aria-label="Project update draft / Borrador de actualización"
      value={text} onChange={event => { setText(event.target.value); setNotice(""); }} />
    <div className="small text-muted my-1">Editable draft; changes stay in this chat view. / Borrador editable; los cambios quedan en esta vista.</div>
    <Button size="sm" variant="outline-secondary" onClick={copy}>Copy draft / Copiar borrador</Button>
    <span className="ms-2" role="status">{notice}</span>
  </div>;
}
