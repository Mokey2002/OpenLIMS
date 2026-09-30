# Notebook regression coverage

GitHub Actions runs on pull requests and pushes to `main`. These are validation
gates, not automatic production deployment. Branch protection remains a GitHub
repository setting; this change does not configure it.

## Layers

- Backend suite: denied writes must not change data; invalid transitions and
  reviewed/locked edits; rollback after notification failure; inactive/revoked
  recipients; stable pagination when timestamps tie; existing stale-save tests.
- PostgreSQL concurrency gate: two independent connections compete to save from
  the same base revision. Exactly one succeeds and one gets a revision conflict.
  SQLite skips this locally, but `REQUIRE_POSTGRES_TESTS=1` makes a non-PostgreSQL
  CI run fail. Barriers and database timeouts bound hangs without fixed sleeps.
- Frontend unit suite: link selection, inaccessible parents, empty notebooks,
  mixed identifier types, and input immutability.
- Playwright: unavailable links show an error without fetching an unrelated
  experiment; failed switches keep the notebook and entry together; delayed
  selections cannot overwrite a newer selection or entry edits; unavailable
  details and slow supporting lists keep the navigator usable. My Work covers
  initial retry, background refresh failures, focus/action refresh, and stale
  responses. These tests use mocked responses; they do not establish backend
  authorization correctness. API/database tests cover that separately.

## Run

From `backend`, with the test PostgreSQL database configured:

```bash
pytest -v notebook/tests
REQUIRE_POSTGRES_TESTS=1 pytest -v notebook/tests/test_concurrency.py
```

From `frontend`:

```bash
node --test scripts/*.test.mjs
npm run build
```

With the frontend running, from `frontend/e2e`:

```bash
npm test -- tests/notebook-links.spec.js tests/daily-workflow.spec.js
```

CI uploads retained browser traces, screenshots and the frontend log on failure
for seven days. Tests use fictional records; do not point test configuration at
a production database. Passing these checks is not a load test or a guarantee
against every race condition. Timestamp ordering is deterministic for an
unchanged dataset; concurrent list mutations still require cursor pagination
for snapshot-like traversal.
