import test from "node:test";
import assert from "node:assert/strict";
import { workflowDraftSteps } from "../src/assistantWorkflowDraft.mjs";
const procedure = { id: 1, code: "EX", version: "1", name: "Extraction", active: true };
const draft = { steps: [{ procedure: 1, code: "EX", version: "1", name: "Untrusted" }] };
test("draft uses current procedure names and safe designer defaults", () => {
  assert.deepEqual(workflowDraftSteps(draft, [procedure], () => ({ requires_qc: false, dependencies: "previous" })),
    [{ procedure: "1", name: "Extraction", requires_qc: false, dependencies: "previous" }]);
});
test("stale, inactive, malformed or oversized drafts cannot populate designer", () => {
  for (const bad of [null, {}, { steps: [] }, { steps: [null] }, { steps: Array(31).fill(draft.steps[0]) }])
    assert.equal(workflowDraftSteps(bad, [procedure], () => ({})), null);
  for (const rows of [[], [{ ...procedure, active: false }], [{ ...procedure, version: "2" }]])
    assert.equal(workflowDraftSteps(draft, rows, () => ({})), null);
});
