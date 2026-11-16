import { useContext, useLayoutEffect, useRef } from "react";
import { useLanguage } from "../i18n";
import { FormFeedbackContext } from "./FormFeedbackContext";

export default function MoreOptions({ children }) {
  const { t } = useLanguage();
  const context = useContext(FormFeedbackContext);
  const section = useRef(null);
  const fields = context?.feedback.issues.fields;
  useLayoutEffect(() => {
    if (section.current && Object.keys(fields || {}).some(name =>
      Array.from(section.current.querySelectorAll("[name]")).some(control => control.name === name))) {
      section.current.open = true;
    }
  }, [fields]);
  return <details ref={section} className="border rounded p-3 my-3" onInvalidCapture={() => { section.current.open = true; }}>
    <summary className="fw-semibold">{t("More options")}</summary>
    <div className="mt-3">{children}</div>
  </details>;
}
