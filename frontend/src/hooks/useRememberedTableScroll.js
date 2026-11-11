import { useLayoutEffect } from "react";
import { tablePreferenceKey } from "../utils/tablePreferences";

export default function useRememberedTableScroll(userId, name, ready) {
  const identity = tablePreferenceKey(userId, name);
  useLayoutEffect(() => {
    if (!identity || !ready) return;
    const key = identity.replace("openlims:table:", "openlims:table-scroll:");
    const previousRestoration = window.history.scrollRestoration;
    window.history.scrollRestoration = "manual";
    let position = window.scrollY, first, second, restoring = true;
    const write = () => { try { sessionStorage.setItem(key, String(position)); } catch { /* Display preferences remain usable. */ } };
    const scroll = () => { if (!restoring) { position = window.scrollY; write(); } };
    let stored;
    try { stored = sessionStorage.getItem(key); } catch { stored = null; }
    first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => {
        const target = Number(stored);
        if (stored !== null && Number.isFinite(target) && target >= 0 && target <= 1000000) window.scrollTo({ top: target, behavior: "instant" });
        position = window.scrollY; restoring = false;
      });
    });
    window.addEventListener("scroll", scroll, { passive: true });
    window.addEventListener("beforeunload", scroll);
    return () => {
      cancelAnimationFrame(first); cancelAnimationFrame(second);
      window.removeEventListener("scroll", scroll); window.removeEventListener("beforeunload", scroll);
      if (!restoring) write();
      window.history.scrollRestoration = previousRestoration;
    };
  }, [identity, ready]);
}
