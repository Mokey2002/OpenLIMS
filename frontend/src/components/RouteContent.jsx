import { Component, Suspense } from "react";
import { Alert, Button } from "react-bootstrap";
import { Link, Outlet, useLocation } from "react-router-dom";
import { useLanguage } from "../i18n";

class PageErrorBoundary extends Component {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error, info) {
    console.error("OpenLIMS page failed to load", error, info);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    const spanish = this.props.language === "es";
    return <Alert variant="danger" className="my-4">
      <h4>{spanish ? "No se pudo cargar esta página" : "This page could not be loaded"}</h4>
      <p>{spanish ? "Puede haber una actualización o un problema de conexión. Intente cargar la página de nuevo." : "An update or connection problem may have interrupted loading. Try loading the page again."}</p>
      <div className="d-flex gap-2">
        <Button onClick={() => window.location.reload()}>{spanish ? "Volver a cargar" : "Reload page"}</Button>
        <Link className="btn btn-outline-dark" to="/">{spanish ? "Volver a Mi trabajo" : "Return to My Work"}</Link>
      </div>
    </Alert>;
  }
}

export default function RouteContent() {
  const location = useLocation();
  const { language } = useLanguage();
  return <PageErrorBoundary key={location.pathname + location.search} language={language}>
    <Suspense fallback={<div role="status" className="py-5 text-center text-muted">{language === "es" ? "Cargando…" : "Loading…"}</div>}>
      <Outlet />
    </Suspense>
  </PageErrorBoundary>;
}
