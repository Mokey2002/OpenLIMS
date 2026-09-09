import { lazy } from "react";
import { OPENLIMS_VERSION } from "../version";

const RECOVERY_KEY = `openlims-page-recovery:${OPENLIMS_VERSION}`;

export function lazyPage(importPage) {
  return lazy(async () => {
    // Capture the destination so a late failure cannot reload a different page.
    const destination = window.location.href;
    try {
      return await importPage();
    } catch (error) {
      const message = String(error?.message || error);
      const moduleFailed = /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Unable to preload CSS|Loading chunk .* failed/i.test(message);
      if (moduleFailed && window.location.href === destination) {
        try {
          // One attempt per release and tab, including failures that persist after reload.
          if (!window.sessionStorage.getItem(RECOVERY_KEY)) {
            window.sessionStorage.setItem(RECOVERY_KEY, "attempted");
            window.location.reload();
            return await new Promise(() => {});
          }
        } catch {
          // Storage may be unavailable. Show the recovery UI instead of risking a loop.
        }
      }
      throw error;
    }
  });
}
