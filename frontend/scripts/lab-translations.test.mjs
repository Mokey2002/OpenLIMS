import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";
import { transformWithEsbuild } from "vite";
import { labSpanish } from "../src/translations/labSpanish.js";

// Exercise the production translator without mounting a browser or contacting an API.
const source = await readFile(new URL("../src/i18n.jsx", import.meta.url), "utf8");
const { code } = await transformWithEsbuild(source, "i18n.jsx", { format: "cjs" });
const sandbox = {
  module: { exports: {} },
  require(name) {
    if (name === "react") return { createContext: () => ({}) };
    if (name === "./api") return {};
    if (name === "./translations/labSpanish") return { labSpanish };
    throw new Error(`Unexpected dependency: ${name}`);
  },
};
vm.runInNewContext(code, sandbox);
const { translateText } = sandbox.module.exports;

test("every added label uses its Spanish translation and preserves English", () => {
  for (const [english, spanish] of Object.entries(labSpanish)) {
    assert.ok(spanish.trim());
    assert.equal(translateText(english, "es"), spanish, english);
    assert.equal(translateText(english, "en"), english);
  }
});

test("unknown identifiers and sequences remain unchanged", () => {
  for (const value of ["S-002", "ATGCGT", "EcoRI", "mzML", "My custom experiment 42"]) {
    assert.equal(translateText(value, "es"), value);
  }
});
