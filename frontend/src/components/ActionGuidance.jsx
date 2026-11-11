import { Children, useContext, useId } from "react";
import { Alert, Button } from "react-bootstrap";
import { Link } from "react-router-dom";
import { useLanguage } from "../i18n";
import { FormFeedbackContext } from "./FormFeedbackContext";

function RecoveryStep({ access }) {
  const { t } = useLanguage();
  return <>{access.next_step && <div>{t(access.next_step)}</div>}{typeof access.href === "string" && ["/access-requests", "/me", "/projects"].includes(access.href) && <Link to={access.href}>{t(access.href === "/access-requests" ? "Request access" : access.href === "/projects" ? "Open projects" : "Review my access")}</Link>}</>;
}

export function AccessNotice({ access, fallback = "Editing requires additional access. Ask the record owner or an administrator." }) {
  const { t } = useLanguage();
  if (access?.allowed) return null;
  return <Alert variant="info"><p className="mb-1">{t(access?.reason || fallback)}</p>{access && <RecoveryStep access={access} />}</Alert>;
}

export function AccessDetails({ access }) {
  const { t } = useLanguage();
  if (!access || access.allowed) return null;
  return <details className="small mt-1"><summary>{t("Read-only")}</summary><div className="mt-1">{t(access.reason)}<RecoveryStep access={access} /></div></details>;
}

export default function ActionButton({ access, reason, nextStep, disabled, children, ...props }) {
  const { t } = useLanguage(), id = useId();
  const form = useContext(FormFeedbackContext);
  const blocked = Boolean(disabled || access?.allowed === false || form?.submitting);
  const message = access?.allowed === false ? access.reason : form?.submitting ? "Wait for the current request to finish." : reason;
  const actionName = Children.toArray(children).filter(value => typeof value === "string" || typeof value === "number").join("").trim() || props["aria-label"] || t("this action");
  return <span className={`d-inline-flex flex-wrap align-items-start gap-1 position-relative ${props.className?.includes("w-100") ? "w-100" : ""}`}>
    <Button {...props} disabled={blocked} aria-describedby={blocked ? `${id}-reason` : undefined}>{children}</Button>
    {blocked && <details className="action-guidance"><summary aria-label={t("Why is {action} unavailable?").replace("{action}", actionName)} title={t(message || "This action is currently unavailable.")}>ⓘ</summary><div id={`${id}-reason`} className="small border rounded bg-body p-2 mt-1" style={{ maxWidth: 360 }}><strong>{t(message || "This action is currently unavailable.")}</strong>{access?.allowed === false ? <RecoveryStep access={access} /> : nextStep && <div>{t(nextStep)}</div>}</div></details>}
  </span>;
}
