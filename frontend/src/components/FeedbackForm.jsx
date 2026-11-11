import { cloneElement, useContext, useId, useLayoutEffect, useRef, useState } from "react";
import { Alert, Form } from "react-bootstrap";
import { useLanguage } from "../i18n";
import { controlValidationMessage, fieldLabel } from "../utils/formErrors";
import { FormFeedbackContext } from "./FormFeedbackContext";
import { Link } from "react-router-dom";

export function FormField({ name, label, hint, children, className = "mb-3" }) {
  const context = useContext(FormFeedbackContext), id = useId();
  const { t } = useLanguage();
  const errors = context?.feedback.issues.fields[name] || [];
  const child = cloneElement(children, {
    id: children.props.id || id, name,
    isInvalid: errors.length > 0 || children.props.isInvalid,
    "aria-invalid": errors.length ? true : undefined,
    "aria-describedby": [children.props["aria-describedby"], hint ? `${id}-hint` : "", errors.length ? `${id}-errors` : ""].filter(Boolean).join(" ") || undefined,
    onChange: event => { context?.feedback.clearField(name); children.props.onChange?.(event); },
  });
  return <Form.Group className={className} controlId={children.props.id || id}>
    {label && <Form.Label>{t(label)}</Form.Label>}{child}
    {hint && <Form.Text id={`${id}-hint`}>{t(hint)}</Form.Text>}
    {errors.length > 0 && <Form.Control.Feedback id={`${id}-errors`} type="invalid" className="d-block">{errors.map(message => t(message)).join(" ")}</Form.Control.Feedback>}
  </Form.Group>;
}

export default function FeedbackForm({ feedback, onSubmit, children, ...props }) {
  const { t } = useLanguage();
  const form = useRef(null), summary = useRef(null), busy = useRef(false);
  const lastFocused = useRef(0);
  const [submitting, setSubmitting] = useState(false);
  const [nativeAttempted, setNativeAttempted] = useState(false);
  const { fields, general, sequence } = feedback.issues;
  const hasIssues = Object.keys(fields).length > 0 || general.length > 0;
  useLayoutEffect(() => {
    if (submitting || !sequence || sequence === lastFocused.current || !form.current) return;
    lastFocused.current = sequence;
    const activeForm = document.activeElement?.closest?.("form");
    if (activeForm && activeForm !== form.current) return;
    const controls = Array.from(form.current.elements);
    const target = controls.find(element => fields[element.name]?.length && !element.disabled && typeof element.focus === "function")
      || controls.find(element => !element.disabled && controlValidationMessage(element));
    (target || summary.current)?.focus();
  }, [sequence, fields, submitting]);

  async function submit(event) {
    event.preventDefault();
    if (busy.current) return;
    const errors = Object.create(null), general = [];
    for (const control of event.currentTarget.elements) {
      const message = controlValidationMessage(control, t);
      if (message && control.name) errors[control.name] = [message];
      else if (message) general.push(`${control.getAttribute("aria-label") || control.placeholder || t("Field")}: ${message}`);
    }
    if (Object.keys(errors).length || general.length) { setNativeAttempted(true); feedback.validate(errors, general); return; }
    setNativeAttempted(false);
    feedback.clear(); busy.current = true; setSubmitting(true);
    try { await onSubmit(event); }
    catch (error) { feedback.reject(error); }
    finally { busy.current = false; setSubmitting(false); }
  }
  return <FormFeedbackContext.Provider value={{ feedback, submitting }}>
    <Form {...props} ref={form} noValidate validated={nativeAttempted} onSubmit={submit} aria-busy={submitting}>
      {hasIssues && <Alert variant="danger" role="alert" tabIndex={-1} ref={summary}>
        <strong>{t(Object.keys(fields).length ? "Check the highlighted fields and try again." : "This request needs attention.")}</strong>
        <ul className="mb-0">{Object.entries(fields).map(([name, messages]) => <li key={name}><button type="button" className="btn btn-link p-0 text-start align-baseline" onClick={() => {
          const control = Array.from(form.current.elements).find(item => item.name === name && !item.disabled); control?.focus();
        }}>{t(fieldLabel(name))}</button>: {messages.map(message => t(message)).join(" ")}</li>)}{general.map((message, index) => <li key={`general-${index}`}>{t(message)}</li>)}</ul>
        {feedback.issues.status === 403 && <Link to="/me">{t("Review my access")}</Link>}
      </Alert>}
      <fieldset disabled={submitting}>{children}</fieldset>
    </Form>
  </FormFeedbackContext.Provider>;
}
