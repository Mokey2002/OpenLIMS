import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  Card,
  Form,
  Row,
  Col,
  Table,
  Pagination,
} from "react-bootstrap";
import { apiGet, apiPost, apiPostDownload } from "../api";
import { canWrite } from "../authz";
import SampleFormFields from "../components/SampleFormFields";
import ConfiguredIntake from "../components/ConfiguredIntake";
import { useLanguage } from "../i18n";
import useTablePreferences from "../hooks/useTablePreferences";
import TableViewControls from "../components/TableViewControls";
import useRememberedTableScroll from "../hooks/useRememberedTableScroll";

const SAMPLE_COLUMNS = [
  { key: "id", label: "ID" }, { key: "sample_type", label: "Sample Type" },
  { key: "project", label: "Primary Project" }, { key: "linked", label: "Linked Projects" },
  { key: "status", label: "Status" }, { key: "container", label: "Container" },
  { key: "location", label: "Location" }, { key: "created_by", label: "Created By" },
  { key: "created_at", label: "Created At" },
];
const SAMPLE_SORTS = [
  { value: "-created_at", label: "Newest first" }, { value: "created_at", label: "Oldest first" },
  { value: "sample_id", label: "Sample ID ↑" }, { value: "-sample_id", label: "Sample ID ↓" },
  { value: "status", label: "Status ↑" }, { value: "-status", label: "Status ↓" },
];
const SAMPLE_TABLE_DEFAULTS = { columns: SAMPLE_COLUMNS.map(column => column.key), sorts: SAMPLE_SORTS.map(sort => sort.value), sort: "-created_at", pageSize: 10, filters: { status: "", project: "", container: "" } };

const STATUS_OPTIONS = [
  "",
  "RECEIVED",
  "IN_PROGRESS",
  "QC",
  "REPORTED",
  "CANCELLED",
  "ARCHIVED",
];

function formatTimestamp(value) {
  if (!value) return "-";

  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function linkedProjectBadges(sample) {
  const linkedProjects = sample.linked_project_summaries || [];

  if (linkedProjects.length === 0) {
    return "-";
  }

  return (
    <div className="d-flex gap-1 flex-wrap">
      {linkedProjects.map((project) => (
        <Badge key={project.id} bg="info">
          {project.code || `Project #${project.id}`}
        </Badge>
      ))}
    </div>
  );
}

function statusVariant(status) {
  switch (status) {
    case "RECEIVED":
      return "secondary";
    case "IN_PROGRESS":
      return "primary";
    case "QC":
      return "warning";
    case "REPORTED":
      return "success";
    case "CANCELLED":
      return "danger";
    case "ARCHIVED":
      return "dark";
    default:
      return "light";
  }
}

async function downloadSelectedSamples(ids) {
  await apiPostDownload(
    "/api/samples/export-selected/",
    { ids },
    "openlims-selected-samples.csv"
  );
}

function sampleCell(sample, key) {
  switch (key) {
    case "id": return sample.id;
    case "sample_type": return sample.sample_type || "GENERAL";
    case "project": return sample.project_code ? <Badge bg="dark">{sample.project_code}</Badge> : "—";
    case "linked": return linkedProjectBadges(sample);
    case "status": return <Badge bg={statusVariant(sample.status)}>{sample.status}</Badge>;
    case "container": return sample.container_code || "—";
    case "location": return sample.location_name || "—";
    case "created_by": return sample.created_by_username || "—";
    case "created_at": return formatTimestamp(sample.created_at);
    default: return "—";
  }
}

export default function SamplesList() {
  const [searchParams] = useSearchParams();
  const { language } = useLanguage();
  const [sampleForms, setSampleForms] = useState([]);
  const [formValues, setFormValues] = useState({});
  const [samples, setSamples] = useState([]);
  const [projects, setProjects] = useState([]);
  const [containers, setContainers] = useState([]);
  const [me, setMe] = useState(null);
  const { preferences, update: updateView, reset: resetView, ready: viewReady } = useTablePreferences(me?.id, "samples", SAMPLE_TABLE_DEFAULTS);
  const { query: search, sort: ordering, page, pageSize, filters } = preferences;
  const { status, project: projectFilter, container: containerFilter } = filters;
  const setPage = value => updateView(current => ({ page: typeof value === "function" ? value(current.page) : value }));
  const setSearch = value => updateView({ query: value, page: 1 });
  const setStatus = value => updateView(current => ({ filters: { ...current.filters, status: value }, page: 1 }));
  const setProjectFilter = value => updateView(current => ({ filters: { ...current.filters, project: value }, page: 1 }));
  const setContainerFilter = value => updateView(current => ({ filters: { ...current.filters, container: value }, page: 1 }));
  const appliedProject = useRef(null);
  const urlProject = searchParams.get("project");

  const [err, setErr] = useState("");
  const [supportError, setSupportError] = useState(false);
  const [success, setSuccess] = useState("");
  const [bulkResult, setBulkResult] = useState(null);

  const [sampleId, setSampleId] = useState("");
  const [sampleType, setSampleType] = useState("GENERAL");
  const [projectId, setProjectId] = useState(() => searchParams.get("project") || "");

  const [debouncedSearch, setDebouncedSearch] = useState("");
  const sampleRequest = useRef(null);

  const [selectedIds, setSelectedIds] = useState([]);
  const [bulkStatus, setBulkStatus] = useState("");
  const [bulkProject, setBulkProject] = useState("");
  const [bulkContainer, setBulkContainer] = useState("");
  const [bulkReason, setBulkReason] = useState("");

  const [exporting, setExporting] = useState(false);

  const [totalCount, setTotalCount] = useState(0);
  const [nextPageUrl, setNextPageUrl] = useState(null);
  const [previousPageUrl, setPreviousPageUrl] = useState(null);
  const [rowsReady, setRowsReady] = useState(false);
  useRememberedTableScroll(me?.id, "samples", rowsReady && viewReady);

  useEffect(() => {
    const controller = new AbortController();
    const options = { signal: controller.signal };
    apiGet("/api/me/", options).then(user => { if (!controller.signal.aborted) setMe(user); })
      .catch(e => { if (!controller.signal.aborted) setErr(e.message || String(e)); });
    Promise.allSettled([
      apiGet("/api/projects/", options), apiGet("/api/containers/", options),
      apiGet("/api/sample-forms/?active=1", options),
    ]).then(results => {
      if (controller.signal.aborted) return;
      const [projectsData, containersData, formsData] = results.map(result => result.status === "fulfilled" ? result.value : []);
      setProjects(projectsData.results || projectsData || []);
      setContainers(containersData.results || containersData || []);
      setSampleForms((formsData.results || formsData || []).filter(f => f.published && !f.archived));
      setSupportError(results.some(result => result.status === "rejected"));
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (viewReady && urlProject && appliedProject.current !== urlProject) {
      appliedProject.current = urlProject;
      updateView(current => current.filters.project === urlProject ? {} : { filters: { ...current.filters, project: urlProject }, page: 1 });
    }
  }, [viewReady, urlProject, updateView]);

  useEffect(() => {
    if (search.trim() === debouncedSearch) return;
    const timeout = setTimeout(() => setDebouncedSearch(search.trim()), 250);
    return () => clearTimeout(timeout);
  }, [search, debouncedSearch]);

  const load = useCallback(async () => {
    if (!viewReady || search.trim() !== debouncedSearch) return;
    sampleRequest.current?.abort();
    const controller = new AbortController();
    sampleRequest.current = controller;
    setErr("");
    try {
      const params = new URLSearchParams({ page: String(page), page_size: String(pageSize), ordering });
      if (debouncedSearch) params.set("search", debouncedSearch);
      if (status) params.set("status", status);
      if (projectFilter) params.set("project", projectFilter);
      if (containerFilter) params.set("container", containerFilter);
      const data = await apiGet(`/api/samples/?${params}`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setSamples(data.results || []);
      setTotalCount(data.count || 0);
      setNextPageUrl(data.next || null);
      setPreviousPageUrl(data.previous || null);
      setRowsReady(true);
    } catch (e) {
      if (!controller.signal.aborted && page > 1 && String(e.message).endsWith("404")) {
        updateView({ page: 1 });
        return;
      }
      if (!controller.signal.aborted) setErr(e.message || String(e));
    }
  }, [debouncedSearch, search, status, projectFilter, containerFilter, page, pageSize, ordering, viewReady, updateView]);

  useEffect(() => {
    // The effect starts an external request; state updates reflect its result.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    return () => sampleRequest.current?.abort();
  }, [load]);

  const selectedVisibleCount = useMemo(() => {
    return samples.filter((sample) => selectedIds.includes(sample.id)).length;
  }, [samples, selectedIds]);

  const allVisibleSelected = useMemo(() => {
    return samples.length > 0 && selectedVisibleCount === samples.length;
  }, [samples, selectedVisibleCount]);

  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));

  const userCanWrite = canWrite(me);

  const visibilityMessage = language === "es"
    ? "Se muestran las muestras de tus proyectos principales o vinculados, y las muestras sin ningún proyecto."
    : "Showing samples in your primary or linked projects, plus samples with no projects.";

  const emptyMessage = language === "es" ? "Ninguna muestra accesible coincide con estos filtros." : "No accessible samples match these filters.";

  function toggleSelected(id) {
    setSelectedIds((prev) =>
      prev.includes(id)
        ? prev.filter((currentId) => currentId !== id)
        : [...prev, id]
    );
  }

  function toggleSelectAllVisible() {
    if (allVisibleSelected) {
      const visibleIds = new Set(samples.map((sample) => sample.id));
      setSelectedIds((prev) => prev.filter((id) => !visibleIds.has(id)));
    } else {
      setSelectedIds((prev) =>
        Array.from(new Set([...prev, ...samples.map((sample) => sample.id)]))
      );
    }
  }

  function clearSelection() {
    setSelectedIds([]);
  }

  async function createSample(e) {
    e.preventDefault();

    setErr("");
    setSuccess("");

    const id = sampleId.trim();

    if (!id) return;

    try {
      await apiPost("/api/samples/", {
        sample_id: id,
        sample_type: sampleType.trim() || "GENERAL",
        form_values: formValues,
        status: "RECEIVED",
        project: projectId ? Number(projectId) : null,
      });

      setSampleId("");
      setSampleType("GENERAL");
      setFormValues({});
      setProjectId("");
      setSuccess("Sample created.");
      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function applyBulkUpdate() {
    setErr("");
    setSuccess("");
    setBulkResult(null);

    if (selectedIds.length === 0) {
      setErr("Select at least one sample.");
      return;
    }

    if (!bulkStatus && !bulkProject && !bulkContainer) {
      setErr("Choose at least one bulk action.");
      return;
    }

    if (bulkStatus && bulkReason.trim().length < 10) {
      setErr("Reason for change is required for bulk status updates and must be at least 10 characters.");
      return;
    }

    try {
      const payload = { ids: selectedIds };

      if (bulkStatus) {
        payload.status = bulkStatus;
        payload.reason = bulkReason.trim();
      }
      if (bulkProject) payload.project = Number(bulkProject);
      if (bulkContainer) payload.container = Number(bulkContainer);

      const result = await apiPost("/api/samples/bulk-update/", payload);

      setBulkResult(result);
      setSuccess(`Updated ${result.updated} sample(s).`);

      setSelectedIds([]);
      setBulkStatus("");
      setBulkProject("");
      setBulkContainer("");
      setBulkReason("");
      setBulkReason("");

      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function archiveSelected() {
    setBulkStatus("ARCHIVED");

    setErr("");
    setSuccess("");
    setBulkResult(null);

    if (selectedIds.length === 0) {
      setErr("Select at least one sample.");
      return;
    }

    if (bulkReason.trim().length < 10) {
      setErr("Reason for change is required to archive selected samples.");
      return;
    }

    try {
      const result = await apiPost("/api/samples/bulk-update/", {
        ids: selectedIds,
        status: "ARCHIVED",
        reason: bulkReason.trim(),
      });

      setBulkResult(result);
      setSuccess(`Archived ${result.updated} sample(s).`);

      setSelectedIds([]);
      setBulkStatus("");
      setBulkProject("");
      setBulkContainer("");

      await load();
    } catch (e) {
      setErr(e.message || String(e));
    }
  }

  async function exportSelected() {
    setErr("");
    setSuccess("");
    setExporting(true);

    if (selectedIds.length === 0) {
      setErr("Select at least one sample to export.");
      setExporting(false);
      return;
    }

    try {
      await downloadSelectedSamples(selectedIds);
      setSuccess(`Exported ${selectedIds.length} selected sample(s).`);
    } catch (e) {
      setErr(e.message || String(e));
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Samples</h1>
          <p className="page-subtitle">
            Track sample lifecycle, assignments, storage, and bulk operations.
          </p>
        </div>

        <div className="inline-actions">
          <Badge bg="dark">{selectedIds.length} selected</Badge>
          <Button variant="outline-dark" size="sm" onClick={load}>
            Refresh
          </Button>
        </div>
      </div>

      {err && <Alert variant="danger">{err}</Alert>}
      {supportError && <Alert variant="warning">{language === "es" ? "No se pudieron cargar algunos filtros u opciones de registro. Actualiza esta página para reintentar." : "Some filters or registration options could not load. Refresh this page to retry."}</Alert>}
      {success && <Alert variant="success">{success}</Alert>}

      <Alert variant="info" className="mb-4">
        {visibilityMessage}
      </Alert>

      {userCanWrite && (
      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Create Sample</h5>
          {canWrite(me) && <ConfiguredIntake projects={projects} onImported={load} />}

          <Form onSubmit={createSample}>
            <SampleFormFields fields={sampleForms.find(f => f.code === sampleType.trim().toUpperCase())?.fields || []} values={formValues} onChange={setFormValues} />
            <Row className="g-2">
              <Col md={4}>
                <Form.Control
                  value={sampleId}
                  onChange={(e) => setSampleId(e.target.value)}
                  placeholder="New sample id, e.g. S-002"
                />
              </Col>

              <Col md={3}>
                <Form.Control
                  value={sampleType}
                  list="configured-sample-types"
                  onChange={(e) => { setSampleType(e.target.value); setFormValues({}); }}
                  placeholder="Sample type, e.g. DNA"
                />
                <datalist id="configured-sample-types">{[...new Set(sampleForms.map(f => f.code))].map(code => <option key={code} value={code}>{sampleForms.find(f => f.code === code)?.[language === "es" ? "name_es" : "name_en"]}</option>)}</datalist>
              </Col>

              <Col md={3}>
                <Form.Select
                  value={projectId}
                  onChange={(e) => setProjectId(e.target.value)}
                >
                  <option value="">No project</option>

                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.code} - {project.name}
                    </option>
                  ))}
                </Form.Select>
              </Col>

              <Col md={2}>
                <Button type="submit" variant="dark" className="w-100">
                  Create
                </Button>
              </Col>
            </Row>
          </Form>
        </Card.Body>
      </Card>
      )}

      <Card className="app-card mb-4">
        <Card.Body>
          <h5 className="section-title">Filters</h5>

          <Row className="g-3">
            <Col md={4}>
              <Form.Control
                placeholder="Search by sample ID"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </Col>

            <Col md={2}>
              <Form.Select
                value={status}
                onChange={(e) => { setStatus(e.target.value); setPage(1); }}
              >
                <option value="">All statuses</option>

                {STATUS_OPTIONS.filter(Boolean).map((statusValue) => (
                  <option key={statusValue} value={statusValue}>
                    {statusValue}
                  </option>
                ))}
              </Form.Select>
            </Col>

            <Col md={3}>
              <Form.Select
                value={projectFilter}
                onChange={(e) => { setProjectFilter(e.target.value); setPage(1); }}
              >
                <option value="">All projects</option>

                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.code} - {project.name}
                  </option>
                ))}
              </Form.Select>
            </Col>

            <Col md={3}>
              <Form.Select
                value={containerFilter}
                onChange={(e) => { setContainerFilter(e.target.value); setPage(1); }}
              >
                <option value="">All containers</option>

                {containers.map((container) => (
                  <option key={container.id} value={container.id}>
                    {container.container_id} - {container.kind}
                  </option>
                ))}
              </Form.Select>
            </Col>
          </Row>
        </Card.Body>
      </Card>

      {userCanWrite && (
      <Card className="app-card mb-4">
        <Card.Body>
          <div className="toolbar-row mb-3">
            <div>
              <h5 className="section-title mb-0">Bulk Actions</h5>
              <div className="feed-meta">
                Select samples below, then apply batch updates.
              </div>
            </div>

            <Badge bg="dark">{selectedIds.length} selected</Badge>
          </div>

          <Row className="g-2">
            <Col md={3}>
              <Form.Select
                value={bulkStatus}
                onChange={(e) => setBulkStatus(e.target.value)}
              >
                <option value="">Set status...</option>

                {STATUS_OPTIONS.filter(Boolean).map((statusValue) => (
                  <option key={statusValue} value={statusValue}>
                    {statusValue}
                  </option>
                ))}
              </Form.Select>
            </Col>

            <Col md={3}>
              <Form.Select
                value={bulkProject}
                onChange={(e) => setBulkProject(e.target.value)}
              >
                <option value="">Assign project...</option>

                {projects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.code} - {project.name}
                  </option>
                ))}
              </Form.Select>
            </Col>

            <Col md={3}>
              <Form.Select
                value={bulkContainer}
                onChange={(e) => setBulkContainer(e.target.value)}
              >
                <option value="">Assign container...</option>

                {containers.map((container) => (
                  <option key={container.id} value={container.id}>
                    {container.container_id} - {container.kind}
                  </option>
                ))}
              </Form.Select>
            </Col>

            <Col md={3}>
              <Button
                variant="dark"
                className="w-100"
                onClick={applyBulkUpdate}
                disabled={
                  selectedIds.length === 0 ||
                  (bulkStatus && bulkReason.trim().length < 10)
                }
              >
                Apply to {selectedIds.length}
              </Button>
            </Col>
          </Row>

          {bulkStatus && (
            <div className="mt-3">
              <Form.Label>Reason for status change</Form.Label>
              <Form.Control
                as="textarea"
                rows={2}
                value={bulkReason}
                onChange={(e) => setBulkReason(e.target.value)}
                placeholder="Example: Samples completed review and are ready for the next workflow step."
              />
              <div className="feed-meta mt-1">
                Required when changing sample status. This reason is saved in the audit trail.
              </div>
            </div>
          )}

          <div className="inline-actions mt-3">
            <Button
              variant="outline-secondary"
              size="sm"
              onClick={toggleSelectAllVisible}
              disabled={samples.length === 0}
            >
              {allVisibleSelected ? "Unselect Visible" : "Select Visible"}
            </Button>

            <Button
              variant="outline-secondary"
              size="sm"
              onClick={clearSelection}
              disabled={selectedIds.length === 0}
            >
              Clear Selection
            </Button>

            <Button
              variant="outline-warning"
              size="sm"
              onClick={archiveSelected}
              disabled={selectedIds.length === 0 || bulkReason.trim().length < 10}
            >
              Archive Selected
            </Button>

            <Button
              variant="outline-primary"
              size="sm"
              onClick={exportSelected}
              disabled={selectedIds.length === 0 || exporting}
            >
              {exporting ? "Exporting..." : "Export Selected CSV"}
            </Button>
          </div>

          {bulkResult && (
            <div className="mt-3">
              <Alert variant="success" className="mb-2">
                Updated {bulkResult.updated} sample(s).
              </Alert>

              {bulkResult.skipped?.length > 0 && (
                <Alert variant="warning" className="mb-0">
                  <div className="fw-semibold mb-2">
                    Skipped {bulkResult.skipped.length} sample(s):
                  </div>

                  <ul className="mb-0">
                    {bulkResult.skipped.map((sample) => (
                      <li key={sample.id}>
                        {sample.sample_id}: {sample.reason}
                      </li>
                    ))}
                  </ul>
                </Alert>
              )}
            </div>
          )}
        </Card.Body>
      </Card>
      )}

      <Card className="app-card">
        <Card.Body>
          <TableViewControls title="Samples" columns={SAMPLE_COLUMNS} preferences={preferences} update={updateView} reset={resetView} sorts={SAMPLE_SORTS} search={false} />
          <div className="toolbar-row mb-3">
            <div className="feed-meta">
              Showing {samples.length} of {totalCount} samples
            </div>

            <Pagination className="mb-0">
              <Pagination.Prev
                aria-label="Previous sample page"
                disabled={!previousPageUrl || page === 1}
                onClick={() => setPage((currentPage) => Math.max(1, currentPage - 1))}
              />

              <Pagination.Item active>{page}</Pagination.Item>

              <Pagination.Next
                aria-label="Next sample page"
                disabled={!nextPageUrl || page >= totalPages}
                onClick={() => setPage((currentPage) => currentPage + 1)}
              />
            </Pagination>
          </div>

          {samples.length === 0 ? (
            <div className="empty-state"><h5>{language === "es" ? "No hay muestras que mostrar" : "No samples to show"}</h5><p>{emptyMessage}</p><p>{language === "es" ? "Revisa los filtros. Si tienes permiso, registra una muestra con el formulario de arriba; de lo contrario, solicita acceso al administrador de tu proyecto." : "Check your filters. If you have access, register a sample using the form above; otherwise, ask your project administrator for access."}</p><Link className="btn btn-outline-dark" to="/projects">{language === "es" ? "Ver mis proyectos" : "View my projects"}</Link></div>
          ) : (
            <Table responsive hover className="app-table align-middle">
              <thead>
                <tr>
                  <th>
                    <Form.Check
                      type="checkbox"
                      aria-label="Select visible samples"
                      checked={allVisibleSelected}
                      onChange={toggleSelectAllVisible}
                    />
                  </th>
                  <th scope="col">Sample ID</th>
                  {SAMPLE_COLUMNS.filter(column => preferences.columns.includes(column.key)).map(column => <th key={column.key} scope="col">{column.label}</th>)}
                </tr>
              </thead>

              <tbody>
                {samples.map((sample) => (
                  <tr key={sample.id}>
                    <td>
                      <Form.Check
                        type="checkbox"
                        aria-label={`Select ${sample.sample_id}`}
                        checked={selectedIds.includes(sample.id)}
                        onChange={() => toggleSelected(sample.id)}
                      />
                    </td>

                    <td>
                      <Link to={`/samples/${sample.id}`}>
                        {sample.sample_id}
                      </Link>
                    </td>

                    {SAMPLE_COLUMNS.filter(column => preferences.columns.includes(column.key)).map(column => <td key={column.key}>{sampleCell(sample, column.key)}</td>)}
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card.Body>
      </Card>
    </div>
  );
}
