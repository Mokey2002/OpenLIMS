import { useCallback, useEffect, useRef, useState } from "react";
import { normalizeTablePreferences, readTablePreferences, tablePreferenceKey, writeTablePreferences } from "../utils/tablePreferences";

function storage() {
  try { return window.localStorage; } catch { return null; }
}

export default function useTablePreferences(userId, name, defaults) {
  const key = tablePreferenceKey(userId, name);
  const [entry, setEntry] = useState({ key: null, value: normalizeTablePreferences(null, defaults) });
  const latest = useRef(entry);
  useEffect(() => {
    const next = { key, value: readTablePreferences(storage(), key, defaults) };
    latest.current = next;
    // Hydrate this user's external browser preferences before displaying rows.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEntry(next);
  }, [key, defaults]);
  const update = useCallback(patch => {
    if (!key || latest.current.key !== key) return;
    const value = latest.current.value;
    const next = { key, value: normalizeTablePreferences({ ...value, ...(typeof patch === "function" ? patch(value) : patch) }, defaults) };
    latest.current = next;
    writeTablePreferences(storage(), key, next.value);
    setEntry(next);
  }, [key, defaults]);
  const reset = useCallback(() => update(normalizeTablePreferences(null, defaults)), [update, defaults]);
  return { preferences: entry.key === key ? entry.value : normalizeTablePreferences(null, defaults), update, reset, ready: Boolean(key && entry.key === key) };
}
