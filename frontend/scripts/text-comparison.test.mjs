import test from "node:test";
import assert from "node:assert/strict";
import { compareText, comparisonText } from "../src/utils/textComparison.js";

for (const [before, after] of [["Store protein at 4 C.", "Store protein at -20 C."], ["", "new block"], ["old block", ""],
  ["same text", "same text"], ["repeat repeat red repeat", "repeat blue repeat repeat"], ["α蛋白 🙂\n4 °C", "α蛋白 🙂\n20 °C"],
  ['<img src=x onerror="attack()">', '<script>alert("changed")</script>']]) {
  test(`reconstructs both sides without interpreting content: ${JSON.stringify(before).slice(0, 35)}`, () => {
    const result = compareText(before, after);
    assert.equal(result.before.map(part => part.text).join(""), before);
    assert.equal(result.after.map(part => part.text).join(""), after);
    assert.ok(result.before.every(part => part.type !== "added"));
    assert.ok(result.after.every(part => part.type !== "removed"));
  });
}
test("highlights the changed words and keeps unchanged context", () => {
  const result = compareText("Protein stored at 4 C", "Protein stored at 20 C");
  assert.equal(result.before.filter(part => part.type === "removed").map(part => part.text).join(""), "4");
  assert.equal(result.after.filter(part => part.type === "added").map(part => part.text).join(""), "20");
});
test("large edits have a bounded fallback and explicitly report shortening", () => {
  const result = compareText("old ".repeat(10000), "new ".repeat(10000));
  assert.equal(result.truncated, true);
  assert.equal(result.coarse, true);
  assert.ok(result.before.map(part => part.text).join("").length <= 12000);
});
test("readable structured values distinguish missing, null, false and numeric zero", () => {
  assert.notEqual(comparisonText(undefined), comparisonText(null));
  assert.equal(comparisonText(false), "No");
  assert.equal(comparisonText(0), "0");
  assert.equal(comparisonText({ protein_name: "P53", concentrations: [0, 2] }), "protein name: P53\nconcentrations: 0\n2");
});
