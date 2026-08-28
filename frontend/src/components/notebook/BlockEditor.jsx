import { Badge, Button, Card, Col, Form, Row } from "react-bootstrap";
import { BLOCK_CATALOG } from "./blockTypes";

function TextField({ value, onChange, ...props }) {
  return <Form.Control value={value ?? ""} onChange={(event) => onChange(event.target.value)} {...props} />;
}

function TableEditor({ rows, disabled, onChange }) {
  const grid = Array.isArray(rows) && rows.length ? rows.map((row) => Array.isArray(row) ? row : [String(row)]) : [[""]];
  const width = Math.max(1, ...grid.map((row) => row.length));
  const normalized = grid.map((row) => [...row, ...Array(Math.max(0, width - row.length)).fill("")]);

  function updateCell(rowIndex, columnIndex, value) {
    onChange(normalized.map((row, ri) => row.map((cell, ci) => ri === rowIndex && ci === columnIndex ? value : cell)));
  }

  return <div className="notebook-table-editor">
    <div className="table-responsive">
      <table className="table table-bordered table-sm align-middle mb-2">
        <tbody>{normalized.map((row, rowIndex) => <tr key={`row-${rowIndex}`}>
          {row.map((cell, columnIndex) => <td key={`cell-${rowIndex}-${columnIndex}`}>
            <Form.Control
              size="sm"
              value={cell ?? ""}
              disabled={disabled}
              aria-label={`Row ${rowIndex + 1}, column ${columnIndex + 1}`}
              onChange={(event) => updateCell(rowIndex, columnIndex, event.target.value)}
            />
          </td>)}
          {!disabled && <td className="notebook-table-action">
            <Button size="sm" variant="link" className="text-danger" disabled={normalized.length === 1} onClick={() => onChange(normalized.filter((_, index) => index !== rowIndex))}>Remove row</Button>
          </td>}
        </tr>)}</tbody>
      </table>
    </div>
    {!disabled && <div className="d-flex gap-2 flex-wrap">
      <Button size="sm" variant="outline-secondary" onClick={() => onChange([...normalized, Array(width).fill("")])}>Add row</Button>
      <Button size="sm" variant="outline-secondary" onClick={() => onChange(normalized.map((row) => [...row, ""]))}>Add column</Button>
      <Button size="sm" variant="outline-danger" disabled={width === 1} onClick={() => onChange(normalized.map((row) => row.slice(0, -1)))}>Remove last column</Button>
    </div>}
  </div>;
}

export default function BlockEditor({
  block,
  index,
  count,
  editable,
  sequenceOptions = [],
  onChange,
  onMove,
  onDuplicate,
  onRemove,
}) {
  const data = block.data || {};
  const meta = BLOCK_CATALOG.find((item) => item.type === block.block_type) || { label: block.block_type, description: "" };
  const update = (field, value) => onChange({ ...block, data: { ...data, [field]: value } });

  let body = null;
  if (block.block_type === "RICH_TEXT") {
    body = <TextField as="textarea" rows={5} value={data.text} disabled={!editable} placeholder="Write observations, rationale, or conclusions..." onChange={(value) => update("text", value)} />;
  } else if (block.block_type === "HEADING") {
    body = <Row className="g-2"><Col md={9}><TextField value={data.text} disabled={!editable} placeholder="Section heading" onChange={(value) => update("text", value)} /></Col><Col md={3}><Form.Select value={data.level || 2} disabled={!editable} onChange={(event) => update("level", Number(event.target.value))}><option value={2}>Heading 2</option><option value={3}>Heading 3</option><option value={4}>Heading 4</option></Form.Select></Col></Row>;
  } else if (block.block_type === "PROTOCOL_STEP") {
    body = <>
      <Form.Check className="mb-2" type="checkbox" checked={Boolean(data.completed)} disabled={!editable} label="Step completed" onChange={(event) => update("completed", event.target.checked)} />
      <TextField as="textarea" rows={3} value={data.text} disabled={!editable} placeholder="Describe the protocol step, quantities, timing, and conditions..." onChange={(value) => update("text", value)} />
      <TextField className="mt-2" value={data.notes} disabled={!editable} placeholder="Deviation or execution notes" onChange={(value) => update("notes", value)} />
    </>;
  } else if (block.block_type === "CHECKLIST") {
    const items = Array.isArray(data.items) ? data.items : [];
    body = <div className="d-grid gap-2">
      {items.map((item, itemIndex) => <div className="d-flex gap-2 align-items-center" key={`item-${itemIndex}`}>
        <Form.Check type="checkbox" checked={Boolean(item.checked)} disabled={!editable} aria-label={`Checklist item ${itemIndex + 1}`} onChange={(event) => update("items", items.map((row, ri) => ri === itemIndex ? { ...row, checked: event.target.checked } : row))} />
        <Form.Control value={item.text || ""} disabled={!editable} onChange={(event) => update("items", items.map((row, ri) => ri === itemIndex ? { ...row, text: event.target.value } : row))} />
        {editable && <Button size="sm" variant="outline-danger" aria-label={`Remove checklist item ${itemIndex + 1}`} onClick={() => update("items", items.filter((_, ri) => ri !== itemIndex))}>Remove</Button>}
      </div>)}
      {editable && <Button size="sm" variant="outline-secondary" className="justify-self-start" onClick={() => update("items", [...items, { text: "", checked: false }])}>Add checklist item</Button>}
    </div>;
  } else if (block.block_type === "TABLE") {
    body = <TableEditor rows={data.rows} disabled={!editable} onChange={(rows) => update("rows", rows)} />;
  } else if (block.block_type === "STRUCTURED_RESULT") {
    body = <Row className="g-2">
      <Col md={4}><Form.Label>Result name</Form.Label><TextField value={data.name} disabled={!editable} onChange={(value) => update("name", value)} /></Col>
      <Col md={3}><Form.Label>Value</Form.Label><TextField value={data.value} disabled={!editable} onChange={(value) => update("value", value)} /></Col>
      <Col md={2}><Form.Label>Unit</Form.Label><TextField value={data.unit} disabled={!editable} onChange={(value) => update("unit", value)} /></Col>
      <Col md={3}><Form.Label>State</Form.Label><Form.Select value={data.status || "RECORDED"} disabled={!editable} onChange={(event) => update("status", event.target.value)}><option value="RECORDED">Recorded</option><option value="PASS">Pass</option><option value="FAIL">Fail</option><option value="INCONCLUSIVE">Inconclusive</option></Form.Select></Col>
      <Col xs={12}><TextField value={data.notes} disabled={!editable} placeholder="Result notes or acceptance criteria" onChange={(value) => update("notes", value)} /></Col>
    </Row>;
  } else if (block.block_type === "CALCULATION") {
    body = <Row className="g-2">
      <Col md={6}><Form.Label>Expression</Form.Label><TextField value={data.expression} disabled={!editable} placeholder="e.g. concentration × volume" onChange={(value) => update("expression", value)} /></Col>
      <Col md={3}><Form.Label>Result</Form.Label><TextField value={data.result} disabled={!editable} onChange={(value) => update("result", value)} /></Col>
      <Col md={3}><Form.Label>Unit</Form.Label><TextField value={data.unit} disabled={!editable} onChange={(value) => update("unit", value)} /></Col>
      <Col xs={12}><TextField value={data.notes} disabled={!editable} placeholder="Inputs, assumptions, or rounding notes" onChange={(value) => update("notes", value)} /></Col>
    </Row>;
  } else if (block.block_type === "IMAGE") {
    body = <Row className="g-2">
      <Col md={8}><Form.Label>Image URL</Form.Label><TextField type="url" value={data.url} disabled={!editable} placeholder="https://..." onChange={(value) => update("url", value)} /></Col>
      <Col md={4}><Form.Label>Alternative text</Form.Label><TextField value={data.alt} disabled={!editable} onChange={(value) => update("alt", value)} /></Col>
      <Col xs={12}><TextField value={data.caption} disabled={!editable} placeholder="Figure caption" onChange={(value) => update("caption", value)} /></Col>
      {data.url && <Col xs={12}><img className="notebook-image-preview" src={data.url} alt={data.alt || data.caption || "Experiment figure"} /></Col>}
    </Row>;
  } else if (block.block_type === "ATTACHMENT") {
    body = <Row className="g-2">
      <Col md={4}><Form.Label>File name</Form.Label><TextField value={data.name} disabled={!editable} onChange={(value) => update("name", value)} /></Col>
      <Col md={8}><Form.Label>File URL</Form.Label><TextField type="url" value={data.url} disabled={!editable} placeholder="Link to the stored attachment" onChange={(value) => update("url", value)} /></Col>
      <Col xs={12}><TextField value={data.description} disabled={!editable} placeholder="Attachment description" onChange={(value) => update("description", value)} /></Col>
      {data.sha256 && <Col xs={12}><div className="feed-meta">{data.media_type || "File"} · {data.size_bytes || 0} bytes · SHA-256 <code>{data.sha256}</code></div></Col>}
    </Row>;
  } else if (block.block_type === "SEQUENCE_VIEW") {
    body = <Row className="g-2">
      <Col md={5}><Form.Label>Sequence</Form.Label><Form.Select value={data.sequence_public_id || ""} disabled={!editable} onChange={(event) => {
        const sequence = sequenceOptions.find((row) => String(row.public_id) === event.target.value);
        onChange({ ...block, data: { ...data, sequence_public_id: event.target.value, label: sequence?.name || sequence?.title || sequence?.identifier || data.label || "" } });
      }}><option value="">Choose sequence</option>{sequenceOptions.map((sequence) => <option value={sequence.public_id} key={sequence.public_id}>{sequence.name || sequence.title || sequence.identifier || sequence.public_id}</option>)}</Form.Select></Col>
      <Col md={3}><Form.Label>Display label</Form.Label><TextField value={data.label} disabled={!editable} onChange={(value) => update("label", value)} /></Col>
      <Col md={1}><Form.Label>Start</Form.Label><TextField type="number" min="1" value={data.start} disabled={!editable} onChange={(value) => update("start", value)} /></Col>
      <Col md={1}><Form.Label>End</Form.Label><TextField type="number" min="1" value={data.end} disabled={!editable} onChange={(value) => update("end", value)} /></Col>
      <Col md={2}><Form.Label>Strand</Form.Label><Form.Select value={data.strand || "+"} disabled={!editable} onChange={(event) => update("strand", event.target.value)}><option value="+">Forward (+)</option><option value="-">Reverse (-)</option></Form.Select></Col>
    </Row>;
  }

  return <Card className={`notebook-block mb-3 ${data.completed ? "notebook-block-complete" : ""}`}>
    <Card.Body>
      <div className="toolbar-row mb-3">
        <div><Badge bg="light" text="dark" className="me-2">{index + 1}</Badge><strong>{meta.label}</strong><div className="feed-meta mt-1">{meta.description}</div></div>
        {editable && <div className="inline-actions">
          <Button size="sm" variant="outline-secondary" disabled={index === 0} title="Move block up" aria-label="Move block up" onClick={() => onMove(-1)}>↑</Button>
          <Button size="sm" variant="outline-secondary" disabled={index === count - 1} title="Move block down" aria-label="Move block down" onClick={() => onMove(1)}>↓</Button>
          <Button size="sm" variant="outline-secondary" onClick={onDuplicate}>Duplicate</Button>
          <Button size="sm" variant="outline-danger" onClick={onRemove}>Remove</Button>
        </div>}
      </div>
      {body}
    </Card.Body>
  </Card>;
}
