import assert from "node:assert/strict";
import { test } from "node:test";
import { describePageRecord, pageSelection } from "../src/assistantPageContext.js";

const publicId = "10101010-2020-4030-8040-505050505050";
const sample = { id: 7, public_id: publicId, sample_id: "DNA-007" };

test("page references come from matching loaded records and prefer stable public IDs", () => {
  const page = describePageRecord("/samples/7", "sample", sample);
  assert.equal(page.record_id, publicId);
  assert.equal(page.label, "DNA-007");
  assert.equal(describePageRecord(`/samples/${publicId}`, "sample", sample).record_id, publicId);
  assert.equal(describePageRecord("/projects/7", "project", { id: 7, code: "ALPHA" }).record_id, "7");
});

test("navigation, unloaded/failed records and unsupported routes do not reuse old page IDs", () => {
  for (const [path, kind, record] of [["/samples/8", "sample", sample], ["/projects/7", "sample", sample],
    ["/samples/7", "sample", null], ["/samples", "sample", sample], ["/assistant", "sample", sample],
    ["/samples/7/results", "sample", sample]]) assert.equal(describePageRecord(path, kind, record), null);
});

test("assistant-page handoffs retain only a validated reference and display label", () => {
  assert.deepEqual(pageSelection({ kind: "sample", record_id: publicId, label: "DNA-007", values: "discard" }),
    { kind: "sample", record_id: publicId, label: "DNA-007" });
  for (const value of [null, { kind: "user", record_id: "1", label: "Admin" },
    { kind: "sample", record_id: "../private", label: "Wrong" }, { kind: "sample", record_id: "0", label: "Wrong" }]) {
    assert.equal(pageSelection(value), null);
  }
});
