import { Link } from "react-router-dom";
import { useLanguage } from "../i18n";

export default function GettingStartedActions() {
  const { t } = useLanguage();
  return <div className="d-flex gap-2 flex-wrap">
    <Link className="btn btn-outline-dark btn-sm" to="/assistant" state={{ prompt: "Register samples" }}>{t("Register samples")}</Link>
    <Link className="btn btn-outline-dark btn-sm" to="/assistant" state={{ prompt: "Import an instrument file" }}>{t("Import an instrument file")}</Link>
  </div>;
}
