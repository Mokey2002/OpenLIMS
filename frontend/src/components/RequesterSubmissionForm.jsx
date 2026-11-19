import { useState } from "react";
import { Alert, Button, Form } from "react-bootstrap";
import { useNavigate } from "react-router-dom";
import { apiPost } from "../api";
import useFormFeedback from "../hooks/useFormFeedback";
import { useLanguage } from "../i18n";
import { createClientId } from "../utils/clientId";
import { ApiError } from "../utils/formErrors";
import FeedbackForm, { FormField } from "./FeedbackForm";

function testFields(schema) {
  const properties = schema?.properties || {};
  const required = schema?.required || [];
  return [...new Set([...Object.keys(properties), ...required])].map((key) => ({
    ...properties[key], key, required: required.includes(key),
  }));
}

function TestField({ field, value, onChange }) {
  const { t } = useLanguage();
  const props = { required: field.required, value, onChange };
  const numeric = field.type === "number" || field.type === "integer";
  const structured = field.type === "array" || field.type === "object";
  const options = field.enum ?? (field.type === "boolean" ? [true, false] : null);
  const optionLabel = (option) => typeof option === "boolean"
    ? t(option ? "Yes" : "No")
    : typeof option === "string" ? option : JSON.stringify(option);

  return <FormField
    name={`form_data.${field.key}`}
    label={typeof field.title === "string" ? field.title : field.key.replaceAll("_", " ")}
    hint={typeof field.description === "string" ? field.description : structured ? "Enter a JSON value for this field." : undefined}
  >
    {options
      ? <Form.Select {...props}>
        <option value="">{t("Select an option")}</option>
        {options.map((option, index) => <option key={index} value={index}>{optionLabel(option)}</option>)}
      </Form.Select>
      : <Form.Control {...props} as={structured ? "textarea" : "input"}
        type={numeric ? "number" : undefined} step={numeric ? (field.type === "integer" ? "1" : "any") : undefined}
        maxLength={4000} />}
  </FormField>;
}

function encodeTestValues(fields, values) {
  const result = [];
  for (const field of fields) {
    const raw = values[field.key];
    if (typeof raw !== "string" || !raw.trim()) continue;
    let value = raw.trim();
    if (field.enum) value = field.enum[Number(raw)];
    else if (field.type === "boolean") value = raw === "0";
    else if (field.type === "number" || field.type === "integer") value = Number(raw);
    else if (field.type === "array" || field.type === "object") {
      try { value = JSON.parse(raw); }
      catch { throw new ApiError(400, { form_data: { [field.key]: "Enter a valid JSON value." } }); }
    }
    result.push([field.key, value]);
  }
  return Object.fromEntries(result);
}

export default function RequesterSubmissionForm({ catalog, requestPath }) {
  const { t } = useLanguage();
  const navigate = useNavigate();
  const feedback = useFormFeedback();
  const { projects, tests } = catalog;
  const [submissionId] = useState(createClientId);
  const [project, setProject] = useState(() => projects.length === 1 ? String(projects[0].id) : "");
  const [testId, setTestId] = useState("");
  const [title, setTitle] = useState("");
  const [references, setReferences] = useState("");
  const [values, setValues] = useState({});
  const availableTests = tests.filter(test => !test.project_id || String(test.project_id) === project);
  const test = availableTests.find(row => String(row.id) === testId);
  const fields = testFields(test?.form_schema);

  async function submit() {
    const sampleReferences = references.split(/\r?\n/).map(line => line.trim()).filter(Boolean);
    if (!sampleReferences.length || sampleReferences.length > 50 || sampleReferences.some(ref => ref.length > 64)) {
      throw new ApiError(400, { sample_references: "Enter 1 to 50 sample references, up to 64 characters per line." });
    }

    const created = await apiPost(requestPath, {
      submission_id: submissionId,
      project: Number(project),
      request_type: Number(testId),
      title,
      sample_references: sampleReferences,
      form_data: encodeTestValues(fields, values),
    });
    navigate(`/requester/${created.public_id}`, { state: { submitted: true } });
  }

  if (!projects.length) return <Alert variant="light" className="mb-0">
    {t("Ask the lab to give you access to a project before submitting a request.")}
  </Alert>;
  if (!tests.length) return <Alert variant="light" className="mb-0">
    {t("The lab has not published any tests for your projects.")}
  </Alert>;

  return <FeedbackForm feedback={feedback} onSubmit={submit}>
    <FormField name="project" label="Project">
      <Form.Select required value={project} onChange={(event) => {
        setProject(event.target.value); setTestId(""); setValues({}); feedback.clear();
      }}>
        <option value="">{t("Choose project")}</option>
        {projects.map(row => <option value={row.id} key={row.id}>{row.name} · {row.code}</option>)}
      </Form.Select>
    </FormField>
    <FormField name="request_type" label="Test" hint={test?.description}>
      <Form.Select required disabled={!project || !availableTests.length} value={testId} onChange={(event) => {
        setTestId(event.target.value); setValues({}); feedback.clear();
      }}>
        <option value="">{t(project && !availableTests.length ? "No tests for this project" : "Choose test")}</option>
        {availableTests.map(row => <option value={row.id} key={row.id}>{row.name} · {row.code}</option>)}
      </Form.Select>
    </FormField>
    <FormField name="title" label="Request title">
      <Form.Control required maxLength={255} value={title} onChange={event => setTitle(event.target.value)} />
    </FormField>
    <FormField name="sample_references" label="Sample references" hint="Enter one reference per line. Each sample gets its own label.">
      <Form.Control as="textarea" rows={3} required maxLength={3250} value={references} onChange={event => setReferences(event.target.value)} />
    </FormField>
    {fields.map(field => <TestField key={field.key} field={field} value={values[field.key] ?? ""}
      onChange={event => setValues(current => ({ ...current, [field.key]: event.target.value }))} />)}
    <Button type="submit" disabled={!test}>{t("Submit test request")}</Button>
  </FeedbackForm>;
}
