import test from "node:test";
import assert from "node:assert/strict";
import { describeAssistantContext, describeWorkflowFilters, describeWorkflowScope, groupWorkflowReasons } from "../src/assistantContext.js";

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

test("scope is visible and older answers default to sample scope", () => {
  assert.equal(describeWorkflowScope({}), "Across sample");
  assert.equal(describeWorkflowScope({ scope: "step" }), "Same step");
  assert.equal(describeWorkflowScope({ scope: "step", language: "es" }), "Mismo paso");
  const context = describeAssistantContext({ project_workflows: {
    project_code: "DEMO-360", filters: ["overdue"], scope: "step",
  } });
  assert.match(context.detail, /Same step/);
});

test("evidence groups never merge different runs or mutate the original reasons", () => {
  const reasons = [
    { run_id: 1, step: 1, kind: "overdue" },
    { run_id: 2, step: 1, kind: "unassigned" },
    { run_id: 1, step: 1, kind: "unassigned" },
    { run_id: 1, step: null, kind: "run_blocked" },
  ];
  const before = structuredClone(reasons);
  const groups = groupWorkflowReasons(reasons);
  assert.equal(groups.length, 3);
  assert.deepEqual(groups[0].reasons.map(r => r.kind), ["overdue", "unassigned"]);
  assert.equal(groups[1].run_id, 2);
  assert.equal(groups[2].step, null);
  assert.deepEqual(reasons, before);
  assert.deepEqual(groupWorkflowReasons(), []);
});

test("assignee names are visible for single and combined filters in both languages", () => {
  assert.equal(describeWorkflowFilters({ filters: ["assigned"], assignee: "maria" }), "Assigned to maria");
  assert.equal(describeWorkflowFilters({ filters: ["assigned", "overdue"], assignee: "maria", match: "all", language: "es" }), "Asignadas a maria Y Vencidas");
  const result = describeAssistantContext({ project_workflows: {
    project_code: "DEMO-360", filters: ["assigned", "overdue"], assignee: "peter", match: "any", scope: "step",
  } });
  assert.match(result.detail, /Assigned to peter OR Overdue/);
  assert.match(result.detail, /Same step/);
});

test("deadline filters are readable in English and Spanish", () => {
  assert.equal(describeWorkflowFilters({ filters: ["assigned", "due_today"], assignee: "maria", match: "all" }), "Assigned to maria AND Due today");
  assert.equal(describeWorkflowFilters({ filters: ["due_tomorrow", "due_soon"], match: "any", language: "es" }), "Vencen mañana O Vencen en los próximos 7 días");
});
