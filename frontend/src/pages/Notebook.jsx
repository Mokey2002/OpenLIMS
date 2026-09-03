import { useEffect, useMemo, useRef, useState } from "react";
import {
  Alert, Badge, Button, Card, Col, Form, Modal, Nav, Row, Spinner, Tab, Table,
} from "react-bootstrap";
import { apiDownload, apiGet, apiGetAll, apiPatch, apiPost, apiPostForm } from "../api";
import BlockEditor from "../components/notebook/BlockEditor";
import { BLOCK_CATALOG, newBlock } from "../components/notebook/blockTypes";
import { useLanguage } from "../i18n";
import "./Notebook.css";

const EDITABLE_STATES = new Set(["DRAFT", "IN_PROGRESS"]);
const STATUS_OPTIONS = ["DRAFT", "IN_PROGRESS", "COMPLETED", "REVIEWED", "LOCKED"];
const DEFAULT_BLOCKS = [
  { block_type: "HEADING", data: { text: "Experiment objective", level: 2 } },
  { block_type: "RICH_TEXT", data: { text: "Describe the objective and context." } },
  { block_type: "PROTOCOL_STEP", data: { text: "Record the first protocol step", completed: false, notes: "" } },
  { block_type: "STRUCTURED_RESULT", data: { name: "Result", value: "", unit: "", status: "RECORDED", notes: "" } },
];

const LINK_TYPES = [
  ["registry_record", "Registry record"], ["sample", "Sample"],
  ["inventory_lot", "Inventory lot"], ["pipeline_run", "Pipeline run"],
  ["work_item", "Work item"], ["result", "Result"],
  ["sop_document", "SOP version"], ["sequence", "Sequence revision"],
];

const LINK_TARGET_PATHS = {
  registry_record: "/api/registry-records/",
  sample: "/api/samples/",
  inventory_lot: "/api/inventory-lots/",
  pipeline_run: "/api/pipeline-runs/",
  work_item: "/api/work-items/",
  result: "/api/results/",
  sop_document: "/api/sop-documents/",
  sequence: "/api/sequences/",
};

const RELATION_TYPES = [
  ["used", "Used"], ["input", "Input"], ["output", "Output"],
  ["protocol", "Protocol"], ["reagent_lot", "Reagent lot"],
  ["physical_sample", "Physical sample"], ["workflow_run", "Workflow run"],
  ["reference", "Reference"],
];

function withKeys(blocks = []) {
  return blocks.map((block) => ({
    _key: `${block.public_id || "block"}-${crypto.randomUUID()}`,
    block_type: block.block_type,
    data: structuredClone(block.data || {}),
  }));
}

function serializableBlocks(blocks) {
  return blocks.map(({ block_type, data }) => ({ block_type, data }));
}

function revisionLinks(revision) {
  return (revision?.links || []).map((link) => ({
    entity_type: link.entity_type,
    public_id: link.entity_public_id,
    relation_type: link.relation_type,
    label: link.label,
    version: link.version,
  }));
}

function statusColor(status) {
  return { DRAFT: "secondary", IN_PROGRESS: "primary", COMPLETED: "warning", REVIEWED: "success", LOCKED: "dark" }[status] || "secondary";
}

function statusLabel(status) {
  return String(status || "").replaceAll("_", " ").toLowerCase().replace(/^./, (letter) => letter.toUpperCase());
}

function targetLabel(target) {
  return target.registry_id || target.sample_id || target.lot_code || target.document_code || target.title || target.name || target.template_code || target.key || target.public_id;
}

function notebookValues(notebook) {
  return {
    name: notebook?.name || "", description: notebook?.description || "",
    scope: notebook?.scope || "USER", project: notebook?.project ? String(notebook.project) : "",
    team_members: notebook?.team_members || [], readers: notebook?.readers || [],
    editors: notebook?.editors || [], commenters: notebook?.commenters || [],
    reviewers: notebook?.reviewers || [], lockers: notebook?.lockers || [],
  };
}

function MultiUserSelect({ label, value, users, disabled, onChange, help }) {
  return <Form.Group>
    <Form.Label>{label}</Form.Label>
    <Form.Select multiple value={(value || []).map(String)} disabled={disabled} onChange={(event) => onChange(Array.from(event.target.selectedOptions, (option) => Number(option.value)))}>
      {users.map((user) => <option key={user.id} value={user.id}>{user.full_name || user.username} ({user.username})</option>)}
    </Form.Select>
    {help && <Form.Text>{help}</Form.Text>}
  </Form.Group>;
}

function StatCard({ label, value, detail, variant = "dark" }) {
  return <Card className="notebook-stat h-100"><Card.Body><Badge bg={variant}>{value}</Badge><div className="fw-semibold mt-2">{label}</div><div className="feed-meta">{detail}</div></Card.Body></Card>;
}

export default function NotebookPage() {
  const { locale } = useLanguage();
  const [me, setMe] = useState(null);
  const [notebooks, setNotebooks] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [experiments, setExperiments] = useState([]);
  const [projects, setProjects] = useState([]);
  const [users, setUsers] = useState([]);
  const [linkTargets, setLinkTargets] = useState({});
  const [linkTargetLoading, setLinkTargetLoading] = useState({});
  const [attachments, setAttachments] = useState([]);
  const [attachmentForm, setAttachmentForm] = useState({ file: null, description: "" });
  const [selectedNotebookId, setSelectedNotebookId] = useState(null);
  const [selected, setSelected] = useState(null);
  const [blocks, setBlocks] = useState([]);
  const [links, setLinks] = useState([]);
  const [experimentMeta, setExperimentMeta] = useState({ title: "", assignees: [] });
  const [notebookEditForm, setNotebookEditForm] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [saveState, setSaveState] = useState("");
  const [topTab, setTopTab] = useState("workspace");
  const [detailTab, setDetailTab] = useState("entry");
  const [notebookSearch, setNotebookSearch] = useState("");
  const [experimentSearch, setExperimentSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [myWorkOnly, setMyWorkOnly] = useState(false);
  const [showNotebookModal, setShowNotebookModal] = useState(false);
  const [showExperimentModal, setShowExperimentModal] = useState(false);
  const [workflowAction, setWorkflowAction] = useState(null);
  const [notebookForm, setNotebookForm] = useState({ name: "", description: "", scope: "PROJECT", project: "" });
  const [templateForm, setTemplateForm] = useState({ notebook: "", name: "", description: "", source: "default" });
  const [experimentForm, setExperimentForm] = useState({ source: "blank", template: "", title: "", assignees: [] });
  const [linkForm, setLinkForm] = useState({ entity_type: "registry_record", public_id: "", relation_type: "used" });
  const [commentForm, setCommentForm] = useState({ body: "", mentions: [], assigned_to: "" });
  const [compareForm, setCompareForm] = useState({ from: "", to: "" });
  const [comparison, setComparison] = useState(null);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const autosaveTimer = useRef(null);
  const selectionToken = useRef(0);
  const revisionRef = useRef("");
  const dirtyRef = useRef(false);
  const editVersionRef = useRef(0);
  const linkTargetRequests = useRef(new Set());

  function formatDate(value) {
    return value ? new Date(value).toLocaleString(locale) : "—";
  }

  function adoptExperiment(experiment) {
    selectionToken.current += 1;
    clearTimeout(autosaveTimer.current);
    dirtyRef.current = false;
    editVersionRef.current += 1;
    setSelected(experiment);
    setBlocks(withKeys(experiment?.current_revision_detail?.blocks || []));
    setLinks(revisionLinks(experiment?.current_revision_detail));
    setExperimentMeta({ title: experiment?.title || "", assignees: experiment?.assignees || [] });
    revisionRef.current = experiment?.current_revision_detail?.public_id || "";
    setSaveState("");
    setComparison(null);
    const revisions = experiment?.revisions || [];
    setCompareForm({ from: revisions[1]?.public_id || revisions[0]?.public_id || "", to: revisions[0]?.public_id || "" });
  }

  async function loadAttachments(experiment) {
    const token = selectionToken.current;
    setAttachments([]);
    if (!experiment) {
      return;
    }
    try {
      const rows = await apiGetAll(`/api/shared-attachments/?target_type=experiment&target_public_id=${experiment.public_id}`);
      if (token === selectionToken.current) setAttachments(rows);
    } catch {
      if (token === selectionToken.current) setAttachments([]);
    }
  }

  async function loadLinkTargets(type) {
    const path = LINK_TARGET_PATHS[type];
    if (!path || Object.prototype.hasOwnProperty.call(linkTargets, type) || linkTargetRequests.current.has(type)) return;
    linkTargetRequests.current.add(type);
    setLinkTargetLoading((current) => ({ ...current, [type]: true }));
    try {
      const rows = await apiGetAll(path);
      setLinkTargets((current) => ({ ...current, [type]: rows }));
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    } finally {
      linkTargetRequests.current.delete(type);
      setLinkTargetLoading((current) => ({ ...current, [type]: false }));
    }
  }

  async function loadExperimentDetail(experiment) {
    if (!experiment) return null;
    const detail = await apiGet(`/api/experiments/${experiment.id}/?compact=1`);
    setExperiments((current) => current.map((row) => (
      row.id === detail.id ? { ...row, ...detail } : row
    )));
    return detail;
  }

  async function load(selectId = null, selectNotebookId = null) {
    setError("");
    try {
      const [meData, notebookRows, templateRows, experimentRows, projectRows, userRows] = await Promise.all([
        apiGet("/api/me/"), apiGetAll("/api/notebooks/"), apiGetAll("/api/experiment-templates/"),
        apiGetAll("/api/experiments/?summary=1"), apiGetAll("/api/projects/"), apiGetAll("/api/notebooks/collaborators/"),
      ]);
      const requestedNotebookId = selectNotebookId || selectedNotebookId;
      const targetNotebook = notebookRows.find((row) => String(row.id) === String(requestedNotebookId)) || notebookRows[0] || null;
      const notebookRowsForTarget = targetNotebook ? experimentRows.filter((row) => String(row.notebook) === String(targetNotebook.id)) : [];
      const targetSummary = notebookRowsForTarget.find((row) => String(row.id) === String(selectId || selected?.id)) || notebookRowsForTarget[0] || null;
      const target = targetSummary ? await apiGet(`/api/experiments/${targetSummary.id}/?compact=1`) : null;
      const hydratedExperiments = target ? experimentRows.map((row) => (
        row.id === target.id ? { ...row, ...target } : row
      )) : experimentRows;
      setMe(meData); setNotebooks(notebookRows); setTemplates(templateRows); setExperiments(hydratedExperiments);
      setProjects(projectRows); setUsers(userRows);
      setSelectedNotebookId(targetNotebook?.id || null);
      setNotebookEditForm(targetNotebook ? notebookValues(targetNotebook) : null);
      setTemplateForm((current) => ({ ...current, notebook: targetNotebook?.permissions?.write ? String(targetNotebook.id) : "" }));
      adoptExperiment(target);
      void loadAttachments(target);
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    return () => clearTimeout(autosaveTimer.current);
    // The workspace loads once; subsequent refreshes are explicit or action-driven.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function replaceExperiment(updated) {
    setExperiments((current) => current.map((row) => row.id === updated.id ? updated : row));
    adoptExperiment(updated);
  }

  async function saveContent(nextBlocks = blocks, nextLinks = links, reason = "Notebook autosave", experiment = selected) {
    if (!experiment?.permissions?.write || !EDITABLE_STATES.has(experiment.status)) return true;
    const token = selectionToken.current;
    const savedEditVersion = editVersionRef.current;
    const expectedRevision = revisionRef.current;
    clearTimeout(autosaveTimer.current);
    setSaveState("Saving...");
    try {
      const response = await apiPost(`/api/experiments/${experiment.id}/autosave/`, {
        blocks: serializableBlocks(nextBlocks), links: nextLinks, reason,
        expected_revision_public_id: expectedRevision,
      });
      if (token !== selectionToken.current || selected?.id !== experiment.id) return true;
      revisionRef.current = response.revision.public_id;
      const hasNewerLocalChanges = editVersionRef.current !== savedEditVersion;
      dirtyRef.current = hasNewerLocalChanges;
      setSaveState(hasNewerLocalChanges ? "Unsaved changes" : response.created ? `Saved as r${response.revision.number}` : "All changes saved");
      setLinks((current) => current.map((link) => {
        const saved = response.revision.links.find((row) => row.entity_type === link.entity_type && String(row.entity_public_id) === String(link.public_id) && row.relation_type === link.relation_type);
        return saved ? { ...link, label: saved.label, version: saved.version } : link;
      }));
      if (response.created) setCompareForm({ from: expectedRevision, to: response.revision.public_id });
      setSelected((current) => {
        if (!current || current.id !== experiment.id) return current;
        const prior = current.revisions || [];
        const revisions = response.created ? [response.revision, ...prior] : prior.map((row) => row.id === response.revision.id ? response.revision : row);
        return { ...current, status: current.status === "DRAFT" ? "IN_PROGRESS" : current.status,
          current_revision: response.revision.id, current_revision_detail: response.revision, revisions };
      });
      setExperiments((current) => current.map((row) => row.id === experiment.id ? {
        ...row, status: row.status === "DRAFT" ? "IN_PROGRESS" : row.status,
        current_revision: response.revision.id, current_revision_detail: response.revision,
        revisions: response.created ? [response.revision, ...(row.revisions || [])] : row.revisions,
      } : row));
      return true;
    } catch (requestError) {
      setSaveState("Save failed — refresh required");
      setError(requestError.message || String(requestError));
      return false;
    }
  }

  function scheduleAutosave(nextBlocks, nextLinks) {
    if (!selected?.permissions?.write || !EDITABLE_STATES.has(selected.status)) return;
    dirtyRef.current = true;
    editVersionRef.current += 1;
    clearTimeout(autosaveTimer.current);
    setSaveState("Unsaved changes");
    const experiment = selected;
    autosaveTimer.current = setTimeout(() => saveContent(nextBlocks, nextLinks, "Notebook autosave", experiment), 1400);
  }

  async function selectExperiment(experiment) {
    if (selected?.id === experiment.id) return;
    if (dirtyRef.current && !(await saveContent(blocks, links, "Saved before switching experiments", selected))) return;
    try {
      const detail = await loadExperimentDetail(experiment);
      adoptExperiment(detail);
      void loadAttachments(detail);
      setDetailTab("entry");
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    }
  }

  async function selectNotebook(notebook) {
    if (!notebook) return;
    if (dirtyRef.current && !(await saveContent(blocks, links, "Saved before switching notebooks", selected))) return;
    setSelectedNotebookId(notebook.id);
    setNotebookEditForm(notebookValues(notebook));
    setTemplateForm((current) => ({ ...current, notebook: notebook.permissions.write ? String(notebook.id) : "" }));
    const firstExperiment = experiments.find((row) => String(row.notebook) === String(notebook.id)) || null;
    try {
      const detail = await loadExperimentDetail(firstExperiment);
      adoptExperiment(detail);
      void loadAttachments(detail);
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    }
  }

  function changeDetailTab(key) {
    setDetailTab(key);
    if (key === "provenance") void loadLinkTargets(linkForm.entity_type);
  }

  function changeLinkType(entityType) {
    setLinkForm((current) => ({ ...current, entity_type: entityType, public_id: "" }));
    void loadLinkTargets(entityType);
  }

  function addBlock(type) {
    if (type === "SEQUENCE_VIEW") void loadLinkTargets("sequence");
    updateBlocks([...blocks, newBlock(type)]);
  }

  function updateBlocks(next) { setBlocks(next); scheduleAutosave(next, links); }
  function changeBlock(index, nextBlock) { updateBlocks(blocks.map((block, blockIndex) => blockIndex === index ? nextBlock : block)); }
  function moveBlock(index, direction) {
    const target = index + direction;
    if (target < 0 || target >= blocks.length) return;
    const next = [...blocks]; [next[index], next[target]] = [next[target], next[index]]; updateBlocks(next);
  }
  function duplicateBlock(index) {
    const duplicate = newBlock(blocks[index].block_type);
    duplicate.data = structuredClone(blocks[index].data);
    const next = [...blocks]; next.splice(index + 1, 0, duplicate); updateBlocks(next);
  }

  async function createNotebook(event) {
    event.preventDefault(); setError("");
    if (dirtyRef.current && !(await saveContent(blocks, links, "Saved before creating a notebook", selected))) return;
    try {
      const created = await apiPost("/api/notebooks/", { ...notebookForm, project: notebookForm.scope === "PROJECT" ? Number(notebookForm.project) : null });
      setNotebookForm({ name: "", description: "", scope: "PROJECT", project: "" });
      setShowNotebookModal(false); setMessage(`Notebook ${created.name} created and selected.`);
      await load(null, created.id); setTopTab("workspace");
    } catch (requestError) { setError(requestError.message || String(requestError)); }
  }

  async function updateNotebook(event) {
    event.preventDefault(); if (!selectedNotebookId || !notebookEditForm) return; setError("");
    if (dirtyRef.current && !(await saveContent(blocks, links, "Saved before updating notebook settings", selected))) return;
    try {
      const payload = { ...notebookEditForm, project: notebookEditForm.scope === "PROJECT" ? Number(notebookEditForm.project) : null };
      const updated = await apiPatch(`/api/notebooks/${selectedNotebookId}/`, payload);
      setMessage(`Notebook ${updated.name} updated.`); await load(selected?.id, updated.id);
    } catch (requestError) { setError(requestError.message || String(requestError)); }
  }

  async function createTemplate(event) {
    event.preventDefault(); setError("");
    if (dirtyRef.current && !(await saveContent(blocks, links, "Saved before creating a template", selected))) return;
    try {
      const sourceBlocks = templateForm.source === "current" && selected ? serializableBlocks(blocks) : DEFAULT_BLOCKS;
      const created = await apiPost("/api/experiment-templates/", { notebook: Number(templateForm.notebook), name: templateForm.name, description: templateForm.description, blocks: sourceBlocks });
      setTemplateForm((current) => ({ ...current, name: "", description: "" }));
      setMessage(`Template ${created.name} created.`); await load(selected?.id, selectedNotebookId); setTopTab("templates");
    } catch (requestError) { setError(requestError.message || String(requestError)); }
  }

  async function toggleTemplate(template) {
    try {
      await apiPatch(`/api/experiment-templates/${template.id}/`, { active: !template.active });
      setTemplates((current) => current.map((row) => row.id === template.id ? { ...row, active: !row.active } : row));
    } catch (requestError) { setError(requestError.message || String(requestError)); }
  }

  async function createExperiment(event) {
    event.preventDefault(); if (!selectedNotebookId) return; setError("");
    if (dirtyRef.current && !(await saveContent(blocks, links, "Saved before creating an experiment", selected))) return;
    try {
      let created;
      if (experimentForm.source === "template") {
        const template = templates.find((row) => String(row.id) === String(experimentForm.template));
        if (!template) return;
        created = await apiPost(`/api/experiment-templates/${template.id}/instantiate/`, { title: experimentForm.title || template.name, assignees: experimentForm.assignees });
      } else {
        created = await apiPost("/api/experiments/", { notebook: Number(selectedNotebookId), title: experimentForm.title, assignees: experimentForm.assignees, initial_blocks: DEFAULT_BLOCKS });
      }
      setExperimentForm({ source: "blank", template: "", title: "", assignees: [] });
      setShowExperimentModal(false); setMessage("Experiment created and ready to edit.");
      await load(created.id, selectedNotebookId); setTopTab("workspace");
    } catch (requestError) { setError(requestError.message || String(requestError)); }
  }

  async function saveExperimentMeta(event) {
    event.preventDefault();
    if (dirtyRef.current && !(await saveContent(blocks, links, "Saved before updating experiment details", selected))) return;
    try {
      const updated = await apiPatch(`/api/experiments/${selected.id}/`, experimentMeta);
      replaceExperiment(updated); setMessage("Experiment details updated.");
    } catch (requestError) { setError(requestError.message || String(requestError)); }
  }

  function addLink(event) {
    event.preventDefault();
    const target = (linkTargets[linkForm.entity_type] || []).find((row) => String(row.public_id) === String(linkForm.public_id));
    if (!target) return;
    const duplicate = links.some((link) => link.entity_type === linkForm.entity_type && String(link.public_id) === String(target.public_id) && link.relation_type === linkForm.relation_type);
    if (duplicate) { setError("That exact record and relationship is already linked."); return; }
    const next = [...links, { entity_type: linkForm.entity_type, public_id: target.public_id, relation_type: linkForm.relation_type, label: targetLabel(target) }];
    setLinks(next); setLinkForm((current) => ({ ...current, public_id: "" })); scheduleAutosave(blocks, next);
  }
  function removeLink(index) { const next = links.filter((_, linkIndex) => linkIndex !== index); setLinks(next); scheduleAutosave(blocks, next); }

  async function uploadAttachment(event) {
    event.preventDefault();
    if (!attachmentForm.file || !selected || !editable) return;
    try {
      const payload = new FormData();
      payload.append("target_type", "experiment");
      payload.append("target_public_id", selected.public_id);
      payload.append("display_name", attachmentForm.file.name);
      payload.append("description", attachmentForm.description);
      payload.append("file", attachmentForm.file);
      const uploaded = await apiPostForm("/api/shared-attachments/", payload);
      setAttachments((current) => [...current, uploaded]);
      setAttachmentForm({ file: null, description: "" });
      const attachmentBlock = newBlock("ATTACHMENT");
      attachmentBlock.data = {
        name: uploaded.display_name || uploaded.filename,
        url: uploaded.file,
        description: uploaded.description || "",
        attachment_public_id: uploaded.public_id,
        sha256: uploaded.sha256,
        size_bytes: uploaded.size_bytes,
        media_type: uploaded.media_type,
      };
      updateBlocks([...blocks, attachmentBlock]);
      setMessage(`${uploaded.display_name || uploaded.filename} uploaded and added to the experiment entry.`);
    } catch (requestError) {
      setError(requestError.message || String(requestError));
    }
  }

  async function addComment(event) {
    event.preventDefault(); if (!commentForm.body.trim()) return;
    if (dirtyRef.current && !(await saveContent(blocks, links, "Saved before adding a comment", selected))) return;
    try {
      await apiPost("/api/experiment-comments/", { experiment: selected.id, revision: selected.current_revision, body: commentForm.body,
        mentions: commentForm.mentions, assigned_to: commentForm.assigned_to ? Number(commentForm.assigned_to) : null });
      setCommentForm({ body: "", mentions: [], assigned_to: "" }); await load(selected.id, selectedNotebookId); setDetailTab("discussion");
    } catch (requestError) { setError(requestError.message || String(requestError)); }
  }

  async function resolveComment(comment, resolved) {
    try {
      const updated = await apiPatch(`/api/experiment-comments/${comment.id}/`, { resolved });
      setSelected((current) => ({ ...current, comments: current.comments.map((row) => row.id === updated.id ? updated : row) }));
    } catch (requestError) { setError(requestError.message || String(requestError)); }
  }

  function openWorkflowAction(type, extra = {}) {
    setWorkflowAction({ type, comment: "", reason: "", signed_name: me?.full_name || me?.username || "",
      title: type === "clone" ? `Copy of ${selected?.title || "experiment"}` : "", ...extra });
  }

  async function submitWorkflowAction(event) {
    event.preventDefault(); if (!workflowAction || !selected) return; clearTimeout(autosaveTimer.current);
    if (dirtyRef.current && !(await saveContent(blocks, links, "Saved before workflow action", selected))) return;
    try {
      let response;
      if (workflowAction.type === "complete") response = await apiPost(`/api/experiments/${selected.id}/transition/`, { status: "COMPLETED", reason: workflowAction.reason });
      else if (["approve", "changes"].includes(workflowAction.type)) await apiPost(`/api/experiments/${selected.id}/review/`, { decision: workflowAction.type === "approve" ? "APPROVED" : "CHANGES_REQUESTED", comment: workflowAction.comment, signed_name: workflowAction.signed_name });
      else if (workflowAction.type === "lock") response = await apiPost(`/api/experiments/${selected.id}/lock/`, { reason: workflowAction.reason });
      else if (workflowAction.type === "clone") response = await apiPost(`/api/experiments/${selected.id}/clone/`, { title: workflowAction.title, assignees: selected.assignees });
      else if (workflowAction.type === "restore") await apiPost(`/api/experiments/${selected.id}/restore/`, { revision_public_id: workflowAction.revision.public_id, reason: workflowAction.reason });
      const type = workflowAction.type; setWorkflowAction(null); setMessage(type === "clone" ? "Experiment cloned." : "Experiment workflow updated.");
      await load(response?.id || selected.id, selectedNotebookId);
    } catch (requestError) { setError(requestError.message || String(requestError)); }
  }

  async function compareRevisions(event) {
    event.preventDefault(); if (!compareForm.from || !compareForm.to) return; setComparisonLoading(true);
    try {
      const params = new URLSearchParams({ from: compareForm.from, to: compareForm.to });
      setComparison(await apiGet(`/api/experiments/${selected.id}/compare/?${params}`));
    } catch (requestError) { setError(requestError.message || String(requestError)); }
    finally { setComparisonLoading(false); }
  }

  async function refreshWorkspace() {
    if (dirtyRef.current && !(await saveContent(blocks, links, "Saved before refresh", selected))) return;
    await load(selected?.id, selectedNotebookId);
  }

  const selectedNotebook = useMemo(() => notebooks.find((row) => String(row.id) === String(selectedNotebookId)) || null, [notebooks, selectedNotebookId]);
  const notebookTemplates = useMemo(() => templates.filter((row) => String(row.notebook) === String(selectedNotebookId)), [templates, selectedNotebookId]);
  const notebookExperiments = useMemo(() => experiments.filter((row) => String(row.notebook) === String(selectedNotebookId)), [experiments, selectedNotebookId]);
  const filteredNotebooks = useMemo(() => notebooks.filter((notebook) => `${notebook.name} ${notebook.description} ${notebook.project_code || ""}`.toLowerCase().includes(notebookSearch.toLowerCase())), [notebooks, notebookSearch]);
  const visibleExperiments = useMemo(() => notebookExperiments.filter((experiment) => {
    const matchesText = `${experiment.title} ${experiment.created_by_username} ${(experiment.assignee_usernames || []).join(" ")}`.toLowerCase().includes(experimentSearch.toLowerCase());
    const matchesStatus = !statusFilter || experiment.status === statusFilter;
    const mine = !myWorkOnly || experiment.created_by === me?.id || (experiment.assignees || []).includes(me?.id);
    return matchesText && matchesStatus && mine;
  }), [notebookExperiments, experimentSearch, statusFilter, myWorkOnly, me]);
  const targetOptions = linkTargets[linkForm.entity_type] || [];
  const editable = Boolean(selected?.permissions?.write && EDITABLE_STATES.has(selected.status));
  const openComments = experiments.reduce((count, experiment) => (
    count + (experiment.open_comment_count ?? (experiment.comments || []).filter((comment) => !comment.resolved).length)
  ), 0);
  const assignedExperiments = experiments.filter((experiment) => (experiment.assignees || []).includes(me?.id)).length;
  const reviewQueue = experiments.filter((experiment) => experiment.status === "COMPLETED" && experiment.permissions?.review).length;
  const statusCounts = Object.fromEntries(STATUS_OPTIONS.map((status) => [status, notebookExperiments.filter((experiment) => experiment.status === status).length]));

  if (loading) return <div className="d-flex gap-2 align-items-center"><Spinner size="sm" /><span>Loading Notebook...</span></div>;

  return <div className="w-100 notebook-page">
    <div className="page-header">
      <div><h1 className="page-title">Laboratory Notebook</h1><p className="page-subtitle">Plan, execute, review, and preserve experiments with exact material and revision provenance.</p></div>
      <div className="inline-actions"><Button variant="outline-dark" onClick={refreshWorkspace}>Refresh</Button><Button variant="dark" onClick={() => setShowNotebookModal(true)}>New notebook</Button></div>
    </div>
    {error && <Alert variant="danger" dismissible onClose={() => setError("")}>{error}</Alert>}
    {message && <Alert variant="success" dismissible onClose={() => setMessage("")}>{message}</Alert>}

    <Row className="g-3 mb-4">
      <Col sm={6} xl={3}><StatCard value={notebooks.length} label="Accessible notebooks" detail="Personal, team, and project scopes" /></Col>
      <Col sm={6} xl={3}><StatCard value={assignedExperiments} label="Assigned to me" detail="Experiments requiring your work" variant="primary" /></Col>
      <Col sm={6} xl={3}><StatCard value={reviewQueue} label="Review queue" detail="Completed experiments awaiting review" variant="warning" /></Col>
      <Col sm={6} xl={3}><StatCard value={openComments} label="Open discussions" detail="Unresolved comments across notebooks" variant="info" /></Col>
    </Row>

    <Tab.Container activeKey={topTab} onSelect={(key) => setTopTab(key)}>
      <Nav variant="tabs" className="notebook-main-tabs mb-4">
        <Nav.Item><Nav.Link eventKey="workspace">Experiment workspace</Nav.Link></Nav.Item>
        <Nav.Item><Nav.Link eventKey="notebooks">Notebooks & sharing</Nav.Link></Nav.Item>
        <Nav.Item><Nav.Link eventKey="templates">Templates</Nav.Link></Nav.Item>
      </Nav>
      <Tab.Content>
        <Tab.Pane eventKey="workspace">
          <Row className="g-4">
            <Col xl={3} lg={4}>
              <Card className="app-card notebook-sidebar"><Card.Body>
                <div className="toolbar-row mb-3"><div><h5 className="section-title mb-1">Experiment navigator</h5><div className="feed-meta">Choose a notebook and entry.</div></div>{selectedNotebook?.permissions?.write && <Button size="sm" variant="dark" onClick={() => setShowExperimentModal(true)}>New</Button>}</div>
                <Form.Label>Notebook</Form.Label>
                <Form.Select className="mb-3" value={selectedNotebookId || ""} onChange={(event) => selectNotebook(notebooks.find((row) => String(row.id) === event.target.value))}>{notebooks.map((notebook) => <option key={notebook.id} value={notebook.id}>{notebook.name}</option>)}</Form.Select>
                {selectedNotebook && <div className="notebook-scope-summary mb-3"><Badge bg="light" text="dark">{selectedNotebook.scope}</Badge><span>{selectedNotebook.project_code || `Owner: ${selectedNotebook.owner_username}`}</span></div>}
                <Form.Control className="mb-2" type="search" placeholder="Search experiments" value={experimentSearch} onChange={(event) => setExperimentSearch(event.target.value)} />
                <Form.Select className="mb-2" value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="">All states</option>{STATUS_OPTIONS.map((status) => <option key={status} value={status}>{statusLabel(status)} ({statusCounts[status]})</option>)}</Form.Select>
                <Form.Check className="mb-3" checked={myWorkOnly} label="Created by or assigned to me" onChange={(event) => setMyWorkOnly(event.target.checked)} />
                <div className="notebook-experiment-list">{visibleExperiments.length === 0 ? <div className="empty-state py-4">No matching experiments.</div> : visibleExperiments.map((experiment) => <button type="button" className={`notebook-experiment-row ${selected?.id === experiment.id ? "active" : ""}`} key={experiment.id} onClick={() => selectExperiment(experiment)}>
                  <div className="d-flex justify-content-between gap-2"><strong>{experiment.title}</strong><Badge bg={statusColor(experiment.status)}>{statusLabel(experiment.status)}</Badge></div>
                  <div className="feed-meta mt-1">r{experiment.current_revision_detail?.number || 0} · {experiment.created_by_username}</div>
                  {(experiment.assignee_usernames || []).length > 0 && <div className="feed-meta mt-1">Assigned: {experiment.assignee_usernames.join(", ")}</div>}
                </button>)}</div>
              </Card.Body></Card>
            </Col>
            <Col xl={9} lg={8}>
              {!selected ? <Card className="app-card"><Card.Body><div className="empty-state"><h5>No experiment selected</h5><p>Create a blank experiment or start from a template.</p>{selectedNotebook?.permissions?.write && <Button variant="dark" onClick={() => setShowExperimentModal(true)}>Create experiment</Button>}</div></Card.Body></Card> : <ExperimentWorkspace
                selected={selected} editable={editable} blocks={blocks} links={links} users={users}
                attachments={attachments} attachmentForm={attachmentForm} setAttachmentForm={setAttachmentForm}
                linkTargets={linkTargets} linkForm={linkForm} setLinkForm={setLinkForm} targetOptions={targetOptions}
                linkTargetLoading={Boolean(linkTargetLoading[linkForm.entity_type])}
                detailTab={detailTab} onDetailTabChange={changeDetailTab} onLinkTypeChange={changeLinkType} saveState={saveState}
                experimentMeta={experimentMeta} setExperimentMeta={setExperimentMeta}
                commentForm={commentForm} setCommentForm={setCommentForm}
                compareForm={compareForm} setCompareForm={setCompareForm} comparison={comparison}
                comparisonLoading={comparisonLoading} locale={locale}
                onSave={() => saveContent(blocks, links, "Manual save")}
                onWorkflow={openWorkflowAction} onDownload={() => apiDownload(`/api/experiments/${selected.id}/export-pdf/`, `${selected.title}.pdf`)}
                onAddBlock={addBlock} onSequenceFocus={() => loadLinkTargets("sequence")}
                onBlockChange={changeBlock} onBlockMove={moveBlock} onBlockDuplicate={duplicateBlock}
                onBlockRemove={(index) => updateBlocks(blocks.filter((_, blockIndex) => blockIndex !== index))}
                onAddLink={addLink} onRemoveLink={removeLink} onUploadAttachment={uploadAttachment} onAddComment={addComment}
                onResolveComment={resolveComment} onCompare={compareRevisions} onSaveMeta={saveExperimentMeta}
                formatDate={formatDate}
              />}
            </Col>
          </Row>
        </Tab.Pane>

        <Tab.Pane eventKey="notebooks">
          <NotebookManagement
            notebooks={notebooks} filteredNotebooks={filteredNotebooks} selectedNotebook={selectedNotebook}
            notebookSearch={notebookSearch} setNotebookSearch={setNotebookSearch} selectNotebook={selectNotebook}
            setShowNotebookModal={setShowNotebookModal} form={notebookEditForm} setForm={setNotebookEditForm}
            projects={projects} users={users} onSubmit={updateNotebook}
          />
        </Tab.Pane>

        <Tab.Pane eventKey="templates">
          <TemplateManagement
            form={templateForm} setForm={setTemplateForm} notebooks={notebooks} selected={selected}
            selectedNotebook={selectedNotebook} templates={notebookTemplates} onCreate={createTemplate}
            onToggle={toggleTemplate} onUse={(template) => { setExperimentForm({ source: "template", template: String(template.id), title: "", assignees: [] }); setShowExperimentModal(true); }}
          />
        </Tab.Pane>
      </Tab.Content>
    </Tab.Container>

    <NotebookCreateModal show={showNotebookModal} onHide={() => setShowNotebookModal(false)} form={notebookForm} setForm={setNotebookForm} projects={projects} onSubmit={createNotebook} />
    <ExperimentCreateModal show={showExperimentModal} onHide={() => setShowExperimentModal(false)} form={experimentForm} setForm={setExperimentForm} templates={notebookTemplates} users={users} onSubmit={createExperiment} />
    <WorkflowModal action={workflowAction} setAction={setWorkflowAction} onSubmit={submitWorkflowAction} />
  </div>;
}

function ExperimentWorkspace(props) {
  const { selected, editable, blocks, links, users, attachments, attachmentForm, setAttachmentForm,
    linkTargets, linkForm, setLinkForm, linkTargetLoading,
    targetOptions, detailTab, onDetailTabChange, onLinkTypeChange, saveState, experimentMeta, setExperimentMeta,
    commentForm, setCommentForm, compareForm, setCompareForm, comparison, comparisonLoading,
    onSave, onWorkflow, onDownload, onAddBlock, onSequenceFocus, onBlockChange, onBlockMove, onBlockDuplicate,
    onBlockRemove, onAddLink, onRemoveLink, onUploadAttachment, onAddComment, onResolveComment, onCompare,
    onSaveMeta, formatDate } = props;
  return <>
    <Card className="app-card notebook-experiment-header mb-4"><Card.Body><div className="toolbar-row">
      <div><div className="inline-actions mb-2"><Badge bg={statusColor(selected.status)}>{statusLabel(selected.status)}</Badge><span className={`notebook-save-state ${saveState.includes("failed") ? "text-danger" : ""}`}>{saveState || `Revision ${selected.current_revision_detail?.number || 0}`}</span></div><h3 className="mb-1">{selected.title}</h3><div className="feed-meta">{selected.notebook_name} · {selected.project_code || "Private/team"} · created by {selected.created_by_username}</div></div>
      <div className="inline-actions">{editable && <Button variant="outline-primary" onClick={onSave}>Save now</Button>}{editable && <Button variant="outline-dark" onClick={() => onWorkflow("complete")}>Complete</Button>}{selected.permissions.review && selected.status === "COMPLETED" && <><Button variant="success" onClick={() => onWorkflow("approve")}>Approve</Button><Button variant="outline-warning" onClick={() => onWorkflow("changes")}>Request changes</Button></>}{selected.permissions.lock && selected.status === "REVIEWED" && <Button variant="dark" onClick={() => onWorkflow("lock")}>Lock</Button>}<Button variant="outline-secondary" onClick={() => onWorkflow("clone")}>Clone</Button><Button variant="outline-primary" onClick={onDownload}>PDF</Button></div>
    </div></Card.Body></Card>
    <Tab.Container activeKey={detailTab} onSelect={onDetailTabChange}>
      <Nav variant="pills" className="notebook-detail-tabs mb-3">
        <Nav.Item><Nav.Link eventKey="entry">Entry</Nav.Link></Nav.Item>
        <Nav.Item><Nav.Link eventKey="provenance">Provenance <Badge bg="light" text="dark">{links.length}</Badge></Nav.Link></Nav.Item>
        <Nav.Item><Nav.Link eventKey="discussion">Discussion <Badge bg="light" text="dark">{(selected.comments || []).filter((row) => !row.resolved).length}</Badge></Nav.Link></Nav.Item>
        <Nav.Item><Nav.Link eventKey="history">History <Badge bg="light" text="dark">{selected.revisions?.length || 0}</Badge></Nav.Link></Nav.Item>
        <Nav.Item><Nav.Link eventKey="details">Details</Nav.Link></Nav.Item>
      </Nav>
      <Tab.Content>
        <Tab.Pane eventKey="entry"><Card className="app-card"><Card.Body>
          <div className="toolbar-row mb-3"><div><h5 className="section-title mb-1">Experiment entry</h5><div className="feed-meta">Use structured blocks; changes autosave into immutable revisions.</div></div>{editable && <Form.Select className="notebook-add-block" defaultValue="" onChange={(event) => { if (event.target.value) onAddBlock(event.target.value); event.target.value = ""; }}><option value="">Add a block...</option>{BLOCK_CATALOG.map((item) => <option key={item.type} value={item.type}>{item.label}</option>)}</Form.Select>}</div>
          {blocks.length === 0 ? <div className="empty-state py-5"><p>This experiment has no blocks.</p>{editable && <Button variant="outline-dark" onClick={() => onAddBlock("RICH_TEXT")}>Add first block</Button>}</div> : blocks.map((block, index) => <BlockEditor key={block._key} block={block} index={index} count={blocks.length} editable={editable} sequenceOptions={linkTargets.sequence || []} onSequenceFocus={onSequenceFocus} onChange={(next) => onBlockChange(index, next)} onMove={(direction) => onBlockMove(index, direction)} onDuplicate={() => onBlockDuplicate(index)} onRemove={() => onBlockRemove(index)} />)}
        </Card.Body></Card></Tab.Pane>

        <Tab.Pane eventKey="provenance"><Card className="app-card"><Card.Body>
          <h5 className="section-title">Exact linked versions</h5><p className="feed-meta">Each revision preserves the precise registry record, sample, lot, SOP, sequence, workflow, work item, or result used.</p>
          {editable && <Form onSubmit={onAddLink} className="notebook-link-form"><Row className="g-2"><Col md={3}><Form.Label>Record type</Form.Label><Form.Select value={linkForm.entity_type} onChange={(event) => onLinkTypeChange(event.target.value)}>{LINK_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</Form.Select></Col><Col md={5}><Form.Label>Exact record</Form.Label><Form.Select required disabled={linkTargetLoading} value={linkForm.public_id} onChange={(event) => setLinkForm({ ...linkForm, public_id: event.target.value })}><option value="">{linkTargetLoading ? "Loading records..." : "Choose exact record"}</option>{targetOptions.map((target) => <option key={target.public_id} value={target.public_id}>{targetLabel(target)}</option>)}</Form.Select></Col><Col md={2}><Form.Label>Relationship</Form.Label><Form.Select value={linkForm.relation_type} onChange={(event) => setLinkForm({ ...linkForm, relation_type: event.target.value })}>{RELATION_TYPES.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</Form.Select></Col><Col md={2} className="d-flex align-items-end"><Button className="w-100" type="submit">Add link</Button></Col></Row></Form>}
          {links.length === 0 ? <div className="empty-state py-4">No records linked to this revision.</div> : <Table responsive className="app-table mt-3 align-middle"><thead><tr><th>Type</th><th>Record</th><th>Relationship</th><th>Captured version</th>{editable && <th />}</tr></thead><tbody>{links.map((link, index) => <tr key={`${link.entity_type}-${link.public_id}-${link.relation_type}`}><td>{LINK_TYPES.find(([value]) => value === link.entity_type)?.[1] || link.entity_type}</td><td><strong>{link.label}</strong></td><td>{RELATION_TYPES.find(([value]) => value === link.relation_type)?.[1] || link.relation_type}</td><td><code className="notebook-version-code">{link.version ? JSON.stringify(link.version) : "Captured when saved"}</code></td>{editable && <td><Button size="sm" variant="outline-danger" onClick={() => onRemoveLink(index)}>Unlink</Button></td>}</tr>)}</tbody></Table>}
          <hr className="my-4" /><h6>Experiment attachments</h6><p className="feed-meta">Files use the shared attachment service with uploader, size, media type, and SHA-256 provenance.</p>
          {editable && <Form onSubmit={onUploadAttachment} className="notebook-link-form mb-3"><Row className="g-2"><Col md={5}><Form.Label>File</Form.Label><Form.Control type="file" required onChange={(event) => setAttachmentForm({ ...attachmentForm, file: event.target.files?.[0] || null })} /></Col><Col md={5}><Form.Label>Description</Form.Label><Form.Control value={attachmentForm.description} onChange={(event) => setAttachmentForm({ ...attachmentForm, description: event.target.value })} /></Col><Col md={2} className="d-flex align-items-end"><Button className="w-100" type="submit" disabled={!attachmentForm.file}>Upload</Button></Col></Row></Form>}
          {attachments.length === 0 ? <div className="empty-state py-3">No experiment attachments.</div> : <div className="d-grid gap-2">{attachments.map((attachment) => <div className="notebook-attachment" key={attachment.public_id}><div><a href={attachment.file} target="_blank" rel="noreferrer"><strong>{attachment.display_name || attachment.filename}</strong></a><div className="feed-meta">{attachment.description || "No description"}</div></div><div className="text-end feed-meta">{attachment.uploaded_by_username || "System"}<br />{attachment.size_bytes} bytes · SHA-256 {attachment.sha256.slice(0, 12)}…</div></div>)}</div>}
        </Card.Body></Card></Tab.Pane>

        <Tab.Pane eventKey="discussion"><DiscussionPanel selected={selected} users={users} form={commentForm} setForm={setCommentForm} onSubmit={onAddComment} onResolve={onResolveComment} formatDate={formatDate} /></Tab.Pane>
        <Tab.Pane eventKey="history"><HistoryPanel selected={selected} editable={editable} form={compareForm} setForm={setCompareForm} comparison={comparison} loading={comparisonLoading} onCompare={onCompare} onWorkflow={onWorkflow} formatDate={formatDate} /></Tab.Pane>
        <Tab.Pane eventKey="details"><Card className="app-card"><Card.Body><h5 className="section-title">Experiment details</h5><Form onSubmit={onSaveMeta}><Row className="g-3"><Col xs={12}><Form.Label>Title</Form.Label><Form.Control required value={experimentMeta.title} disabled={!editable} onChange={(event) => setExperimentMeta({ ...experimentMeta, title: event.target.value })} /></Col><Col xs={12}><MultiUserSelect label="Assignees" users={users} value={experimentMeta.assignees} disabled={!editable} onChange={(assignees) => setExperimentMeta({ ...experimentMeta, assignees })} help="Assignees can find this experiment through the My work filter." /></Col></Row>{editable && <Button className="mt-3" variant="dark" type="submit">Save experiment details</Button>}</Form><hr /><dl className="row mb-0"><dt className="col-sm-4">Public ID</dt><dd className="col-sm-8"><code>{selected.public_id}</code></dd><dt className="col-sm-4">Created</dt><dd className="col-sm-8">{formatDate(selected.created_at)}</dd><dt className="col-sm-4">Last updated</dt><dd className="col-sm-8">{formatDate(selected.updated_at)}</dd><dt className="col-sm-4">Current checksum</dt><dd className="col-sm-8"><code>{selected.current_revision_detail?.checksum || "—"}</code></dd></dl></Card.Body></Card></Tab.Pane>
      </Tab.Content>
    </Tab.Container>
  </>;
}

function DiscussionPanel({ selected, users, form, setForm, onSubmit, onResolve, formatDate }) {
  return <Card className="app-card"><Card.Body><h5 className="section-title">Comments, mentions, and assignments</h5><p className="feed-meta">Discuss any revision without changing signed-off content.</p>
    {selected.permissions.comment && <Form onSubmit={onSubmit} className="notebook-comment-form mb-4"><Form.Control as="textarea" rows={3} required value={form.body} onChange={(event) => setForm({ ...form, body: event.target.value })} placeholder="Add context, ask a question, or record a review note..." /><Row className="g-2 mt-1"><Col md={5}><Form.Label>Mention collaborators</Form.Label><Form.Select multiple value={form.mentions.map(String)} onChange={(event) => setForm({ ...form, mentions: Array.from(event.target.selectedOptions, (option) => Number(option.value)) })}>{users.map((user) => <option key={user.id} value={user.id}>{user.full_name || user.username}</option>)}</Form.Select></Col><Col md={5}><Form.Label>Assign follow-up</Form.Label><Form.Select value={form.assigned_to} onChange={(event) => setForm({ ...form, assigned_to: event.target.value })}><option value="">No assignment</option>{users.map((user) => <option key={user.id} value={user.id}>{user.full_name || user.username}</option>)}</Form.Select></Col><Col md={2} className="d-flex align-items-end"><Button className="w-100" type="submit">Comment</Button></Col></Row></Form>}
    {(selected.comments || []).length === 0 ? <div className="empty-state py-4">No discussion yet.</div> : <div className="d-grid gap-3">{selected.comments.map((row) => <div className={`notebook-comment ${row.resolved ? "resolved" : ""}`} key={row.public_id}><div className="toolbar-row"><div><strong>{row.author_username}</strong> <Badge bg={row.resolved ? "secondary" : "info"}>{row.resolved ? "Resolved" : "Unresolved"}</Badge></div>{selected.permissions.comment && <Button size="sm" variant="outline-secondary" onClick={() => onResolve(row, !row.resolved)}>{row.resolved ? "Reopen" : "Resolve"}</Button>}</div><p className="mb-2 mt-2">{row.body}</p><div className="feed-meta">{formatDate(row.created_at)} · {row.revision ? `revision ${row.revision}` : "general comment"}{row.assigned_to_username ? ` · assigned to ${row.assigned_to_username}` : ""}{row.mention_usernames?.length ? ` · mentioned ${row.mention_usernames.join(", ")}` : ""}</div></div>)}</div>}
  </Card.Body></Card>;
}

function HistoryPanel({ selected, editable, form, setForm, comparison, loading, onCompare, onWorkflow, formatDate }) {
  return <><Card className="app-card mb-4"><Card.Body><h5 className="section-title">Compare immutable revisions</h5><Form onSubmit={onCompare}><Row className="g-2"><Col md={5}><Form.Label>Before</Form.Label><Form.Select required value={form.from} onChange={(event) => setForm({ ...form, from: event.target.value })}><option value="">Choose revision</option>{(selected.revisions || []).map((revision) => <option key={revision.public_id} value={revision.public_id}>r{revision.number} · {revision.change_summary}</option>)}</Form.Select></Col><Col md={5}><Form.Label>After</Form.Label><Form.Select required value={form.to} onChange={(event) => setForm({ ...form, to: event.target.value })}><option value="">Choose revision</option>{(selected.revisions || []).map((revision) => <option key={revision.public_id} value={revision.public_id}>r{revision.number} · {revision.change_summary}</option>)}</Form.Select></Col><Col md={2} className="d-flex align-items-end"><Button type="submit" className="w-100" disabled={loading}>{loading ? "Comparing..." : "Compare"}</Button></Col></Row></Form>
    {comparison && <div className="notebook-comparison mt-3"><div className="inline-actions mb-3"><Badge bg="primary">r{comparison.before.number} → r{comparison.after.number}</Badge><Badge bg="success">{comparison.summary.blocks_added} blocks added</Badge><Badge bg="warning" text="dark">{comparison.summary.blocks_modified} modified</Badge><Badge bg="danger">{comparison.summary.blocks_removed} removed</Badge><Badge bg="info">{comparison.summary.links_added + comparison.summary.links_modified + comparison.summary.links_removed} link changes</Badge></div>{comparison.block_changes.map((change) => <div className="notebook-change" key={`${change.position}-${change.change}`}><div><Badge bg={change.change === "added" ? "success" : change.change === "removed" ? "danger" : "warning"} text={change.change === "modified" ? "dark" : undefined}>{change.change}</Badge> Block {change.position + 1}</div><Row className="g-2 mt-1"><Col md={6}><small>Before</small><pre>{change.before ? JSON.stringify(change.before.data, null, 2) : "—"}</pre></Col><Col md={6}><small>After</small><pre>{change.after ? JSON.stringify(change.after.data, null, 2) : "—"}</pre></Col></Row></div>)}</div>}
  </Card.Body></Card><Card className="app-card"><Card.Body><h5 className="section-title">Revision and sign-off history</h5><Table responsive className="app-table align-middle"><thead><tr><th>Revision</th><th>Author</th><th>Timestamp</th><th>Change</th><th>Checksum</th><th /></tr></thead><tbody>{(selected.revisions || []).map((revision) => <tr key={revision.public_id}><td><strong>r{revision.number}</strong>{revision.number === selected.current_revision_detail?.number && <Badge bg="primary" className="ms-2">Current</Badge>}</td><td>{revision.created_by_username || "System"}</td><td>{formatDate(revision.created_at)}</td><td>{revision.change_summary}</td><td><code>{revision.checksum.slice(0, 12)}…</code></td><td>{editable && revision.number !== selected.current_revision_detail?.number && <Button size="sm" variant="outline-dark" onClick={() => onWorkflow("restore", { revision })}>Restore</Button>}</td></tr>)}</tbody></Table>
    {(selected.reviews || []).length > 0 && <><h6 className="mt-4">Review sign-off</h6><Table responsive className="app-table"><thead><tr><th>Reviewer</th><th>Decision</th><th>Signed name</th><th>Revision</th><th>Timestamp</th><th>Comment</th></tr></thead><tbody>{selected.reviews.map((review) => <tr key={review.public_id}><td>{review.reviewer_username}</td><td><Badge bg={review.decision === "APPROVED" ? "success" : "warning"}>{statusLabel(review.decision)}</Badge></td><td>{review.signed_name}</td><td>r{review.revision_number}</td><td>{formatDate(review.reviewed_at)}</td><td>{review.comment || "—"}</td></tr>)}</tbody></Table></>}
  </Card.Body></Card></>;
}

function NotebookManagement({ filteredNotebooks, selectedNotebook, notebookSearch, setNotebookSearch, selectNotebook, setShowNotebookModal, form, setForm, projects, users, onSubmit }) {
  return <Row className="g-4"><Col lg={4}><Card className="app-card"><Card.Body><div className="toolbar-row mb-3"><div><h5 className="section-title mb-1">All laboratory notebooks</h5><div className="feed-meta">Everything you own or can access.</div></div><Button size="sm" variant="dark" onClick={() => setShowNotebookModal(true)}>New</Button></div><Form.Control type="search" className="mb-3" placeholder="Search notebooks" value={notebookSearch} onChange={(event) => setNotebookSearch(event.target.value)} /><div className="d-grid gap-2">{filteredNotebooks.map((notebook) => <button type="button" key={notebook.id} className={`notebook-list-row ${selectedNotebook?.id === notebook.id ? "active" : ""}`} onClick={() => selectNotebook(notebook)}><div className="d-flex justify-content-between"><strong>{notebook.name}</strong><Badge bg="light" text="dark">{notebook.scope}</Badge></div><div className="feed-meta mt-1">{notebook.project_code || notebook.owner_username} · {notebook.experiment_count} experiments</div></button>)}</div></Card.Body></Card></Col>
  <Col lg={8}><Card className="app-card"><Card.Body><h5 className="section-title">Notebook metadata and sharing</h5>{!selectedNotebook || !form ? <div className="empty-state">Choose or create a notebook.</div> : <Form onSubmit={onSubmit}><Row className="g-3"><Col md={8}><Form.Label>Name</Form.Label><Form.Control required value={form.name} disabled={!selectedNotebook.permissions.write} onChange={(event) => setForm({ ...form, name: event.target.value })} /></Col><Col md={4}><Form.Label>Scope</Form.Label><Form.Select value={form.scope} disabled={!selectedNotebook.permissions.write} onChange={(event) => setForm({ ...form, scope: event.target.value, project: event.target.value === "PROJECT" ? form.project : "" })}><option value="USER">User</option><option value="TEAM">Team</option><option value="PROJECT">Project</option></Form.Select></Col><Col xs={12}><Form.Label>Description</Form.Label><Form.Control as="textarea" rows={3} value={form.description} disabled={!selectedNotebook.permissions.write} onChange={(event) => setForm({ ...form, description: event.target.value })} /></Col>{form.scope === "PROJECT" && <Col xs={12}><Form.Label>Project</Form.Label><Form.Select required value={form.project} disabled={!selectedNotebook.permissions.write} onChange={(event) => setForm({ ...form, project: event.target.value })}><option value="">Choose project</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.code} — {project.name}</option>)}</Form.Select></Col>}{form.scope === "TEAM" && <Col md={6}><MultiUserSelect label="Team members" users={users} value={form.team_members} disabled={!selectedNotebook.permissions.write} onChange={(team_members) => setForm({ ...form, team_members })} /></Col>}<Col md={6}><MultiUserSelect label="Readers" users={users} value={form.readers} disabled={!selectedNotebook.permissions.write} onChange={(readers) => setForm({ ...form, readers })} help="Can view notebook content." /></Col><Col md={6}><MultiUserSelect label="Editors" users={users} value={form.editors} disabled={!selectedNotebook.permissions.write} onChange={(editors) => setForm({ ...form, editors })} help="Can change experiments and create revisions." /></Col><Col md={6}><MultiUserSelect label="Commenters" users={users} value={form.commenters} disabled={!selectedNotebook.permissions.write} onChange={(commenters) => setForm({ ...form, commenters })} help="Can discuss without editing content." /></Col><Col md={6}><MultiUserSelect label="Reviewers" users={users} value={form.reviewers} disabled={!selectedNotebook.permissions.write} onChange={(reviewers) => setForm({ ...form, reviewers })} /></Col><Col md={6}><MultiUserSelect label="Lockers" users={users} value={form.lockers} disabled={!selectedNotebook.permissions.write} onChange={(lockers) => setForm({ ...form, lockers })} /></Col></Row>{selectedNotebook.permissions.write && <Button type="submit" variant="dark" className="mt-3">Save notebook settings</Button>}</Form>}</Card.Body></Card></Col></Row>;
}

function TemplateManagement({ form, setForm, notebooks, selected, selectedNotebook, templates, onCreate, onToggle, onUse }) {
  return <Row className="g-4"><Col lg={5}><Card className="app-card"><Card.Body><h5 className="section-title">Create reusable template</h5><Form onSubmit={onCreate}><Form.Group className="mb-3"><Form.Label>Notebook</Form.Label><Form.Select required value={form.notebook} onChange={(event) => setForm({ ...form, notebook: event.target.value })}><option value="">Choose notebook</option>{notebooks.filter((notebook) => notebook.permissions.write).map((notebook) => <option key={notebook.id} value={notebook.id}>{notebook.name}</option>)}</Form.Select></Form.Group><Form.Group className="mb-3"><Form.Label>Template name</Form.Label><Form.Control required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></Form.Group><Form.Group className="mb-3"><Form.Label>Description</Form.Label><Form.Control as="textarea" rows={2} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></Form.Group><Form.Group className="mb-3"><Form.Label>Starting blocks</Form.Label><Form.Select value={form.source} onChange={(event) => setForm({ ...form, source: event.target.value })}><option value="default">Standard experiment structure</option><option value="current" disabled={!selected || String(selected.notebook) !== String(form.notebook)}>Copy the currently open experiment</option></Form.Select></Form.Group><Button type="submit" variant="dark">Create template</Button></Form></Card.Body></Card></Col><Col lg={7}><Card className="app-card"><Card.Body><h5 className="section-title mb-1">Templates in {selectedNotebook?.name || "notebook"}</h5><div className="feed-meta">Clone a consistent structure without changing the source.</div>{templates.length === 0 ? <div className="empty-state py-5">No templates in this notebook.</div> : <div className="d-grid gap-3 mt-3">{templates.map((template) => <div className={`notebook-template ${!template.active ? "inactive" : ""}`} key={template.id}><div className="toolbar-row"><div><div><strong>{template.name}</strong> <Badge bg={template.active ? "success" : "secondary"}>{template.active ? "Active" : "Inactive"}</Badge></div><p className="mb-1 mt-2">{template.description || "No description"}</p><div className="feed-meta">{template.blocks.length} blocks · created by {template.created_by_username || "System"}</div></div><div className="inline-actions">{selectedNotebook?.permissions?.write && <Button size="sm" variant="outline-secondary" onClick={() => onToggle(template)}>{template.active ? "Deactivate" : "Activate"}</Button>}<Button size="sm" variant="dark" disabled={!template.active} onClick={() => onUse(template)}>Use template</Button></div></div></div>)}</div>}</Card.Body></Card></Col></Row>;
}

function NotebookCreateModal({ show, onHide, form, setForm, projects, onSubmit }) {
  return <Modal show={show} onHide={onHide} centered><Form onSubmit={onSubmit}><Modal.Header closeButton><Modal.Title>Create laboratory notebook</Modal.Title></Modal.Header><Modal.Body><Form.Group className="mb-3"><Form.Label>Name</Form.Label><Form.Control autoFocus required value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} /></Form.Group><Form.Group className="mb-3"><Form.Label>Description</Form.Label><Form.Control as="textarea" rows={3} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></Form.Group><Form.Group className="mb-3"><Form.Label>Scope</Form.Label><Form.Select value={form.scope} onChange={(event) => setForm({ ...form, scope: event.target.value, project: event.target.value === "PROJECT" ? form.project : "" })}><option value="USER">Personal — visible only to you and people you share with</option><option value="TEAM">Team — visible to selected team members</option><option value="PROJECT">Project — governed by project membership</option></Form.Select></Form.Group>{form.scope === "PROJECT" && <Form.Group><Form.Label>Project</Form.Label><Form.Select required value={form.project} onChange={(event) => setForm({ ...form, project: event.target.value })}><option value="">Choose project</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.code} — {project.name}</option>)}</Form.Select></Form.Group>}</Modal.Body><Modal.Footer><Button variant="outline-secondary" onClick={onHide}>Cancel</Button><Button variant="dark" type="submit">Create notebook</Button></Modal.Footer></Form></Modal>;
}

function ExperimentCreateModal({ show, onHide, form, setForm, templates, users, onSubmit }) {
  return <Modal show={show} onHide={onHide} centered><Form onSubmit={onSubmit}><Modal.Header closeButton><Modal.Title>New experiment</Modal.Title></Modal.Header><Modal.Body><Form.Group className="mb-3"><Form.Label>Start from</Form.Label><Form.Select value={form.source} onChange={(event) => setForm({ ...form, source: event.target.value })}><option value="blank">Standard blank experiment</option><option value="template">Notebook template</option></Form.Select></Form.Group>{form.source === "template" && <Form.Group className="mb-3"><Form.Label>Template</Form.Label><Form.Select required value={form.template} onChange={(event) => setForm({ ...form, template: event.target.value })}><option value="">Choose template</option>{templates.filter((template) => template.active).map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}</Form.Select></Form.Group>}<Form.Group className="mb-3"><Form.Label>Experiment title</Form.Label><Form.Control autoFocus required={form.source === "blank"} value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} placeholder={form.source === "template" ? "Optional — defaults to template name" : "Describe this experiment"} /></Form.Group><MultiUserSelect label="Assignees" users={users} value={form.assignees} onChange={(assignees) => setForm({ ...form, assignees })} /></Modal.Body><Modal.Footer><Button variant="outline-secondary" onClick={onHide}>Cancel</Button><Button variant="dark" type="submit">Create experiment</Button></Modal.Footer></Form></Modal>;
}

function WorkflowModal({ action, setAction, onSubmit }) {
  if (!action) return null;
  const titles = { complete: "Complete experiment", approve: "Approve experiment", changes: "Request changes", lock: "Lock reviewed experiment", clone: "Clone experiment", restore: `Restore revision ${action.revision?.number || ""}` };
  return <Modal show onHide={() => setAction(null)} centered><Form onSubmit={onSubmit}><Modal.Header closeButton><Modal.Title>{titles[action.type]}</Modal.Title></Modal.Header><Modal.Body>
    {action.type === "clone" && <Form.Group><Form.Label>New experiment title</Form.Label><Form.Control required value={action.title} onChange={(event) => setAction({ ...action, title: event.target.value })} /></Form.Group>}
    {["approve", "changes"].includes(action.type) && <><Form.Group className="mb-3"><Form.Label>{action.type === "approve" ? "Review comment" : "Required changes"}</Form.Label><Form.Control as="textarea" rows={3} required={action.type === "changes"} value={action.comment} onChange={(event) => setAction({ ...action, comment: event.target.value })} /></Form.Group><Form.Group><Form.Label>Signed name</Form.Label><Form.Control required value={action.signed_name} onChange={(event) => setAction({ ...action, signed_name: event.target.value })} /><Form.Text>This is an internal sign-off. Formal regulated electronic signatures remain a v1.0 hardening item.</Form.Text></Form.Group></>}
    {["complete", "lock", "restore"].includes(action.type) && <Form.Group><Form.Label>Reason</Form.Label><Form.Control as="textarea" rows={3} required value={action.reason} onChange={(event) => setAction({ ...action, reason: event.target.value })} /></Form.Group>}
    {action.type === "lock" && <Alert variant="warning" className="mt-3 mb-0">Locking freezes the reviewed content. Create a clone if more work is needed.</Alert>}
  </Modal.Body><Modal.Footer><Button variant="outline-secondary" onClick={() => setAction(null)}>Cancel</Button><Button variant={action.type === "lock" ? "dark" : action.type === "approve" ? "success" : "primary"} type="submit">Confirm</Button></Modal.Footer></Form></Modal>;
}
