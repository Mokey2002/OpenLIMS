import assert from "node:assert/strict";
import { test } from "node:test";
import { build } from "esbuild";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

const result = await build({
  entryPoints: [new URL("../src/components/WorkflowQueryExplanation.jsx", import.meta.url).pathname],
  bundle: true, write: false, format: "esm", platform: "node", jsx: "automatic",
});
const { default: Explanation } = await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString("base64")}`);
const render = (explanation) => renderToStaticMarkup(React.createElement(Explanation, { explanation }));
const base = {
  title: "Query explained: DEMO-360", language: "en", assignee: "maria",
  match_description: "AND: every condition must match.", scope_description: "Same step in the same run.",
  filters: [{ key: "assigned", meaning: "The work owner, not the reviewer." }, { key: "due_today", meaning: "Current calendar day." }],
  assignee_description: "Work owner: maria", notes: ["No sample scan was run. Page position preserved."],
};
test("renders filter names, owner, logic and pagination caveat", () => {
  const html = render(base);
  for (const text of ["Assigned to maria", "Due today", base.match_description, base.scope_description, base.notes[0]]) assert.ok(html.includes(text));
  assert.match(html, /aria-label="Query explained: DEMO-360"/);
});
test("Spanish labels remain readable", () => {
  const html = render({ ...base, language: "es" });
  for (const text of ["Significado de los filtros", "Asignadas a maria", "Vencen hoy"]) assert.ok(html.includes(text));
});
test("renders text safely and omits absent explanations", () => {
  assert.equal(render(null), "");
  const html = render({ ...base, title: "<script>alert(1)</script>", notes: ["<img src=x onerror=alert(1)>"] });
  assert.ok(!html.includes("<script>"));
  assert.ok(!html.includes("<img"));
  assert.ok(html.includes("&lt;script&gt;"));
});
