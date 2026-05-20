import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  Row,
  Table,
} from "react-bootstrap";
import { SeqViz } from "seqviz";
import { apiDelete, apiGet, apiPatch, apiPost } from "../api";

const demoSequence =
  "TTGACGGCTAGCTCAGTCCTAGGTACAGTGCTAGCGGATCCATGGTGAGCAAGGGCGAGGAGCTGTTCACCGGGGTGGTGCCCATCCTGGTCGAGCTGGACGGCGACGTAAACGGCCACAAGTTCAGCGTGTCCGGCGAGGGCGAGGGCGATGCCACCTACGGCAAGCTGACCCTGAAGTTCATCTGCACCACCGGCAAGCTGCCCGTGCCCTGGCCCACCCTCGTGACCACCCTGACCTACGGCGTGCAGTGCTTCAGCCGCTACCCCGACCACATGAAGCAGCACGACTTCTTCAAGTCCGCCATGCCCGAAGGCTACGTCCAGGAGCGCACCATCTTCTTCAAGGACGACGGCAACTACAAGACCCGCGCCGAGGTGAAGTTCGAGGGCGACACCCTGGTGAACCGCATCGAGCTGAAGGGCATCGACTTCAAGGAGGACGGCAACATCCTGGGGCACAAGCTGGAGTACAACTACAACAGCCACAACGTCTATATCATGGCCGACAAGCAGAAGAACGGCATCAAGGTGAACTTCAAGATCCGCCACAACATCGAGGACGGCAGCGTGCAGCTCGCCGACCACTACCAGCAGAACACCCCCATCGGCGACGGCCCCGTGCTGCTGCCCGACAACCACTACCTGAGCACCCAGTCCGCCCTGAGCAAAGACCCCAACGAGAAGCGCGATCACATGGTCCTGCTGGAGTTCGTGACCGCCGCCGGGATCACTCTCGGCATGGACGAGCTGTACAAGTAA";

const defaultAnnotations = [
  {
    name: "Promoter",
    start: 0,
    end: 35,
    direction: 1,
    color: "#2563eb",
  },
  {
    name: "BamHI",
    start: 37,
    end: 43,
    direction: 1,
    color: "#f97316",
  },
  {
    name: "GFP CDS",
    start: 43,
    end: 763,
    direction: 1,
    color: "#22c55e",
  },
];

const defaultPrimers = [
  {
    name: "GFP Forward",
    start: 43,
    end: 63,
    direction: 1,
    color: "#9333ea",
  },
  {
    name: "GFP Reverse",
    start: 730,
    end: 760,
    direction: -1,
    color: "#db2777",
  },
];

const defaultTranslations = [
  {
    name: "GFP Translation",
    start: 43,
    end: 763,
    direction: 1,
    color: "#16a34a",
  },
];

const defaultHighlights = [
  {
    name: "QC Review Region",
    start: 120,
    end: 180,
    color: "#fde047",
  },
];

const defaultEnzymes = ["EcoRI", "BamHI", "HindIII", "PstI", "XhoI"];

const defaultBpColors = {
  A: "#ef4444",
  T: "#3b82f6",
  G: "#22c55e",
  C: "#f59e0b",
};

function cleanSequenceText(value) {
  return value.replace(/\s/g, "").toUpperCase();
}

function clampRange(item, sequenceLength) {
  const start = Math.max(0, Number(item.start || 0));
  const end = Math.min(sequenceLength, Number(item.end || 0));

  return {
    ...item,
    start,
    end,
    direction: Number(item.direction || 1),
  };
}

function isValidNamedRange(item, sequenceLength) {
  return (
    item.name &&
    item.start !== "" &&
    item.end !== "" &&
    Number(item.start) >= 0 &&
    Number(item.end) > Number(item.start) &&
    Number(item.end) <= sequenceLength
  );
}

function isValidRange(item, sequenceLength) {
  return (
    item.start !== "" &&
    item.end !== "" &&
    Number(item.start) >= 0 &&
    Number(item.end) > Number(item.start) &&
    Number(item.end) <= sequenceLength
  );
}

function formatRange(item) {
  return `${item.start}–${item.end}`;
}

function ColorSwatch({ color }) {
  return (
    <span
      style={{
        display: "inline-block",
        width: "18px",
        height: "18px",
        borderRadius: "6px",
        background: color,
        border: "1px solid #d1d5db",
        verticalAlign: "middle",
        marginRight: "8px",
      }}
    />
  );
}

function SelectionDetails({ selection }) {
  if (!selection) {
    return (
      <div className="empty-state">
        Click or drag on the sequence viewer to inspect a region.
      </div>
    );
  }

  return (
    <div className="soft-card">
      <div className="feed-meta mb-2">Selected Region</div>

      <div>
        <strong>Start:</strong> {selection.start ?? "-"}
      </div>

      <div>
        <strong>End:</strong> {selection.end ?? "-"}
      </div>

      <div>
        <strong>Length:</strong> {selection.length ?? "-"}
      </div>

      {selection.name && (
        <div>
          <strong>Name:</strong> {selection.name}
        </div>
      )}

      {selection.type && (
        <div>
          <strong>Type:</strong> {selection.type}
        </div>
      )}
    </div>
  );
}

function JsonPreview({ title, data }) {
  return (
    <details className="mt-3">
      <summary className="feed-meta">{title}</summary>
      <pre className="app-pre mt-2">{JSON.stringify(data, null, 2)}</pre>
    </details>
  );
}

function FeatureTable({ items, type, onRemove }) {
  if (items.length === 0) {
    return <div className="empty-state mt-3">No {type} added yet.</div>;
  }

  return (
    <Table responsive hover className="app-table mt-3">
      <thead>
        <tr>
          <th>Name</th>
          <th>Range</th>
          <th>Dir</th>
          <th>Color</th>
          <th></th>
        </tr>
      </thead>

      <tbody>
        {items.map((item, index) => (
          <tr key={`${type}-${item.name || item.start}-${index}`}>
            <td>{item.name || "-"}</td>
            <td>{formatRange(item)}</td>
            <td>{item.direction === -1 ? "REV" : "FWD"}</td>
            <td>
              <ColorSwatch color={item.color} />
              {item.color}
            </td>
            <td>
              <Button
                variant="outline-danger"
                size="sm"
                onClick={() => onRemove(index)}
              >
                Remove
              </Button>
            </td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

export default function Sequences() {
  const [searchParams, setSearchParams] = useSearchParams();

  const [name, setName] = useState("Demo GFP Construct");
  const [description, setDescription] = useState("Saved from SeqViz workspace");
  const [sequenceType, setSequenceType] = useState("DNA");
  const [sequence, setSequence] = useState(demoSequence);

  const [projectId, setProjectId] = useState("");
  const [projects, setProjects] = useState([]);

  const [viewer, setViewer] = useState("both");
  const [showComplement, setShowComplement] = useState(true);
  const [rotateOnScroll, setRotateOnScroll] = useState(false);
  const [zoom, setZoom] = useState(50);

  const [annotations, setAnnotations] = useState(defaultAnnotations);
  const [primers, setPrimers] = useState(defaultPrimers);
  const [translations, setTranslations] = useState(defaultTranslations);
  const [highlights, setHighlights] = useState(defaultHighlights);
  const [enzymes, setEnzymes] = useState(defaultEnzymes);
  const [bpColors, setBpColors] = useState(defaultBpColors);

  const [selection, setSelection] = useState(null);
  const [searchResults, setSearchResults] = useState([]);
  const [searchQuery, setSearchQuery] = useState("ATG");
  const [searchMismatch, setSearchMismatch] = useState(0);

  const [savedSequences, setSavedSequences] = useState([]);
  const [selectedSequenceId, setSelectedSequenceId] = useState("");
  const [saveMessage, setSaveMessage] = useState("");
  const [saveError, setSaveError] = useState("");
  const [saving, setSaving] = useState(false);
  const [loadingWorkspace, setLoadingWorkspace] = useState(false);

  const [annotationForm, setAnnotationForm] = useState({
    name: "",
    start: "",
    end: "",
    direction: "1",
    color: "#22c55e",
  });

  const [primerForm, setPrimerForm] = useState({
    name: "",
    start: "",
    end: "",
    direction: "1",
    color: "#9333ea",
  });

  const [translationForm, setTranslationForm] = useState({
    name: "",
    start: "",
    end: "",
    direction: "1",
    color: "#16a34a",
  });

  const [highlightForm, setHighlightForm] = useState({
    name: "Selected Highlight",
    start: "",
    end: "",
    color: "#fde047",
  });

  const [enzymeName, setEnzymeName] = useState("");

  const [customEnzyme, setCustomEnzyme] = useState({
    name: "",
    rseq: "",
    fcut: "0",
    rcut: "0",
    color: "#dbeafe",
  });

  const cleanSequence = useMemo(() => cleanSequenceText(sequence), [sequence]);
  const sequenceLength = cleanSequence.length;

  const selectedProject = projects.find(
    (project) => String(project.id) === String(projectId)
  );

  const search = useMemo(() => {
    if (!searchQuery.trim()) return {};

    return {
      query: cleanSequenceText(searchQuery),
      mismatch: Number(searchMismatch || 0),
    };
  }, [searchQuery, searchMismatch]);

  useEffect(() => {
    loadInitialData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function loadInitialData() {
    await Promise.all([loadSavedSequences(), loadProjects()]);

    const workspaceId = searchParams.get("workspace");

    if (workspaceId) {
      await loadSequenceWorkspace(workspaceId);
    }
  }

  async function loadProjects() {
    try {
      const data = await apiGet("/api/projects/");
      setProjects(data.results || data || []);
    } catch (e) {
      setSaveError(e.message || String(e));
    }
  }

  async function loadSavedSequences() {
    setSaveError("");

    try {
      const data = await apiGet("/api/sequences/");
      setSavedSequences(data.results || data || []);
    } catch (e) {
      setSaveError(e.message || String(e));
    }
  }

  function hasSelectionRange() {
    return (
      selection &&
      selection.start !== undefined &&
      selection.end !== undefined &&
      Number(selection.end) > Number(selection.start)
    );
  }

  function useSelectionForAnnotation() {
    if (!hasSelectionRange()) return;

    setAnnotationForm((prev) => ({
      ...prev,
      start: selection.start,
      end: selection.end,
      name: selection.name || prev.name || "Selected Annotation",
    }));
  }

  function useSelectionForPrimer() {
    if (!hasSelectionRange()) return;

    setPrimerForm((prev) => ({
      ...prev,
      start: selection.start,
      end: selection.end,
      name: selection.name || prev.name || "Selected Primer",
    }));
  }

  function useSelectionForTranslation() {
    if (!hasSelectionRange()) return;

    setTranslationForm((prev) => ({
      ...prev,
      start: selection.start,
      end: selection.end,
      name: selection.name || prev.name || "Selected Translation",
    }));
  }

  function useSelectionForHighlight() {
    if (!hasSelectionRange()) return;

    setHighlightForm((prev) => ({
      ...prev,
      start: selection.start,
      end: selection.end,
      name: prev.name || "Selected Highlight",
    }));
  }

  function resetDemo() {
    setName("Demo GFP Construct");
    setDescription("Saved from SeqViz workspace");
    setSequenceType("DNA");
    setSequence(demoSequence);
    setProjectId("");
    setViewer("both");
    setShowComplement(true);
    setRotateOnScroll(false);
    setZoom(50);
    setAnnotations(defaultAnnotations);
    setPrimers(defaultPrimers);
    setTranslations(defaultTranslations);
    setHighlights(defaultHighlights);
    setEnzymes(defaultEnzymes);
    setSearchQuery("ATG");
    setSearchMismatch(0);
    setSelection(null);
    setSearchResults([]);
    setBpColors(defaultBpColors);
  }

  function startNewWorkspace() {
    setSelectedSequenceId("");
    setSearchParams({});
    setSaveMessage("");
    setSaveError("");
    resetDemo();
  }

  function buildFeaturesPayload() {
    return [
      ...annotations.map((item) => ({
        feature_type: "ANNOTATION",
        name: item.name || "",
        start: item.start,
        end: item.end,
        direction: item.direction || 1,
        color: item.color || "#22c55e",
        metadata: {},
      })),

      ...primers.map((item) => ({
        feature_type: "PRIMER",
        name: item.name || "",
        start: item.start,
        end: item.end,
        direction: item.direction || 1,
        color: item.color || "#9333ea",
        metadata: {},
      })),

      ...translations.map((item) => ({
        feature_type: "TRANSLATION",
        name: item.name || "",
        start: item.start,
        end: item.end,
        direction: item.direction || 1,
        color: item.color || "#16a34a",
        metadata: {},
      })),

      ...highlights.map((item) => ({
        feature_type: "HIGHLIGHT",
        name: item.name || "",
        start: item.start,
        end: item.end,
        direction: 1,
        color: item.color || "#fde047",
        metadata: {},
      })),
    ];
  }

  async function saveSequenceWorkspace() {
    setSaveMessage("");
    setSaveError("");
    setSaving(true);

    const payload = {
      name,
      description,
      sequence_type: sequenceType,
      sequence: cleanSequence,
      project: projectId || null,
      viewer,
      show_complement: showComplement,
      rotate_on_scroll: rotateOnScroll,
      zoom,
      enzymes,
      bp_colors: bpColors,
      features: buildFeaturesPayload(),
    };

    try {
      let saved;

      if (selectedSequenceId) {
        saved = await apiPatch(`/api/sequences/${selectedSequenceId}/`, payload);
        setSaveMessage(`Updated "${saved.name}" successfully.`);
      } else {
        saved = await apiPost("/api/sequences/", payload);
        setSelectedSequenceId(String(saved.id));
        setSearchParams({ workspace: String(saved.id) });
        setSaveMessage(`Saved "${saved.name}" successfully.`);
      }

      await loadSavedSequences();
    } catch (e) {
      setSaveError(e.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  async function loadSequenceWorkspace(id) {
    if (!id) return;

    setSaveMessage("");
    setSaveError("");
    setLoadingWorkspace(true);

    try {
      const data = await apiGet(`/api/sequences/${id}/workspace/`);

      setSelectedSequenceId(String(data.id));
      setSearchParams({ workspace: String(data.id) });
      setName(data.name);
      setDescription(data.description || "");
      setSequenceType(data.sequence_type || "DNA");
      setSequence(data.sequence);
      setProjectId(data.project ? String(data.project) : "");
      setViewer(data.viewer || "both");
      setShowComplement(Boolean(data.show_complement));
      setRotateOnScroll(Boolean(data.rotate_on_scroll));
      setZoom(data.zoom ?? 50);

      setAnnotations(data.annotations || []);
      setPrimers(data.primers || []);
      setTranslations(data.translations || []);
      setHighlights(data.highlights || []);
      setEnzymes(data.enzymes || []);
      setBpColors(data.bp_colors || defaultBpColors);

      setSelection(null);
      setSearchResults([]);
      setSaveMessage(`Loaded "${data.name}".`);
    } catch (e) {
      setSaveError(e.message || String(e));
    } finally {
      setLoadingWorkspace(false);
    }
  }

  async function deleteSequenceWorkspace() {
    if (!selectedSequenceId) return;

    const confirmed = window.confirm(
      `Delete workspace "${name}"? This cannot be undone.`
    );

    if (!confirmed) return;

    setSaveMessage("");
    setSaveError("");
    setSaving(true);

    try {
      await apiDelete(`/api/sequences/${selectedSequenceId}/`);

      setSaveMessage(`Deleted "${name}".`);
      setSelectedSequenceId("");
      setSearchParams({});
      resetDemo();
      await loadSavedSequences();
    } catch (e) {
      setSaveError(e.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  function addAnnotation(e) {
    e.preventDefault();

    if (!isValidNamedRange(annotationForm, sequenceLength)) return;

    setAnnotations((prev) => [
      ...prev,
      clampRange(
        {
          ...annotationForm,
          direction: Number(annotationForm.direction),
        },
        sequenceLength
      ),
    ]);

    setAnnotationForm({
      name: "",
      start: "",
      end: "",
      direction: "1",
      color: "#22c55e",
    });
  }

  function addPrimer(e) {
    e.preventDefault();

    if (!isValidNamedRange(primerForm, sequenceLength)) return;

    setPrimers((prev) => [
      ...prev,
      clampRange(
        {
          ...primerForm,
          direction: Number(primerForm.direction),
        },
        sequenceLength
      ),
    ]);

    setPrimerForm({
      name: "",
      start: "",
      end: "",
      direction: "1",
      color: "#9333ea",
    });
  }

  function addTranslation(e) {
    e.preventDefault();

    if (!isValidNamedRange(translationForm, sequenceLength)) return;

    setTranslations((prev) => [
      ...prev,
      clampRange(
        {
          ...translationForm,
          direction: Number(translationForm.direction),
        },
        sequenceLength
      ),
    ]);

    setTranslationForm({
      name: "",
      start: "",
      end: "",
      direction: "1",
      color: "#16a34a",
    });
  }

  function addHighlight(e) {
    e.preventDefault();

    if (!isValidRange(highlightForm, sequenceLength)) return;

    setHighlights((prev) => [
      ...prev,
      clampRange(highlightForm, sequenceLength),
    ]);

    setHighlightForm({
      name: "Selected Highlight",
      start: "",
      end: "",
      color: "#fde047",
    });
  }

  function addEnzyme(e) {
    e.preventDefault();

    const value = enzymeName.trim();

    if (!value) return;

    setEnzymes((prev) => [...prev, value]);
    setEnzymeName("");
  }

  function addCustomEnzyme(e) {
    e.preventDefault();

    if (!customEnzyme.name.trim() || !customEnzyme.rseq.trim()) return;

    setEnzymes((prev) => [
      ...prev,
      {
        name: customEnzyme.name.trim(),
        rseq: cleanSequenceText(customEnzyme.rseq),
        fcut: Number(customEnzyme.fcut || 0),
        rcut: Number(customEnzyme.rcut || 0),
        color: customEnzyme.color,
      },
    ]);

    setCustomEnzyme({
      name: "",
      rseq: "",
      fcut: "0",
      rcut: "0",
      color: "#dbeafe",
    });
  }

  function removeItem(setter, index) {
    setter((prev) => prev.filter((_, i) => i !== index));
  }

  function updateBpColor(base, color) {
    setBpColors((prev) => ({
      ...prev,
      [base]: color,
    }));
  }

  return (
    <div className="w-100">
      <div className="page-header">
        <div>
          <h1 className="page-title">Sequences</h1>
          <p className="page-subtitle">
            Saveable SeqViz workspaces for annotations, primers, translations,
            enzyme sites, highlights, search, selected regions, and project
            linkage.
          </p>
        </div>

        <div className="inline-actions">
          <Badge bg="dark">{sequenceLength} bp</Badge>
          <Button variant="outline-dark" size="sm" onClick={resetDemo}>
            Reset Demo
          </Button>
        </div>
      </div>

      <Alert variant="info" className="border-0 shadow-sm">
        <strong>Tip:</strong> Drag across the sequence viewer to select a
        region, then use the selected region to create an annotation, primer,
        translation, or highlight without manually typing start/end coordinates.
      </Alert>

      <Row className="g-4 mb-4">
        <Col lg={4}>
          <Card className="app-card mb-4 border-0 shadow-sm">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">Saved Workspaces</h5>
                <Badge bg="dark">{savedSequences.length}</Badge>
              </div>

              {saveMessage && <Alert variant="success">{saveMessage}</Alert>}
              {saveError && <Alert variant="danger">{saveError}</Alert>}

              <div className="soft-card mb-3">
                <div className="feed-meta">Current Workspace</div>

                <div className="fw-semibold">
                  {name || "Untitled workspace"}
                </div>

                <div className="small text-muted">
                  {selectedSequenceId
                    ? `Saved workspace ID: ${selectedSequenceId}`
                    : "Not saved yet"}
                </div>

                <div className="small text-muted">
                  {selectedProject
                    ? `Linked project: ${selectedProject.code} — ${selectedProject.name}`
                    : "No linked project"}
                </div>
              </div>

              <Form.Group className="mb-3">
                <Form.Label>Load saved workspace</Form.Label>
                <Form.Select
                  value={selectedSequenceId}
                  disabled={loadingWorkspace}
                  onChange={(e) => {
                    const id = e.target.value;
                    setSelectedSequenceId(id);

                    if (id) {
                      loadSequenceWorkspace(id);
                    } else {
                      setSearchParams({});
                    }
                  }}
                >
                  <option value="">New unsaved workspace</option>

                  {savedSequences.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name} — {item.sequence_type} —{" "}
                      {item.sequence.length} bp
                    </option>
                  ))}
                </Form.Select>
              </Form.Group>

              <div className="d-grid gap-2">
                <Button
                  variant="dark"
                  onClick={saveSequenceWorkspace}
                  disabled={saving || !name || !cleanSequence}
                >
                  {saving
                    ? "Saving..."
                    : selectedSequenceId
                    ? "Update Workspace"
                    : "Save Workspace"}
                </Button>

                {selectedSequenceId && (
                  <Button
                    variant="outline-danger"
                    onClick={deleteSequenceWorkspace}
                    disabled={saving}
                  >
                    Delete Workspace
                  </Button>
                )}

                <Button variant="outline-dark" onClick={startNewWorkspace}>
                  Start New Workspace
                </Button>

                <Button variant="outline-secondary" onClick={loadSavedSequences}>
                  Refresh Saved List
                </Button>
              </div>
            </Card.Body>
          </Card>

          <Card className="app-card mb-4 border-0 shadow-sm">
            <Card.Body>
              <h5 className="section-title">Sequence Setup</h5>

              <Form.Group className="mb-3">
                <Form.Label>Workspace Name</Form.Label>
                <Form.Control
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Example: GFP construct review"
                />
                <div className="form-text">
                  This name is used in the saved workspace dropdown.
                </div>
              </Form.Group>

              <Form.Group className="mb-3">
                <Form.Label>Linked Project</Form.Label>
                <Form.Select
                  value={projectId}
                  onChange={(e) => setProjectId(e.target.value)}
                >
                  <option value="">No linked project</option>

                  {projects.map((project) => (
                    <option key={project.id} value={project.id}>
                      {project.code} — {project.name}
                    </option>
                  ))}
                </Form.Select>
                <div className="form-text">
                  Optional: link this sequence workspace to a project.
                </div>
              </Form.Group>

              <Form.Group className="mb-3">
                <Form.Label>Description</Form.Label>
                <Form.Control
                  as="textarea"
                  rows={2}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </Form.Group>

              <Form.Group className="mb-3">
                <Form.Label>Sequence Type</Form.Label>
                <Form.Select
                  value={sequenceType}
                  onChange={(e) => setSequenceType(e.target.value)}
                >
                  <option value="DNA">DNA</option>
                  <option value="RNA">RNA</option>
                  <option value="PROTEIN">Protein</option>
                </Form.Select>
              </Form.Group>

              <Form.Group className="mb-3">
                <Form.Label>Viewer Mode</Form.Label>
                <Form.Select
                  value={viewer}
                  onChange={(e) => setViewer(e.target.value)}
                >
                  <option value="both">Circular + Linear</option>
                  <option value="both_flip">Linear + Circular</option>
                  <option value="circular">Circular Only</option>
                  <option value="linear">Linear Only</option>
                </Form.Select>
              </Form.Group>

              <Form.Group className="mb-3">
                <Form.Label>Linear Zoom: {zoom}</Form.Label>
                <Form.Range
                  min={0}
                  max={100}
                  value={zoom}
                  onChange={(e) => setZoom(Number(e.target.value))}
                />
              </Form.Group>

              <div className="d-grid gap-2 mb-3">
                <Form.Check
                  type="switch"
                  label="Show complement sequence"
                  checked={showComplement}
                  onChange={(e) => setShowComplement(e.target.checked)}
                />

                <Form.Check
                  type="switch"
                  label="Rotate circular viewer on scroll"
                  checked={rotateOnScroll}
                  onChange={(e) => setRotateOnScroll(e.target.checked)}
                />
              </div>

              <Form.Group>
                <Form.Label>Sequence</Form.Label>
                <Form.Control
                  as="textarea"
                  rows={10}
                  value={sequence}
                  onChange={(e) => setSequence(e.target.value)}
                />
              </Form.Group>
            </Card.Body>
          </Card>

          <Card className="app-card mb-4 border-0 shadow-sm">
            <Card.Body>
              <h5 className="section-title">Search</h5>

              <Row className="g-2">
                <Col md={8}>
                  <Form.Control
                    placeholder="Search query, e.g. ATG"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                  />
                </Col>

                <Col md={4}>
                  <Form.Control
                    type="number"
                    min={0}
                    placeholder="Mismatch"
                    value={searchMismatch}
                    onChange={(e) => setSearchMismatch(e.target.value)}
                  />
                </Col>
              </Row>

              <div className="feed-meta mt-3">
                Search results: {searchResults.length}
              </div>
            </Card.Body>
          </Card>

          <Card className="app-card border-0 shadow-sm">
            <Card.Body>
              <div className="d-flex justify-content-between align-items-start gap-3 mb-3">
                <div>
                  <h5 className="section-title mb-1">Selected Region</h5>
                  <div className="feed-meta">
                    Drag on the viewer, then apply the region to a feature.
                  </div>
                </div>

                {hasSelectionRange() && (
                  <Badge bg="dark">
                    {selection.start}–{selection.end}
                  </Badge>
                )}
              </div>

              <SelectionDetails selection={selection} />

              <div className="d-grid gap-2 mt-3">
                <Button
                  variant="outline-primary"
                  size="sm"
                  disabled={!hasSelectionRange()}
                  onClick={useSelectionForAnnotation}
                >
                  Use for Annotation
                </Button>

                <Button
                  variant="outline-secondary"
                  size="sm"
                  disabled={!hasSelectionRange()}
                  onClick={useSelectionForPrimer}
                >
                  Use for Primer
                </Button>

                <Button
                  variant="outline-success"
                  size="sm"
                  disabled={!hasSelectionRange()}
                  onClick={useSelectionForTranslation}
                >
                  Use for Translation
                </Button>

                <Button
                  variant="outline-warning"
                  size="sm"
                  disabled={!hasSelectionRange()}
                  onClick={useSelectionForHighlight}
                >
                  Use for Highlight
                </Button>
              </div>
            </Card.Body>
          </Card>
        </Col>

        <Col lg={8}>
          <Card className="app-card h-100 border-0 shadow-sm">
            <Card.Body>
              <div className="d-flex justify-content-between align-items-start flex-wrap gap-3 mb-3">
                <div>
                  <h5 className="section-title mb-1">Sequence Viewer</h5>
                  <div className="feed-meta">
                    Select regions directly on the viewer to create features
                    faster.
                  </div>
                </div>

                <div className="d-flex flex-wrap gap-2">
                  <Badge bg="dark">{sequenceLength} bp</Badge>
                  <Badge bg="primary">{annotations.length} annotations</Badge>
                  <Badge bg="secondary">{primers.length} primers</Badge>
                  <Badge bg="success">{translations.length} translations</Badge>
                  <Badge bg="warning" text="dark">
                    {highlights.length} highlights
                  </Badge>
                  <Badge bg="info" text="dark">
                    {enzymes.length} enzymes
                  </Badge>
                </div>
              </div>

              {sequenceLength === 0 ? (
                <Alert variant="light" className="mb-0">
                  Paste a DNA, RNA, or protein sequence to view it.
                </Alert>
              ) : (
                <div
                  style={{
                    height: "780px",
                    width: "100%",
                    border: "1px solid #e5e7eb",
                    borderRadius: "18px",
                    overflow: "hidden",
                    background: "#ffffff",
                  }}
                >
                  <SeqViz
                    name={name}
                    seq={cleanSequence}
                    viewer={viewer}
                    annotations={annotations}
                    primers={primers}
                    translations={translations}
                    highlights={highlights}
                    enzymes={enzymes}
                    search={search}
                    onSearch={(results) => setSearchResults(results || [])}
                    onSelection={(selected) => setSelection(selected)}
                    showComplement={showComplement}
                    rotateOnScroll={rotateOnScroll}
                    zoom={{ linear: zoom }}
                    bpColors={bpColors}
                    disableExternalFonts={true}
                    style={{
                      height: "100%",
                      width: "100%",
                    }}
                  />
                </div>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="g-4 mb-4">
        <Col lg={6}>
          <Card className="app-card h-100 border-0 shadow-sm">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">Annotations</h5>
                <Badge bg="primary">{annotations.length}</Badge>
              </div>

              <Form onSubmit={addAnnotation}>
                <Row className="g-2">
                  <Col md={4}>
                    <Form.Control
                      placeholder="Name"
                      value={annotationForm.name}
                      onChange={(e) =>
                        setAnnotationForm({
                          ...annotationForm,
                          name: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={2}>
                    <Form.Control
                      type="number"
                      placeholder="Start"
                      value={annotationForm.start}
                      onChange={(e) =>
                        setAnnotationForm({
                          ...annotationForm,
                          start: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={2}>
                    <Form.Control
                      type="number"
                      placeholder="End"
                      value={annotationForm.end}
                      onChange={(e) =>
                        setAnnotationForm({
                          ...annotationForm,
                          end: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={2}>
                    <Form.Select
                      value={annotationForm.direction}
                      onChange={(e) =>
                        setAnnotationForm({
                          ...annotationForm,
                          direction: e.target.value,
                        })
                      }
                    >
                      <option value="1">FWD</option>
                      <option value="-1">REV</option>
                    </Form.Select>
                  </Col>

                  <Col md={1}>
                    <Form.Control
                      type="color"
                      value={annotationForm.color}
                      onChange={(e) =>
                        setAnnotationForm({
                          ...annotationForm,
                          color: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={1}>
                    <Button type="submit" variant="dark" className="w-100">
                      Add
                    </Button>
                  </Col>
                </Row>
              </Form>

              <FeatureTable
                items={annotations}
                type="annotation"
                onRemove={(index) => removeItem(setAnnotations, index)}
              />
            </Card.Body>
          </Card>
        </Col>

        <Col lg={6}>
          <Card className="app-card h-100 border-0 shadow-sm">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">Primers</h5>
                <Badge bg="secondary">{primers.length}</Badge>
              </div>

              <Form onSubmit={addPrimer}>
                <Row className="g-2">
                  <Col md={4}>
                    <Form.Control
                      placeholder="Name"
                      value={primerForm.name}
                      onChange={(e) =>
                        setPrimerForm({
                          ...primerForm,
                          name: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={2}>
                    <Form.Control
                      type="number"
                      placeholder="Start"
                      value={primerForm.start}
                      onChange={(e) =>
                        setPrimerForm({
                          ...primerForm,
                          start: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={2}>
                    <Form.Control
                      type="number"
                      placeholder="End"
                      value={primerForm.end}
                      onChange={(e) =>
                        setPrimerForm({
                          ...primerForm,
                          end: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={2}>
                    <Form.Select
                      value={primerForm.direction}
                      onChange={(e) =>
                        setPrimerForm({
                          ...primerForm,
                          direction: e.target.value,
                        })
                      }
                    >
                      <option value="1">FWD</option>
                      <option value="-1">REV</option>
                    </Form.Select>
                  </Col>

                  <Col md={1}>
                    <Form.Control
                      type="color"
                      value={primerForm.color}
                      onChange={(e) =>
                        setPrimerForm({
                          ...primerForm,
                          color: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={1}>
                    <Button type="submit" variant="dark" className="w-100">
                      Add
                    </Button>
                  </Col>
                </Row>
              </Form>

              <FeatureTable
                items={primers}
                type="primer"
                onRemove={(index) => removeItem(setPrimers, index)}
              />
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="g-4 mb-4">
        <Col lg={6}>
          <Card className="app-card h-100 border-0 shadow-sm">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">Translations</h5>
                <Badge bg="success">{translations.length}</Badge>
              </div>

              <Form onSubmit={addTranslation}>
                <Row className="g-2">
                  <Col md={4}>
                    <Form.Control
                      placeholder="Name"
                      value={translationForm.name}
                      onChange={(e) =>
                        setTranslationForm({
                          ...translationForm,
                          name: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={2}>
                    <Form.Control
                      type="number"
                      placeholder="Start"
                      value={translationForm.start}
                      onChange={(e) =>
                        setTranslationForm({
                          ...translationForm,
                          start: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={2}>
                    <Form.Control
                      type="number"
                      placeholder="End"
                      value={translationForm.end}
                      onChange={(e) =>
                        setTranslationForm({
                          ...translationForm,
                          end: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={2}>
                    <Form.Select
                      value={translationForm.direction}
                      onChange={(e) =>
                        setTranslationForm({
                          ...translationForm,
                          direction: e.target.value,
                        })
                      }
                    >
                      <option value="1">FWD</option>
                      <option value="-1">REV</option>
                    </Form.Select>
                  </Col>

                  <Col md={1}>
                    <Form.Control
                      type="color"
                      value={translationForm.color}
                      onChange={(e) =>
                        setTranslationForm({
                          ...translationForm,
                          color: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={1}>
                    <Button type="submit" variant="dark" className="w-100">
                      Add
                    </Button>
                  </Col>
                </Row>
              </Form>

              <FeatureTable
                items={translations}
                type="translation"
                onRemove={(index) => removeItem(setTranslations, index)}
              />
            </Card.Body>
          </Card>
        </Col>

        <Col lg={6}>
          <Card className="app-card h-100 border-0 shadow-sm">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">Highlights</h5>
                <Badge bg="warning" text="dark">
                  {highlights.length}
                </Badge>
              </div>

              <Form onSubmit={addHighlight}>
                <Row className="g-2">
                  <Col md={4}>
                    <Form.Control
                      type="number"
                      placeholder="Start"
                      value={highlightForm.start}
                      onChange={(e) =>
                        setHighlightForm({
                          ...highlightForm,
                          start: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={4}>
                    <Form.Control
                      type="number"
                      placeholder="End"
                      value={highlightForm.end}
                      onChange={(e) =>
                        setHighlightForm({
                          ...highlightForm,
                          end: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={2}>
                    <Form.Control
                      type="color"
                      value={highlightForm.color}
                      onChange={(e) =>
                        setHighlightForm({
                          ...highlightForm,
                          color: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={2}>
                    <Button type="submit" variant="dark" className="w-100">
                      Add
                    </Button>
                  </Col>
                </Row>
              </Form>

              {highlights.length === 0 ? (
                <div className="empty-state mt-3">No highlights yet.</div>
              ) : (
                <Table responsive hover className="app-table mt-3">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Range</th>
                      <th>Color</th>
                      <th></th>
                    </tr>
                  </thead>

                  <tbody>
                    {highlights.map((item, index) => (
                      <tr key={`${item.start}-${item.end}-${index}`}>
                        <td>{item.name || "-"}</td>
                        <td>{formatRange(item)}</td>
                        <td>
                          <ColorSwatch color={item.color} />
                          {item.color}
                        </td>
                        <td>
                          <Button
                            variant="outline-danger"
                            size="sm"
                            onClick={() => removeItem(setHighlights, index)}
                          >
                            Remove
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </Col>
      </Row>

      <Row className="g-4 mb-4">
        <Col lg={6}>
          <Card className="app-card h-100 border-0 shadow-sm">
            <Card.Body>
              <div className="toolbar-row mb-3">
                <h5 className="section-title mb-0">Restriction Enzymes</h5>
                <Badge bg="info" text="dark">
                  {enzymes.length}
                </Badge>
              </div>

              <Form onSubmit={addEnzyme} className="mb-3">
                <Row className="g-2">
                  <Col md={9}>
                    <Form.Control
                      placeholder="Enzyme name, e.g. EcoRI"
                      value={enzymeName}
                      onChange={(e) => setEnzymeName(e.target.value)}
                    />
                  </Col>

                  <Col md={3}>
                    <Button type="submit" variant="dark" className="w-100">
                      Add
                    </Button>
                  </Col>
                </Row>
              </Form>

              <Form onSubmit={addCustomEnzyme}>
                <div className="feed-meta mb-2">Custom enzyme</div>

                <Row className="g-2">
                  <Col md={3}>
                    <Form.Control
                      placeholder="Name"
                      value={customEnzyme.name}
                      onChange={(e) =>
                        setCustomEnzyme({
                          ...customEnzyme,
                          name: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={3}>
                    <Form.Control
                      placeholder="Recognition seq"
                      value={customEnzyme.rseq}
                      onChange={(e) =>
                        setCustomEnzyme({
                          ...customEnzyme,
                          rseq: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={2}>
                    <Form.Control
                      type="number"
                      placeholder="fcut"
                      value={customEnzyme.fcut}
                      onChange={(e) =>
                        setCustomEnzyme({
                          ...customEnzyme,
                          fcut: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={2}>
                    <Form.Control
                      type="number"
                      placeholder="rcut"
                      value={customEnzyme.rcut}
                      onChange={(e) =>
                        setCustomEnzyme({
                          ...customEnzyme,
                          rcut: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={1}>
                    <Form.Control
                      type="color"
                      value={customEnzyme.color}
                      onChange={(e) =>
                        setCustomEnzyme({
                          ...customEnzyme,
                          color: e.target.value,
                        })
                      }
                    />
                  </Col>

                  <Col md={1}>
                    <Button type="submit" variant="dark" className="w-100">
                      Add
                    </Button>
                  </Col>
                </Row>
              </Form>

              {enzymes.length === 0 ? (
                <div className="empty-state mt-3">No enzymes selected.</div>
              ) : (
                <Table responsive hover className="app-table mt-3">
                  <thead>
                    <tr>
                      <th>Enzyme</th>
                      <th>Type</th>
                      <th></th>
                    </tr>
                  </thead>

                  <tbody>
                    {enzymes.map((enzyme, index) => (
                      <tr
                        key={`${
                          typeof enzyme === "string" ? enzyme : enzyme.name
                        }-${index}`}
                      >
                        <td>
                          {typeof enzyme === "string" ? enzyme : enzyme.name}
                        </td>
                        <td>
                          {typeof enzyme === "string"
                            ? "Built-in"
                            : enzyme.rseq}
                        </td>
                        <td>
                          <Button
                            variant="outline-danger"
                            size="sm"
                            onClick={() => removeItem(setEnzymes, index)}
                          >
                            Remove
                          </Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              )}
            </Card.Body>
          </Card>
        </Col>

        <Col lg={6}>
          <Card className="app-card h-100 border-0 shadow-sm">
            <Card.Body>
              <h5 className="section-title">Base Pair Colors</h5>

              <Row className="g-3">
                {["A", "T", "G", "C"].map((base) => (
                  <Col md={3} key={base}>
                    <Form.Label>{base}</Form.Label>
                    <Form.Control
                      type="color"
                      value={bpColors[base]}
                      onChange={(e) => updateBpColor(base, e.target.value)}
                    />
                  </Col>
                ))}
              </Row>

              <JsonPreview
                title="Workspace JSON Preview"
                data={{
                  selectedSequenceId,
                  projectId,
                  linkedProject: selectedProject
                    ? `${selectedProject.code} — ${selectedProject.name}`
                    : null,
                  name,
                  description,
                  sequenceType,
                  sequenceLength,
                  viewer,
                  showComplement,
                  rotateOnScroll,
                  zoom,
                  annotations,
                  primers,
                  translations,
                  highlights,
                  enzymes,
                  search,
                  bpColors,
                }}
              />
            </Card.Body>
          </Card>
        </Col>
      </Row>
    </div>
  );
}