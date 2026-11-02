import { useEffect, useState } from "react";
import { Alert, Button, Form } from "react-bootstrap";
import { apiDelete, apiGet, apiPatch, apiPost } from "../api";

export default function AssistantConversations({ conversationId, onSelect, history, disabled, onNew }) {
  const [items, setItems] = useState([]);
  const [selected, setSelected] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  useEffect(() => {
    let active = true;
    apiGet("/api/assistant/conversations/").then(data => { if (active) setItems(Array.isArray(data) ? data : []); }, () => {});
    return () => { active = false; };
  }, []);
  async function action(kind) {
    setError(""); setBusy(true);
    try {
      if (kind === "save") {
        const data = await apiPost("/api/assistant/conversations/", {
          name, turn_tokens: history.filter(item => item.saveToken).map(item => item.saveToken).slice(-20),
        });
        setSelected(data.id);
        onSelect({ id: data.id });
      } else if (kind === "open") {
        const data = await apiGet(`/api/assistant/conversations/${selected}/`);
        onSelect(data);
        setName(data.name);
      } else if (kind === "rename") {
        await apiPatch(`/api/assistant/conversations/${selected}/`, { name });
      } else {
        await apiDelete(`/api/assistant/conversations/${selected}/`);
        if (selected === conversationId) onNew();
        setSelected(""); setDeleting(false);
      }
      setItems(await apiGet("/api/assistant/conversations/"));
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  }
  return <details className="small my-2" aria-label="Saved assistant conversations">
    <summary>Saved conversations{conversationId ? " · saving this chat" : ""}</summary>
    <p className="text-muted my-2">Save named chats to reopen them later. Laboratory answers refresh with your current access.</p>
    {error && <Alert variant="warning">{error}</Alert>}
    <Form.Control aria-label="Conversation name" value={name} onChange={e => setName(e.target.value)} maxLength={80} placeholder="Conversation name" disabled={disabled || busy} />
    <Form.Select aria-label="Saved conversation" value={selected} onChange={e => { setSelected(e.target.value); setDeleting(false); }} className="my-2" disabled={disabled || busy}>
      <option value="">Choose a conversation</option>
      {items.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
    </Form.Select>
    <div className="d-flex gap-2 flex-wrap">
      <Button size="sm" onClick={() => action("save")} disabled={disabled || busy || !name.trim()}>Save as new chat</Button>
      <Button size="sm" variant="outline-secondary" onClick={() => action("open")} disabled={disabled || busy || !selected}>Open saved chat</Button>
      <Button size="sm" variant="outline-secondary" onClick={() => action("rename")} disabled={disabled || busy || !selected || !name.trim()}>Rename chat</Button>
      <Button size="sm" variant="outline-danger" onClick={() => setDeleting(true)} disabled={disabled || busy || !selected}>Delete chat</Button>
      <Button size="sm" variant="outline-secondary" onClick={onNew} disabled={disabled || busy}>New unsaved chat</Button>
      {deleting && <Button size="sm" variant="danger" onClick={() => action("delete")} disabled={disabled || busy}>Confirm delete chat</Button>}
    </div>
  </details>;
}
