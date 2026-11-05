import test from "node:test";
import assert from "node:assert/strict";
import { canWrite, readOnlyMessage } from "../src/authz.js";

test("mixed administrator/viewer and technician/viewer roles do not claim read-only access", () => {
  for (const roles of [["admin", "viewer"], ["tech", "viewer"]]) {
    const user = { roles };
    assert.equal(canWrite(user), true);
    assert.equal(readOnlyMessage(user), "");
  }
});

test("viewer-only and reviewer/viewer accounts retain their read-only explanation", () => {
  for (const roles of [["viewer"], ["qc_reviewer", "viewer"]]) {
    const user = { roles };
    assert.equal(canWrite(user), false);
    assert.match(readOnlyMessage(user), /Read-only access/);
  }
});
