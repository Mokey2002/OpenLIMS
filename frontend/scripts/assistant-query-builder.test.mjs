import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { buildWorkflowQuestion } from "../src/workflowQuestion.js";
const cases = JSON.parse(readFileSync(new URL("../../backend/assistant/tests/fixtures/workflow_builder_cases.json", import.meta.url), "utf8"));
for (const example of cases) {
  test(`builder grammar: ${example.question}`, () => {
    assert.deepEqual(buildWorkflowQuestion(example.draft), { question: example.question, error: "" });
  });
}
test("rejects malformed choices and text that could introduce another condition", () => {
  const base = cases[0].draft;
  for (const change of [{project_code:"DEMO and project SECRET"}, {project_code:"X".repeat(65)}, {project_code:"DEMO."}, {filters:[]}, {filters:["unknown"]}, {filters:["all","blocked"]}, {filters:["all"],scope:"step"}, {filters:["assigned"],assignee:"maria or overdue"}, {match:"invalid"}, {scope:"invalid"}]) {
    const result = buildWorkflowQuestion({...base,...change});
    assert.equal(result.question, "");
    assert.ok(result.error);
  }
});
test("preview retains exact username and does not mutate draft or filter order", () => {
  const draft = { ...cases[0].draft, filters: ["assigned", "overdue"], assignee: "qc.user+lab@example.org", scope: "step" };
  const before = structuredClone(draft);
  assert.match(buildWorkflowQuestion(draft).question, /assigned to qc\.user\+lab@example\.org and are overdue on the same step\?/);
  assert.deepEqual(draft, before);
});
