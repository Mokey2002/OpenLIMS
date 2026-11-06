export function favoritesStorageKey(userId) {
  const id = typeof userId === "number" && Number.isSafeInteger(userId) && userId > 0
    ? String(userId) : typeof userId === "string" && /^[1-9]\d{0,18}$/.test(userId) ? userId : null;
  return id ? `openlims_favorites:user:${id}` : null;
}

function cleanFavorites(value, routes) {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.filter(path => typeof path === "string" && Object.hasOwn(routes, path)))];
}

export function loadFavorites(userId, routes, storage) {
  const key = favoritesStorageKey(userId);
  if (!key) return [];
  try {
    const target = storage ?? globalThis.localStorage;
    return cleanFavorites(JSON.parse(target.getItem(key) || "[]"), routes);
  } catch {
    return [];
  }
}

export function saveFavorites(userId, paths, routes, storage) {
  const key = favoritesStorageKey(userId);
  if (!key) return false;
  try {
    const target = storage ?? globalThis.localStorage;
    target.setItem(key, JSON.stringify(cleanFavorites(paths, routes)));
    return true;
  } catch {
    return false;
  }
}
