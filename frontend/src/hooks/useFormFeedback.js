import { useCallback, useState } from "react";

export default function useFormFeedback() {
  const [issues, setIssues] = useState({ fields: {}, general: [], sequence: 0, status: null });
  const reject = useCallback(error => setIssues(current => ({ fields: error.fieldErrors || {}, general: error.generalErrors?.length ? error.generalErrors : Object.keys(error.fieldErrors || {}).length ? [] : [error.message || "Could not save these values. Try again."], sequence: current.sequence + 1, status: error.status ?? null })), []);
  const validate = useCallback((fields, general = []) => setIssues(current => ({ fields, general, sequence: current.sequence + 1, status: null })), []);
  const clear = useCallback(() => setIssues(current => ({ fields: {}, general: [], sequence: current.sequence, status: null })), []);
  const clearField = useCallback(name => setIssues(current => ({ ...current, fields: Object.fromEntries(Object.entries(current.fields).filter(([key]) => key !== name && !key.startsWith(`${name}.`))) })), []);
  return { issues, reject, validate, clear, clearField };
}
