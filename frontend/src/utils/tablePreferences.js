const PREFIX = "openlims:table:v1:";
export const PAGE_SIZES = [10, 25, 50];

export function tablePreferenceKey(userId, name) {
  return /^[1-9]\d*$/.test(String(userId)) && /^[a-z][a-z0-9-]*$/.test(name) ? `${PREFIX}${userId}:${name}` : null;
}

export function normalizeTablePreferences(value, defaults) {
  const source = value && typeof value === "object" && !Array.isArray(value) ? value : {};
  const columns = Array.isArray(source.columns) ? defaults.columns.filter(key => source.columns.includes(key)) : [...defaults.columns];
  return {
    query: typeof source.query === "string" ? source.query.slice(0, 200) : "",
    sort: defaults.sorts.includes(source.sort) ? source.sort : defaults.sort,
    page: Number.isSafeInteger(source.page) && source.page > 0 && source.page <= 100000 ? source.page : 1,
    pageSize: PAGE_SIZES.includes(source.pageSize) ? source.pageSize : defaults.pageSize,
    columns: columns.length ? columns : [...defaults.columns],
    filters: Object.fromEntries(Object.entries(defaults.filters || {}).map(([key, fallback]) => [key,
      typeof source.filters?.[key] === "string" ? source.filters[key].slice(0, 200) : fallback])),
  };
}

export function readTablePreferences(storage, key, defaults) {
  try { return normalizeTablePreferences(key ? JSON.parse(storage?.getItem(key)) : null, defaults); }
  catch { return normalizeTablePreferences(null, defaults); }
}

export function writeTablePreferences(storage, key, value) {
  if (!key) return false;
  try { storage.setItem(key, JSON.stringify(value)); return true; }
  catch { return false; }
}

export function filterAndSortRows(rows, columns, preferences) {
  const query = preferences.query.trim().toLocaleLowerCase();
  const filtered = rows.filter(row => Object.entries(preferences.filters || {}).every(([key, value]) => !value || String(columns.find(column => column.key === key)?.value(row) ?? "") === value)
    && (!query || columns.some(column => String(column.value(row) ?? "").toLocaleLowerCase().includes(query))));
  const descending = preferences.sort.startsWith("-");
  const column = columns.find(item => item.key === preferences.sort.replace(/^-/, ""));
  if (column) {
    const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
    filtered.sort((a, b) => {
      const left = column.value(a), right = column.value(b);
      if (left === null || left === undefined || left === "") return right === null || right === undefined || right === "" ? 0 : 1;
      if (right === null || right === undefined || right === "") return -1;
      const result = typeof left === "number" && typeof right === "number" ? left - right : collator.compare(String(left), String(right));
      return descending ? -result : result;
    });
  }
  return filtered;
}
