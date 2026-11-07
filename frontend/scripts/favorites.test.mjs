import test from "node:test";
import assert from "node:assert/strict";
import { favoritesStorageKey, loadFavorites, saveFavorites } from "../src/utils/favorites.js";

const routes = { "/": "My Work", "/projects": "Projects", "/samples": "Samples" };
function memoryStorage() {
  const data = new Map();
  return { getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value) };
}

test("accounts independently save, reload and remove favorites", () => {
  const storage = memoryStorage();
  assert.equal(saveFavorites(1, ["/projects"], routes, storage), true);
  assert.deepEqual(loadFavorites(2, routes, storage), []);
  saveFavorites(2, ["/samples"], routes, storage);
  assert.deepEqual(loadFavorites(1, routes, storage), ["/projects"]);
  saveFavorites(1, [], routes, storage);
  assert.deepEqual(loadFavorites(1, routes, storage), []);
  assert.deepEqual(loadFavorites(2, routes, storage), ["/samples"]);
});

test("the unowned legacy list is never attributed to an account or overwritten", () => {
  const storage = memoryStorage();
  storage.setItem("openlims_favorites", '["/projects"]');
  assert.deepEqual(loadFavorites(1, routes, storage), []);
  assert.deepEqual(loadFavorites(2, routes, storage), []);
  saveFavorites(2, ["/samples"], routes, storage);
  assert.equal(storage.getItem("openlims_favorites"), '["/projects"]');
});

test("an unidentified account never reads or writes storage", () => {
  let accesses = 0;
  const forbidden = { getItem() { accesses++; return null; }, setItem() { accesses++; } };
  for (const id of [null, undefined, "", false, 0, -1, "undefined", "01", "1/2", Infinity, Number.MAX_SAFE_INTEGER + 1]) {
    assert.equal(favoritesStorageKey(id), null);
    assert.deepEqual(loadFavorites(id, routes, forbidden), []);
    assert.equal(saveFavorites(id, ["/projects"], routes, forbidden), false);
  }
  assert.equal(accesses, 0);
});

test("numeric/string identities use the same account, with no username dependency", () => {
  const storage = memoryStorage();
  saveFavorites(1, ["/samples"], routes, storage);
  assert.deepEqual(loadFavorites("1", routes, storage), ["/samples"]);
});

test("invalid JSON, invalid entries and duplicate routes cannot corrupt the menu", () => {
  const storage = memoryStorage(), key = favoritesStorageKey(1);
  for (const raw of ["broken-json", "null", '{}', '"/samples"']) {
    storage.setItem(key, raw);
    assert.deepEqual(loadFavorites(1, routes, storage), []);
  }
  storage.setItem(key, '["/projects",{},3,null,"__proto__","constructor","/unknown","/projects","/samples"]');
  assert.deepEqual(loadFavorites(1, routes, storage), ["/projects", "/samples"]);
});

test("blocked storage and failed writes do not throw", () => {
  const blocked = { getItem() { throw new Error("Storage blocked"); }, setItem() { throw new Error("Quota exceeded"); } };
  assert.deepEqual(loadFavorites(1, routes, blocked), []);
  assert.equal(saveFavorites(1, ["/projects"], routes, blocked), false);
});
