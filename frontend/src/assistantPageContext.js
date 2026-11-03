import { createContext, useContext, useEffect } from "react";
import { useLocation } from "react-router-dom";

export const AssistantPageContext = createContext(null);
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function pageSelection(value) {
  if (!value || !["sample", "project"].includes(value.kind) || typeof value.record_id !== "string"
      || (!UUID.test(value.record_id) && !/^[1-9]\d{0,17}$/.test(value.record_id))
      || typeof value.label !== "string" || !value.label || value.label.length > 128) return null;
  return { kind: value.kind, record_id: value.record_id, label: value.label };
}

export function describePageRecord(pathname, kind, record) {
  const match = /^\/(samples|projects)\/([^/]+)\/?$/.exec(pathname);
  if (!match || !record || (match[1] === "samples" ? "sample" : "project") !== kind) return null;
  const routeId = match[2].toLowerCase();
  const ids = [record.id, record.public_id].filter(value => value != null).map(String);
  if (!ids.some(value => value.toLowerCase() === routeId)) return null;
  const recordId = UUID.test(String(record.public_id)) ? String(record.public_id) : String(record.id);
  if (!UUID.test(recordId) && !/^[1-9]\d{0,17}$/.test(recordId)) return null;
  const label = kind === "sample" ? record.sample_id : record.code;
  if (typeof label !== "string" || !label) return null;
  return { path: pathname, kind, record_id: recordId, label };
}

export function useAssistantPageRecord(kind, record) {
  const shared = useContext(AssistantPageContext);
  const setPage = shared?.setPage;
  const { pathname } = useLocation();
  const page = describePageRecord(pathname, kind, record);
  const recordId = page?.record_id, label = page?.label;
  useEffect(() => {
    if (!setPage || !recordId) return;
    const registration = { path: pathname, kind, record_id: recordId, label };
    setPage(registration);
    return () => setPage(current => current === registration ? null : current);
  }, [setPage, pathname, kind, recordId, label]);
}

export function useAssistantPage() {
  return useContext(AssistantPageContext);
}
