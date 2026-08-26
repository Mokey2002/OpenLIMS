import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  Badge,
  Button,
  Card,
  Col,
  Form,
  Row,
  Spinner,
  Table,
} from "react-bootstrap";
import { apiGet, apiGetAll, apiPost } from "../api";
import { canWrite, isAdmin, readOnlyMessage } from "../authz";

const plasmidSchema = JSON.stringify(
  {
    type: "object",
    required: ["backbone"],
    properties: {
      backbone: { type: "string" },
      resistance: { type: "string" },
      host: { type: "string" },
    },
  },
  null,
  2
);

const emptyRecord = {
  schema: "",
  name: "",
  catalog_number: "",
  project: "",
  visibility: "PROJECT",
  aliases: "",
  tags: "",
  sequence_revision: "",
  data: "{}",
};

function statusVariant(status) {
  return {
    DRAFT: "secondary",
    IN_REVIEW: "warning",
    REGISTERED: "success",
    RETIRED: "dark",
  }[status] || "secondary";
}

function parseJson(value, label) {
  try {
    const parsed = JSON.parse(value || "{}");
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
      throw new Error();
    }
    return parsed;
  } catch {
    throw new Error(`${label} must be a valid JSON object.`);
  }
}

export default function Registry() {
  const [me, setMe] = useState(null);
  const [schemas, setSchemas] = useState([]);
  const [records, setRecords] = useState([]);
  const [projects, setProjects] = useState([]);
  const [sequences, setSequences] = useState([]);
  const [samples, setSamples] = useState([]);
  const [lots, setLots] = useState([]);
  const [selected, setSelected] = useState(null);
  const [recordForm, setRecordForm] = useState(emptyRecord);
  const [schemaForm, setSchemaForm] = useState({
    code: "plasmid",
    name: "Plasmid",
    entity_type: "plasmid",
    id_prefix: "PLS",
    schema: plasmidSchema,
    matching_fields: "backbone,resistance",
  });
  const [versionForm, setVersionForm] = useState({
    data: "{}",
    sequence_revision: "",
    change_summary: "",
  });
  const [linkForm, setLinkForm] = useState({ target_type: "sample", target_public_id: "" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [duplicates, setDuplicates] = useState([]);

  const userCanWrite = canWrite(me);
  const userIsAdmin = isAdmin(me);
  const linkTargets = linkForm.target_type === "sample" ? samples : lots;

  const selectedSequence = useMemo(
    () => sequences.find((item) => String(item.current_revision) === String(recordForm.sequence_revision)),
    [sequences, recordForm.sequence_revision]
  );

  useEffect(() => {
    load();
    // Registry data is loaded once when the workspace mounts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function load(selectId = null) {
    setError("");
    try {
      const [meData, schemaData, recordData, projectData, sequenceData, sampleData, lotData] =
        await Promise.all([
          apiGet("/api/me/"),
          apiGetAll("/api/registry-schemas/?active=true"),
          apiGetAll("/api/registry-records/"),
          apiGetAll("/api/projects/"),
          apiGetAll("/api/sequences/"),
          apiGetAll("/api/samples/"),
          apiGetAll("/api/inventory-lots/"),
        ]);
      setMe(meData);
      setSchemas(schemaData);
      setRecords(recordData);
      setProjects(projectData);
      setSequences(sequenceData);
      setSamples(sampleData);
      setLots(lotData);
      const selectedId = selectId || selected?.id;
      setSelected(recordData.find((item) => item.id === selectedId) || null);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }

  function updateRecord(field, value) {
    setRecordForm((current) => ({ ...current, [field]: value }));
  }

  async function createSchema(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await apiPost("/api/registry-schemas/", {
        ...schemaForm,
        version: 1,
        schema: parseJson(schemaForm.schema, "Schema"),
        matching_fields: schemaForm.matching_fields
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean),
      });
      setMessage("Registry type created.");
      await load();
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  async function createRecord(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    setDuplicates([]);
    try {
      const data = parseJson(recordForm.data, "Registry data");
      const aliases = recordForm.aliases.split(",").map((item) => item.trim()).filter(Boolean);
      const duplicateResult = await apiPost("/api/registry-records/duplicate-check/", {
        schema: Number(recordForm.schema),
        catalog_number: recordForm.catalog_number,
        aliases,
        sequence_revision: recordForm.sequence_revision || null,
        data,
      });
      if (duplicateResult.duplicate) {
        setDuplicates(duplicateResult.matches);
        throw new Error("Potential duplicates found. Review them before creating the record.");
      }
      const created = await apiPost("/api/registry-records/", {
        schema: Number(recordForm.schema),
        name: recordForm.name,
        catalog_number: recordForm.catalog_number,
        project: recordForm.project ? Number(recordForm.project) : null,
        visibility: recordForm.visibility,
        aliases: aliases.map((alias) => ({ alias, alias_type: "laboratory" })),
        tags: recordForm.tags.split(",").map((item) => item.trim()).filter(Boolean),
        sequence_revision: recordForm.sequence_revision ? Number(recordForm.sequence_revision) : null,
        data,
      });
      setRecordForm(emptyRecord);
      setMessage("Registry record created as a draft.");
      await load(created.id);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  async function createVersion(e) {
    e.preventDefault();
    if (!selected) return;
    setSaving(true);
    setError("");
    try {
      await apiPost(`/api/registry-records/${selected.id}/new-version/`, {
        data: parseJson(versionForm.data, "Registry data"),
        sequence_revision: versionForm.sequence_revision
          ? Number(versionForm.sequence_revision)
          : null,
        change_summary: versionForm.change_summary,
      });
      setMessage("Immutable record version created.");
      await load(selected.id);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  async function lifecycle(path, body = {}) {
    if (!selected) return;
    setSaving(true);
    setError("");
    try {
      await apiPost(`/api/registry-records/${selected.id}/${path}/`, body);
      setMessage("Registry lifecycle updated.");
      await load(selected.id);
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  async function createLink(e) {
    e.preventDefault();
    if (!selected) return;
    setSaving(true);
    setError("");
    try {
      await apiPost("/api/entity-links/", {
        source_type: "registry_record",
        source_public_id: selected.public_id,
        target_type: linkForm.target_type,
        target_public_id: linkForm.target_public_id,
        relation_type: linkForm.target_type === "sample" ? "represented_by" : "stored_as",
      });
      setMessage("Registry link created.");
      setLinkForm((current) => ({ ...current, target_public_id: "" }));
    } catch (e) {
      setError(e.message || String(e));
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <Spinner animation="border" />;

  return (
    <div>
      <div className="d-flex justify-content-between align-items-start mb-4">
        <div>
          <h2>Biological Registry</h2>
          <p className="text-muted mb-0">
            Register versioned biological materials, sequences, aliases, relationships, and physical links.
          </p>
        </div>
        <Button variant="outline-secondary" onClick={() => load()}>Refresh</Button>
      </div>

      {message && <Alert variant="success" dismissible onClose={() => setMessage("")}>{message}</Alert>}
      {error && <Alert variant="danger" dismissible onClose={() => setError("")}>{error}</Alert>}
      {!userCanWrite && <Alert variant="info">{readOnlyMessage(me)}</Alert>}
      {duplicates.length > 0 && (
        <Alert variant="warning">
          <strong>Potential duplicates</strong>
          <ul className="mb-0 mt-2">
            {duplicates.map((item) => (
              <li key={item.public_id}>{item.registry_id} — {item.name} ({item.reasons.join(", ")})</li>
            ))}
          </ul>
        </Alert>
      )}

      {userIsAdmin && (
        <Card className="app-card mb-4">
          <Card.Body>
            <h5>Configure Registry Type</h5>
            <Form onSubmit={createSchema}>
              <Row className="g-3">
                {[
                  ["code", "Schema code"], ["name", "Type name"],
                  ["entity_type", "Entity type"], ["id_prefix", "Registry ID prefix"],
                ].map(([field, label]) => (
                  <Col md={3} key={field}>
                    <Form.Label>{label}</Form.Label>
                    <Form.Control value={schemaForm[field]} onChange={(e) => setSchemaForm({ ...schemaForm, [field]: e.target.value })} required />
                  </Col>
                ))}
                <Col md={8}>
                  <Form.Label>Versioned JSON schema</Form.Label>
                  <Form.Control as="textarea" rows={7} value={schemaForm.schema} onChange={(e) => setSchemaForm({ ...schemaForm, schema: e.target.value })} />
                </Col>
                <Col md={4}>
                  <Form.Label>Duplicate matching fields</Form.Label>
                  <Form.Control value={schemaForm.matching_fields} onChange={(e) => setSchemaForm({ ...schemaForm, matching_fields: e.target.value })} />
                  <Form.Text>Comma-separated schema fields.</Form.Text>
                </Col>
              </Row>
              <Button className="mt-3" type="submit" disabled={saving}>Create Registry Type</Button>
            </Form>
          </Card.Body>
        </Card>
      )}

      <Row className="g-4">
        <Col xl={5}>
          <Card className="app-card mb-4">
            <Card.Body>
              <h5>Create Draft Record</h5>
              <Form onSubmit={createRecord}>
                <Form.Group className="mb-3">
                  <Form.Label>Registry type</Form.Label>
                  <Form.Select value={recordForm.schema} onChange={(e) => updateRecord("schema", e.target.value)} required>
                    <option value="">Choose type</option>
                    {schemas.map((item) => <option key={item.id} value={item.id}>{item.name} v{item.version}</option>)}
                  </Form.Select>
                </Form.Group>
                <Row className="g-3">
                  <Col md={7}><Form.Label>Name</Form.Label><Form.Control value={recordForm.name} onChange={(e) => updateRecord("name", e.target.value)} required /></Col>
                  <Col md={5}><Form.Label>Catalog number</Form.Label><Form.Control value={recordForm.catalog_number} onChange={(e) => updateRecord("catalog_number", e.target.value)} /></Col>
                  <Col md={6}><Form.Label>Project</Form.Label><Form.Select value={recordForm.project} onChange={(e) => updateRecord("project", e.target.value)}><option value="">Private / no project</option>{projects.map((item) => <option key={item.id} value={item.id}>{item.code}</option>)}</Form.Select></Col>
                  <Col md={6}><Form.Label>Visibility</Form.Label><Form.Select value={recordForm.visibility} onChange={(e) => updateRecord("visibility", e.target.value)}><option value="PROJECT">Project</option><option value="PRIVATE">Owner only</option><option value="INSTITUTION">Institution</option></Form.Select></Col>
                  <Col md={6}><Form.Label>Aliases</Form.Label><Form.Control value={recordForm.aliases} onChange={(e) => updateRecord("aliases", e.target.value)} placeholder="pABC, vector-42" /></Col>
                  <Col md={6}><Form.Label>Tags</Form.Label><Form.Control value={recordForm.tags} onChange={(e) => updateRecord("tags", e.target.value)} placeholder="cloning, validated" /></Col>
                  <Col md={12}><Form.Label>Sequence revision</Form.Label><Form.Select value={recordForm.sequence_revision} onChange={(e) => updateRecord("sequence_revision", e.target.value)}><option value="">No sequence</option>{sequences.filter((item) => item.current_revision).map((item) => <option key={item.id} value={item.current_revision}>{item.name} — revision {item.revisions?.[0]?.revision || "current"}</option>)}</Form.Select>{selectedSequence && <Form.Text>{selectedSequence.topology} {selectedSequence.sequence_type}, {selectedSequence.sequence.length} bases/residues</Form.Text>}</Col>
                  <Col md={12}><Form.Label>Registry data (JSON)</Form.Label><Form.Control as="textarea" rows={6} value={recordForm.data} onChange={(e) => updateRecord("data", e.target.value)} /></Col>
                </Row>
                <Button className="mt-3" type="submit" disabled={!userCanWrite || saving}>Check Duplicates and Create Draft</Button>
              </Form>
            </Card.Body>
          </Card>
        </Col>

        <Col xl={7}>
          <Card className="app-card mb-4">
            <Card.Body>
              <h5>Registry Records</h5>
              <Table responsive hover className="app-table">
                <thead><tr><th>Registry ID</th><th>Name</th><th>Type</th><th>Status</th><th>Version</th></tr></thead>
                <tbody>
                  {records.map((item) => (
                    <tr key={item.id} onClick={() => { setSelected(item); setVersionForm({ data: JSON.stringify(item.versions?.[0]?.data || {}, null, 2), sequence_revision: item.versions?.[0]?.sequence_revision || "", change_summary: "" }); }} style={{ cursor: "pointer" }}>
                      <td>{item.registry_id}</td><td>{item.name}</td><td>{item.entity_type}</td>
                      <td><Badge bg={statusVariant(item.lifecycle_status)}>{item.lifecycle_status}</Badge></td>
                      <td>{item.versions?.[0]?.version || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              {records.length === 0 && <div className="empty-state">No registry records yet.</div>}
            </Card.Body>
          </Card>

          {selected && (
            <Card className="app-card">
              <Card.Body>
                <div className="d-flex justify-content-between align-items-start">
                  <div><h5>{selected.registry_id} — {selected.name}</h5><div className="text-muted">Owner: {selected.owner_username} · Project: {selected.project_code || "Private"}</div></div>
                  <Badge bg={statusVariant(selected.lifecycle_status)}>{selected.lifecycle_status}</Badge>
                </div>
                <div className="inline-actions my-3">
                  {selected.lifecycle_status === "DRAFT" && <Button size="sm" onClick={() => lifecycle("submit-review")}>Submit for Review</Button>}
                  {userIsAdmin && selected.lifecycle_status === "IN_REVIEW" && <><Button size="sm" variant="success" onClick={() => lifecycle("review", { decision: "APPROVED" })}>Approve Registration</Button><Button size="sm" variant="outline-danger" onClick={() => lifecycle("review", { decision: "REJECTED" })}>Reject</Button></>}
                  {selected.lifecycle_status === "REGISTERED" && <Button size="sm" variant="outline-dark" onClick={() => lifecycle("retire", { reason: "Retired from Registry UI" })}>Retire Record</Button>}
                </div>

                <Form onSubmit={createVersion} className="soft-card mb-3">
                  <h6>Create New Immutable Version</h6>
                  <Form.Label>Change summary</Form.Label><Form.Control className="mb-2" value={versionForm.change_summary} onChange={(e) => setVersionForm({ ...versionForm, change_summary: e.target.value })} required />
                  <Form.Label>Registry data (JSON)</Form.Label><Form.Control as="textarea" rows={5} className="mb-2" value={versionForm.data} onChange={(e) => setVersionForm({ ...versionForm, data: e.target.value })} />
                  <Form.Label>Sequence revision</Form.Label><Form.Select value={versionForm.sequence_revision} onChange={(e) => setVersionForm({ ...versionForm, sequence_revision: e.target.value })}><option value="">Keep current sequence</option>{sequences.flatMap((item) => (item.revisions || []).map((revision) => <option key={`${item.id}-${revision.id}`} value={revision.id}>{item.name} — r{revision.revision}</option>))}</Form.Select>
                  <Button className="mt-2" size="sm" type="submit" disabled={!userCanWrite || saving}>Create Version</Button>
                </Form>

                <Form onSubmit={createLink} className="soft-card mb-3">
                  <h6>Link Physical Material</h6>
                  <Row className="g-2"><Col md={4}><Form.Select value={linkForm.target_type} onChange={(e) => setLinkForm({ target_type: e.target.value, target_public_id: "" })}><option value="sample">Sample</option><option value="inventory_lot">Inventory lot</option></Form.Select></Col><Col md={6}><Form.Select value={linkForm.target_public_id} onChange={(e) => setLinkForm({ ...linkForm, target_public_id: e.target.value })} required><option value="">Choose record</option>{linkTargets.map((item) => <option key={item.public_id} value={item.public_id}>{item.sample_id || item.lot_code}</option>)}</Form.Select></Col><Col md={2}><Button type="submit" disabled={!userCanWrite || saving}>Link</Button></Col></Row>
                </Form>

                <h6>Version History</h6>
                <Table size="sm" responsive><thead><tr><th>Version</th><th>Summary</th><th>Sequence checksum</th><th>Created</th></tr></thead><tbody>{(selected.versions || []).map((version) => <tr key={version.public_id}><td>{version.version}</td><td>{version.change_summary || "-"}</td><td className="font-monospace small">{version.sequence_checksum ? `${version.sequence_checksum.slice(0, 12)}…` : "-"}</td><td>{new Date(version.created_at).toLocaleString()}</td></tr>)}</tbody></Table>
              </Card.Body>
            </Card>
          )}
        </Col>
      </Row>
    </div>
  );
}
