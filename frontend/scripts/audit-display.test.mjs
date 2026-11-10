import test from "node:test";
import assert from "node:assert/strict";
import { auditAction, auditDescription, auditReason, auditRecord } from "../src/utils/auditDisplay.js";

test("old experiment snapshots show the title and distinguish real revisions", () => {
  const event = { entity_type: "experiment", entity_id: "3c834c15-53d3-4e65-8ffe-67314e7d28e0",
    action: "EXPERIMENT_REVISION_CREATED", payload: { entity: { label: "Protein stability study" },
      before: { revision: 3 }, after: { revision: 4 }, details: { changes: { blocks_modified: 1, links_added: 2 } } } };
  assert.equal(auditRecord(event), "Protein stability study");
  assert.equal(auditAction(event), "Experiment saved");
  assert.equal(auditDescription(event), "Revision 3 → 4; 1 block modified, 2 links added");
  assert.equal(auditDescription(event, value => value, "es"), "Revisión 3 → 4; 1 bloque modificado, 2 enlaces añadidos");
});

test("legacy inventory labels use recorded names and barcodes instead of database IDs", () => {
  assert.equal(auditRecord({ entity_type: "Container", entity_id: "13", payload: { container_id: "PROTEIN-BOX-A" } }), "PROTEIN-BOX-A");
  assert.equal(auditRecord({ entity_type: "Location", entity_id: "18", payload: { before: { name: "Protein freezer" } } }), "Protein freezer");
});

test("unresolvable or malformed historical records remain readable without inventing a name", () => {
  for (const payload of [null, [], "old data", { entity: [], after: [], reason: {} }]) {
    const event = { entity_type: "experiment", entity_id: "unresolved-id", action: "EXPERIMENT_REVISION_CREATED", payload };
    assert.equal(auditRecord(event), "Experiment (name unavailable)");
    assert.equal(auditReason(event), "");
    assert.doesNotMatch(auditDescription(event), /unresolved-id|undefined|\[object Object\]/);
  }
});

test("the legacy technical action UUID is kept out of the displayed reason", () => {
  assert.equal(auditReason({ payload: { reason: "Assistant source draft / action 3c834c15-53d3-4e65-8ffe-67314e7d28e0" } }), "Assistant source draft");
  assert.equal(auditReason({ payload: { reason: "Repeat QC after checking control S-100" } }), "Repeat QC after checking control S-100");
});

test("assistant receipts describe the actual requested task", () => {
  const event = { entity_type: "AssistantAction", action: "ASSISTANT_ACTION_COMPLETED",
    payload: { summary: "Register protein samples in ALPHA" } };
  assert.equal(auditRecord(event), "Register protein samples in ALPHA");
  assert.equal(auditDescription(event), "Register protein samples in ALPHA");
});
