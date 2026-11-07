import assert from "node:assert/strict";
import { test } from "node:test";
import { clearLegacyTokens } from "../src/auth.js";

for (const denied of ["localStorage", "sessionStorage"]) {
  for (const denial of ["access", "removal"]) {
    test(`legacy cleanup tolerates blocked ${denied} ${denial} and cleans the other storage`, t => {
      const other = denied === "localStorage" ? "sessionStorage" : "localStorage";
      const entries = new Map([["access", "legacy"], ["refresh_token", "legacy"], ["openlims_favorites:user:1", "[]"]]);
      const error = () => { throw new DOMException("Storage is disabled", "SecurityError"); };
      for (const name of [denied, other]) {
        const original = Object.getOwnPropertyDescriptor(globalThis, name);
        const descriptor = name === denied && denial === "access"
          ? { get: error }
          : { value: { removeItem: name === denied ? error : key => entries.delete(key) } };
        Object.defineProperty(globalThis, name, { configurable: true, ...descriptor });
        t.after(() => original ? Object.defineProperty(globalThis, name, original) : delete globalThis[name]);
      }
      assert.doesNotThrow(clearLegacyTokens);
      assert.deepEqual([...entries], [["openlims_favorites:user:1", "[]"]]);
    });
  }
}
