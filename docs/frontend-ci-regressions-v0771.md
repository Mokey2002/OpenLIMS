# v0.77.1: Frontend CI regressions

The four failures reported after v0.77.0 were reproduced on the merged main revision: four failures and seven passing tests across the three affected suites.

| Failing scenario | Cause | Correction |
| --- | --- | --- |
| Failed notebook switch | Expected the old `failed: 503` transport string | Assert the readable service error; keep notebook/experiment pairing checks and verify a later successful switch clears the error. |
| Unavailable initial experiment | Expected the old `failed: 403` transport string | Assert the safe access-denied message and usable navigator, then open another accessible experiment. |
| Sample loading/search | Looked for a button named `Next` | Use `Next sample page`, the current accessible name; preserve debounce, stale-result, page reset and reference-data assertions. |
| Failed sample history | Expected HTTP `503` in a user-facing alert | Assert the readable service error, no misleading empty timeline and successful history recovery after reload. |

Server/proxy errors remain sanitized. No raw status/path/body strings were restored to the UI to make tests pass, and none of the four tests was skipped or removed. Application code, data permissions, database schema and dependencies are unchanged.

Validation includes the affected browser suites, the complete frontend browser suite, frontend unit tests and a production build. The full browser suite uses a local Docker API with the same seeded demo account as CI for its real cookie-session tests; other tests keep their existing isolated fixtures.

The root version and generated footer are 0.77.1. Both READMEs retain only 0.77.1, 0.77.0 and 0.76.0 release updates. Older release guides remain available in `docs/`. No migration is required. Existing installations need no data repair; rebuilding the web image publishes the updated footer.
