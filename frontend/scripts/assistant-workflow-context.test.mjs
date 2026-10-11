import test from "node:test";
import assert from "node:assert/strict";
import { describeAssistantContext, describeWorkflowFilters } from "../src/assistantContext.js";

test("combined filters remain explicit in the context bar, including empty result pages", () => {
  const result = describeAssistantContext({ project_workflows: {
    project_code: "DEMO-360", filters: ["overdue", "unassigned"], match: "all", language: "en",
  } });
  assert.equal(result.kind, "project_workflows");
  assert.match(result.detail, /^Overdue AND Unassigned/);
  assert.match(result.label, /DEMO-360/);
});

test("OR and Spanish filters do not render as AND or raw internal keys", () => {
  assert.equal(describeWorkflowFilters({ filters: ["qc_failed", "missing"], match: "any", language: "es" }),
    "QC rechazado O Campos faltantes");
  assert.equal(describeWorkflowFilters({ filters: ["overdue", "unassigned"], match: "all", language: "es" }),
    "Vencidas Y Sin asignar");
});

test("older single-filter messages and cleared context still work", () => {
  assert.equal(describeWorkflowFilters({ filter: "qc_failed" }), "Failed QC");
  assert.equal(describeAssistantContext({}), null);
});
