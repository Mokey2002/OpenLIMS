import assert from "node:assert/strict";
import { after, test } from "node:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { build } from "esbuild";

const bundle = await build({ entryPoints: [new URL("../src/api.js", import.meta.url).pathname], bundle: true, write: false, format: "esm", platform: "node" });
const directory = await mkdtemp(join(tmpdir(), "openlims-api-test-"));
after(() => rm(directory, { recursive: true, force: true }));
const modulePath = join(directory, "api.mjs");
await writeFile(modulePath, bundle.outputFiles[0].text);
const moduleUrl = pathToFileURL(modulePath).href;
let instance = 0;

async function setup(t) {
  const events = [];
  const globals = {
    document: { cookie: "csrftoken=test-csrf" },
    window: { location: { pathname: "/samples", href: "/samples" }, dispatchEvent: event => events.push(event.detail) },
    localStorage: { removeItem() {} },
    sessionStorage: { removeItem() {} },
    CustomEvent: class { constructor(type, { detail }) { this.type = type; this.detail = detail; } },
  };
  for (const [key, value] of Object.entries(globals)) {
    const original = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value });
    t.after(() => original ? Object.defineProperty(globalThis, key, original) : delete globalThis[key]);
  }
  return { api: await import(`${moduleUrl}#${++instance}`), events };
}

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

test("simultaneous expired requests share one rotating-token refresh", async t => {
  const { api } = await setup(t);
  const gate = deferred();
  const refreshing = deferred();
  const attempts = new Map();
  let refreshes = 0;
  t.mock.method(globalThis, "fetch", async path => {
    if (path.endsWith("/auth/refresh/")) {
      const current = ++refreshes;
      refreshing.resolve();
      await gate.promise;
      return new Response(null, { status: current === 1 ? 200 : 401 });
    }
    attempts.set(path, (attempts.get(path) || 0) + 1);
    return Response.json({ path }, { status: attempts.get(path) === 1 ? 401 : 200 });
  });
  const results = Promise.allSettled([api.apiGet("/api/samples/"), api.apiGet("/api/projects/")]);
  await refreshing.promise;
  // Both original responses reach the refresh gate before it finishes.
  await new Promise(setImmediate);
  gate.resolve();
  assert.deepEqual((await results).map(result => result.status), ["fulfilled", "fulfilled"]);
  assert.equal(refreshes, 1);
  assert.equal(window.location.href, "/samples");
});

test("a delayed 401 from the old token reuses the completed refresh", async t => {
  const { api } = await setup(t);
  const slow = deferred();
  const attempts = new Map();
  let refreshes = 0;
  t.mock.method(globalThis, "fetch", async path => {
    if (path.endsWith("/auth/refresh/")) {
      refreshes++;
      return new Response(null, { status: refreshes === 1 ? 200 : 401 });
    }
    const attempt = (attempts.get(path) || 0) + 1;
    attempts.set(path, attempt);
    if (path.includes("projects") && attempt === 1) await slow.promise;
    return Response.json({ path }, { status: attempt === 1 ? 401 : 200 });
  });
  const fast = api.apiGet("/api/samples/");
  const results = Promise.allSettled([api.apiGet("/api/projects/"), fast]);
  await fast;
  slow.resolve();
  assert.deepEqual((await results).map(result => result.status), ["fulfilled", "fulfilled"]);
  assert.equal(refreshes, 1);
});

test("failed refresh is shared and an expired session still returns to login", async t => {
  const { api } = await setup(t);
  const gate = deferred();
  const refreshing = deferred();
  let refreshes = 0;
  t.mock.method(globalThis, "fetch", async path => {
    if (path.endsWith("/auth/refresh/")) {
      refreshes++;
      refreshing.resolve();
      await gate.promise;
    }
    return new Response(null, { status: 401 });
  });
  const results = Promise.allSettled([api.apiGet("/api/samples/"), api.apiGet("/api/projects/")]);
  await refreshing.promise;
  await new Promise(setImmediate);
  gate.resolve();
  for (const result of await results) {
    assert.equal(result.status, "rejected");
    assert.match(result.reason.message, /Session expired/);
  }
  assert.equal(refreshes, 1);
  assert.equal(window.location.href, "/login");
});

test("retry preserves a mutation's body and emits one pending/completion pair", async t => {
  const { api, events } = await setup(t);
  const mutations = [];
  t.mock.method(globalThis, "fetch", async (path, options) => {
    if (path.endsWith("/auth/refresh/")) return new Response(null, { status: 200 });
    mutations.push({ path, ...options });
    return Response.json({ id: 42 }, { status: mutations.length === 1 ? 401 : 201 });
  });
  assert.deepEqual(await api.apiPost("/api/samples/", { sample_id: "S-100" }), { id: 42 });
  assert.equal(mutations.length, 2);
  assert.deepEqual(mutations[1], mutations[0]);
  assert.equal(mutations[0].headers["X-CSRFToken"], "test-csrf");
  assert.deepEqual(events, [{ state: "pending" }, { state: "success" }]);
});

test("a retried 401 stops and later expirations can start a fresh refresh", async t => {
  const { api } = await setup(t);
  let refreshes = 0;
  t.mock.method(globalThis, "fetch", async path => {
    if (path.endsWith("/auth/refresh/")) { refreshes++; return new Response(null, { status: 200 }); }
    return new Response(null, { status: 401 });
  });
  await assert.rejects(api.apiGet("/api/samples/"), /Session expired/);
  assert.equal(refreshes, 1);
  await assert.rejects(api.apiGet("/api/projects/"), /Session expired/);
  assert.equal(refreshes, 2);
});

test("forbidden and authentication endpoints never trigger a refresh", async t => {
  const { api } = await setup(t);
  const paths = [];
  t.mock.method(globalThis, "fetch", async path => {
    paths.push(path);
    return new Response(null, { status: path.includes("auth") ? 401 : 403 });
  });
  await assert.rejects(api.apiGet("/api/samples/"), /403/);
  assert.equal((await api.apiGetResponse("/api/auth/login/")).status, 401);
  assert.deepEqual(paths, ["/api/v1/samples/", "/api/v1/auth/login/"]);
  assert.equal(window.location.href, "/samples");
});

test("cancelling a request during refresh does not replay it or redirect to login", async t => {
  const { api } = await setup(t);
  const controller = new AbortController();
  const gate = deferred();
  const refreshing = deferred();
  let requests = 0;
  t.mock.method(globalThis, "fetch", async path => {
    if (path.endsWith("/auth/refresh/")) {
      refreshing.resolve();
      await gate.promise;
      return new Response(null, { status: 401 });
    }
    requests++;
    return new Response(null, { status: 401 });
  });
  const result = assert.rejects(api.apiGet("/api/samples/", { signal: controller.signal }), { name: "AbortError" });
  await refreshing.promise;
  controller.abort();
  gate.resolve();
  await result;
  assert.equal(requests, 1);
  assert.equal(window.location.href, "/samples");
});

test("cancelling one waiter leaves the shared refresh available to other requests", async t => {
  const { api } = await setup(t);
  const controller = new AbortController();
  const gate = deferred();
  const refreshing = deferred();
  const attempts = new Map();
  let refreshes = 0;
  t.mock.method(globalThis, "fetch", async path => {
    if (path.endsWith("/auth/refresh/")) {
      refreshes++;
      refreshing.resolve();
      await gate.promise;
      return new Response(null, { status: 200 });
    }
    attempts.set(path, (attempts.get(path) || 0) + 1);
    return Response.json({ path }, { status: attempts.get(path) === 1 ? 401 : 200 });
  });
  const results = Promise.allSettled([api.apiGet("/api/samples/", { signal: controller.signal }), api.apiGet("/api/projects/")]);
  await refreshing.promise;
  await new Promise(setImmediate);
  controller.abort();
  gate.resolve();
  const [cancelled, completed] = await results;
  assert.equal(cancelled.status, "rejected");
  assert.equal(cancelled.reason.name, "AbortError");
  assert.equal(completed.status, "fulfilled");
  assert.equal(attempts.get("/api/v1/samples/"), 1);
  assert.equal(refreshes, 1);
  assert.equal(window.location.href, "/samples");
});

test("downloads preserve literal percent signs, quoted punctuation and UTF-8 names", async t => {
  const { api } = await setup(t);
  const names = [];
  let disposition;
  t.mock.method(globalThis, "fetch", async () => new Response("sequence", { headers: { "Content-Disposition": disposition } }));
  document.createElement = () => ({ click() { names.push(this.download); }, remove() {} });
  document.body = { appendChild() {} };
  t.mock.method(URL, "createObjectURL", () => "blob:test");
  const revoke = t.mock.method(URL, "revokeObjectURL", () => {});
  for (const [header, expected] of [
    ['attachment; filename="100% recovery.csv"', "100% recovery.csv"],
    ['attachment; filename="literal%20name.csv"', "literal%20name.csv"],
    ['attachment; filename="run;final.csv"', "run;final.csv"],
    ['attachment; filename="run\\"final.csv"', 'run"final.csv'],
    ["attachment; filename=plain.csv", "plain.csv"],
    ["attachment; filename=old.csv; filename*=UTF-8''an%C3%A1lisis.csv", "análisis.csv"],
    ["attachment; filename*=UTF-8'en'an%C3%A1lisis.csv", "análisis.csv"],
    ["attachment; filename=plain.csv; filename*=UTF-8''invalid%ZZ.csv", "plain.csv"],
    ["attachment; filename*=UTF-8''invalid%ZZ.csv", "fallback.csv"],
    ["attachment", "fallback.csv"],
  ]) {
    disposition = header;
    await api.apiDownload("/api/sequences/1/export/", "fallback.csv");
    assert.equal(names.at(-1), expected, header);
  }
  assert.equal(revoke.mock.callCount(), names.length);
});
