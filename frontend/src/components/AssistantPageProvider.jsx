import { useState } from "react";
import { useLocation } from "react-router-dom";
import { AssistantPageContext } from "../assistantPageContext";

export default function AssistantPageProvider({ children }) {
  const { pathname } = useLocation();
  const [registration, setPage] = useState(null);
  const [dismissed, setDismissed] = useState(null);
  const available = registration?.path === pathname ? registration : null;
  const identity = available ? `${available.path}:${available.record_id}` : null;
  const enabled = Boolean(available && dismissed !== identity);
  return <AssistantPageContext.Provider value={{ available, page: enabled ? available : null, setPage,
    setEnabled: value => setDismissed(value ? null : identity) }}>
    {children}
  </AssistantPageContext.Provider>;
}
