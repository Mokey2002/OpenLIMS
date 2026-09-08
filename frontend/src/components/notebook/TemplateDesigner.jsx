import { useState } from "react";
import { Alert, Button, Form, Modal } from "react-bootstrap";
import { apiPatch } from "../../api";
import { useLanguage } from "../../i18n";
import BlockEditor from "./BlockEditor";
import { BLOCK_CATALOG, newBlock } from "./blockTypes";

export default function TemplateDesigner({ template, onClose, onSaved }) {
  const { language } = useLanguage();
  const t = (en, es) => language === "es" ? es : en;
  const [name, setName] = useState(template.name);
  const [description, setDescription] = useState(template.description);
  const [blocks, setBlocks] = useState(() => template.blocks.map(block => ({ ...structuredClone(block), _key: newBlock(block.block_type)._key })));
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  function move(index, direction) {
    const next = [...blocks], target = index + direction;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setBlocks(next);
  }
  async function save() {
    setBusy(true); setError("");
    try {
      const updated = await apiPatch(`/api/experiment-templates/${template.id}/`, {
        name, description, expected_updated_at: template.updated_at,
        blocks: blocks.map(({ block_type, data }) => ({ block_type, data })),
      });
      onSaved(updated);
    } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  return <Modal show size="xl" onHide={busy ? () => {} : onClose} backdrop="static">
    <Modal.Header closeButton={!busy}><Modal.Title>{t("Design experiment template", "Diseñar plantilla de experimento")}</Modal.Title></Modal.Header>
    <Modal.Body>
      {error && <Alert variant="danger">{error}</Alert>}
      <Alert variant="info">{t("Changes apply to future experiments. Existing experiment content and revisions are preserved.", "Los cambios se aplican a futuros experimentos. Se conservan el contenido y las revisiones de los experimentos existentes.")}</Alert>
      <Form.Label htmlFor="designer-name">{t("Template name", "Nombre de plantilla")}</Form.Label>
      <Form.Control id="designer-name" maxLength={255} disabled={busy} value={name} onChange={e => setName(e.target.value)} />
      <Form.Label htmlFor="designer-description">{t("Description", "Descripción")}</Form.Label>
      <Form.Control id="designer-description" as="textarea" disabled={busy} value={description} onChange={e => setDescription(e.target.value)} />
      <div className="my-3 d-flex gap-2 flex-wrap">{BLOCK_CATALOG.filter(b => !["IMAGE", "ATTACHMENT", "SEQUENCE_VIEW"].includes(b.type)).map(b => <Button key={b.type} size="sm" disabled={busy} variant="outline-dark" onClick={() => setBlocks([...blocks, newBlock(b.type)])}>{t("Add", "Añadir")} {t(b.label, ({ RICH_TEXT: "Texto enriquecido", HEADING: "Encabezado", PROTOCOL_STEP: "Paso de protocolo", CHECKLIST: "Lista de verificación", TABLE: "Tabla", STRUCTURED_RESULT: "Resultado estructurado", CALCULATION: "Cálculo" })[b.type])}</Button>)}</div>
      {blocks.map((block, index) => <BlockEditor key={block._key} block={block} index={index} count={blocks.length} editable={!busy}
        onChange={next => setBlocks(blocks.map((b, i) => i === index ? next : b))} onMove={direction => move(index, direction)}
        onDuplicate={() => { const next = [...blocks]; next.splice(index + 1, 0, { ...structuredClone(block), _key: newBlock(block.block_type)._key }); setBlocks(next); }}
        onRemove={() => setBlocks(blocks.filter((_, i) => i !== index))} />)}
    </Modal.Body>
    <Modal.Footer><Button disabled={busy} variant="outline-secondary" onClick={onClose}>{t("Cancel", "Cancelar")}</Button><Button disabled={busy || !name.trim()} onClick={save}>{t("Save structure", "Guardar estructura")}</Button></Modal.Footer>
  </Modal>;
}
