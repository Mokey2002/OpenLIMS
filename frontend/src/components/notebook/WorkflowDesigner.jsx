import { Button, Card, Form, Row, Col } from "react-bootstrap";
import { useLanguage } from "../../i18n";

export default function WorkflowDesigner({ steps, onChange, users, disabled }) {
  const { language } = useLanguage();
  const t = (en, es) => language === "es" ? es : en;
  const change = (index, patch) => onChange(steps.map((step, i) => i === index ? { ...step, ...patch } : step));
  function addField(index) {
    const fields = steps[index].fields;
    let number = 1;
    while (fields.some(field => field.key === `field_${number}`)) number += 1;
    change(index, { fields: [...fields, { key: `field_${number}`, label: "", type: "STRING", required: true }] });
  }
  function move(index, direction) {
    const next = [...steps];
    [next[index], next[index + direction]] = [next[index + direction], next[index]];
    onChange(next);
  }
  return <fieldset disabled={disabled} className="my-4" aria-label={t("Workflow designer", "Diseñador de flujo")}>
    <legend className="h5">{t("Reusable experiment workflow", "Flujo de experimento reutilizable")}</legend>
    <p className="text-muted">{t("Steps run in order. Each needs a responsible person, required values, and a completion note. Saved measurements may fail criteria; completion cannot. Changes apply to new experiments only.", "Los pasos se ejecutan en orden. Cada uno requiere responsable, valores obligatorios y nota de finalización. Se pueden guardar mediciones fuera de criterio, pero no finalizar. Los cambios solo afectan a experimentos nuevos.")}</p>
    {steps.map((step, index) => <Card key={index} className="mb-3" data-testid="workflow-design-step"><Card.Body>
      <div className="d-flex gap-2 align-items-center mb-3"><strong>{t("Step", "Paso")} {index + 1}</strong>
        <Button size="sm" variant="outline-secondary" disabled={index === 0} onClick={() => move(index, -1)}>{t("Move up", "Subir")}</Button>
        <Button size="sm" variant="outline-secondary" disabled={index === steps.length - 1} onClick={() => move(index, 1)}>{t("Move down", "Bajar")}</Button>
        <Button size="sm" variant="outline-danger" onClick={() => onChange(steps.filter((_, i) => i !== index))}>{t("Remove step", "Quitar paso")}</Button>
      </div>
      <Row className="g-2">
        <Col md={6}><Form.Label>{t("Step name", "Nombre del paso")}</Form.Label><Form.Control aria-label={t("Step name", "Nombre del paso")} value={step.name} maxLength={120} onChange={e => change(index, { name: e.target.value })} /></Col>
        <Col md={6}><Form.Label>{t("Default responsible person", "Responsable predeterminado")}</Form.Label><Form.Select aria-label={t("Default responsible person", "Responsable predeterminado")} value={step.assignee || ""} onChange={e => change(index, { assignee: e.target.value ? Number(e.target.value) : null })}><option value="">{t("Assign in each experiment", "Asignar en cada experimento")}</option>{users.map(user => <option value={user.id} key={user.id}>{user.username}</option>)}</Form.Select><Form.Text>{t("Must have edit access to this notebook.", "Debe tener permiso de edición en esta bitácora.")}</Form.Text></Col>
        <Col xs={12}><Form.Label>{t("Instructions", "Instrucciones")}</Form.Label><Form.Control as="textarea" aria-label={t("Instructions", "Instrucciones")} value={step.instructions} maxLength={4000} onChange={e => change(index, { instructions: e.target.value })} /></Col>
        <Col xs={12}><Form.Label>{t("Completion criteria", "Criterios de finalización")}</Form.Label><Form.Control as="textarea" aria-label={t("Completion criteria", "Criterios de finalización")} value={step.completion_criteria} maxLength={2000} onChange={e => change(index, { completion_criteria: e.target.value })} /><Form.Text>{t("The person completing the step confirms these instructions. Field limits below are checked automatically.", "La persona que finaliza confirma estos criterios. Los límites de campos se verifican automáticamente.")}</Form.Text></Col>
      </Row>
      {step.fields.map((field, fieldIndex) => {
        const update = patch => change(index, { fields: step.fields.map((f, i) => i === fieldIndex ? { ...f, ...patch } : f) });
        return <div key={fieldIndex} className="border rounded p-3 my-2" data-testid="workflow-design-field"><Row className="g-2">
          <Col md={4}><Form.Label>{t("Field label", "Etiqueta del campo")}</Form.Label><Form.Control aria-label={t("Field label", "Etiqueta del campo")} value={field.label} maxLength={120} onChange={e => update({ label: e.target.value })} /></Col>
          <Col md={4}><Form.Label>{t("Field key", "Clave del campo")}</Form.Label><Form.Control aria-label={t("Field key", "Clave del campo")} value={field.key} maxLength={64} onChange={e => update({ key: e.target.value })} /><Form.Text>{t("Lowercase letters, digits, underscores; start with a letter.", "Letras minúsculas, números y guiones bajos; iniciar con una letra.")}</Form.Text></Col>
          <Col md={4}><Form.Label>{t("Field type", "Tipo de campo")}</Form.Label><Form.Select aria-label={t("Field type", "Tipo de campo")} value={field.type} onChange={e => change(index, { fields: step.fields.map((f, i) => i === fieldIndex ? { key: f.key, label: f.label, required: f.required, type: e.target.value } : f) })}><option value="STRING">{t("Text", "Texto")}</option><option value="NUMBER">{t("Number", "Número")}</option><option value="BOOLEAN">{t("Yes / No", "Sí / No")}</option></Form.Select></Col>
          {field.type === "NUMBER" && ["minimum", "maximum"].map(bound => <Col md={4} key={bound}><Form.Label>{bound === "minimum" ? t("Minimum", "Mínimo") : t("Maximum", "Máximo")}</Form.Label><Form.Control type="number" step="any" aria-label={bound === "minimum" ? t("Minimum", "Mínimo") : t("Maximum", "Máximo")} value={field[bound] ?? ""} onChange={e => update({ [bound]: e.target.value === "" ? null : Number(e.target.value) })} /></Col>)}
          <Col md={4}><Form.Label>{t("Required value (optional)", "Valor exigido (opcional)")}</Form.Label>{field.type === "BOOLEAN" ? <Form.Select aria-label={t("Required value", "Valor exigido")} value={field.equals === undefined ? "" : String(field.equals)} onChange={e => { const next = { ...field }; if (e.target.value === "") delete next.equals; else next.equals = e.target.value === "true"; change(index, { fields: step.fields.map((f, i) => i === fieldIndex ? next : f) }); }}><option value="">{t("Either", "Cualquiera")}</option><option value="true">{t("Yes", "Sí")}</option><option value="false">No</option></Form.Select> : <Form.Control aria-label={t("Required value", "Valor exigido")} type={field.type === "NUMBER" ? "number" : "text"} step="any" value={field.equals ?? ""} onChange={e => { const next = { ...field }; if (e.target.value === "") delete next.equals; else next.equals = field.type === "NUMBER" ? Number(e.target.value) : e.target.value; change(index, { fields: step.fields.map((f, i) => i === fieldIndex ? next : f) }); }} />}</Col>
        </Row><div className="d-flex gap-3 mt-2"><Form.Check label={t("Required", "Obligatorio")} checked={field.required} onChange={e => update({ required: e.target.checked })} /><Button size="sm" variant="outline-danger" onClick={() => change(index, { fields: step.fields.filter((_, i) => i !== fieldIndex) })}>{t("Remove field", "Quitar campo")}</Button></div></div>;
      })}
      <Button className="mt-2" size="sm" variant="outline-dark" disabled={step.fields.length >= 30} onClick={() => addField(index)}>{t("Add required field", "Añadir campo obligatorio")}</Button>
    </Card.Body></Card>)}
    <Button variant="outline-primary" disabled={steps.length >= 50} onClick={() => onChange([...steps, { name: "", instructions: "", completion_criteria: "", assignee: null, fields: [] }])}>{t("Add workflow step", "Añadir paso al flujo")}</Button>
  </fieldset>;
}
