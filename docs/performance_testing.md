# Repeatable speed tests

These opt-in suites measure speed; they do not certify a supported sample count. Use a
separate test deployment and comparable hardware for before/after measurements.

## API and database benchmark

The pytest suite creates a disposable test database with one project, a project-member
technician, and one assigned work item per sample. Data is inserted in batches of 1,000.
It benchmarks session startup, My Work, a 50-row sample list, an exact sample-ID search,
and sample detail. Assertions check successful responses, full counts and bounded lists.

From `backend`, using your normal Python environment:

```bash
OPENLIMS_RUN_PERF=1 OPENLIMS_PERF_SAMPLES=1000 OPENLIMS_PERF_ROUNDS=20 \
  pytest performance/test_speed.py -q -s --junitxml=/tmp/openlims-speed.xml -o junit_family=legacy
```

Use a PostgreSQL test instance for representative measurements. pytest-django creates and
removes its own test database; its database user needs permission to create a test database.
Do not configure the test database name to be an existing laboratory database. For a local
SQLite smoke check only, add `--nomigrations` to bypass PostgreSQL-specific historical migrations.

Increase `OPENLIMS_PERF_SAMPLES` to 10,000, 100,000 or 500,000 when resources permit. Dataset
creation is excluded from timings. Results include first-request time, warm p50/p95/max
milliseconds, maximum response bytes, SQL query count, database engine, dataset size and
iteration count. Query instrumentation runs separately from the timed requests. JSON records
print to stdout; JUnit properties preserve the measurements for comparisons.

Optional gates fail the run when `OPENLIMS_PERF_P95_MS` or `OPENLIMS_PERF_MAX_QUERIES` is exceeded.
Choose budgets for the target machine after establishing a baseline. Without budgets, tests
check correctness and report speed. Routine pytest runs skip this suite.

This is an in-process authenticated API benchmark. It excludes HTTP/TLS, login cost, concurrent
users, uploaded files, instrument runs and background-worker throughput. Samples and work items
alone are not a realistic complete laboratory workload. Record CPU, RAM, database version and
OpenLIMS commit alongside results. Small datasets and SQLite results cannot establish
100,000-sample production capacity.

## Real-browser navigation benchmark

Build and serve the production frontend against an isolated running backend. Use an English
UI and a dedicated account with access to a known project and a sample visible on the first
sample-list page. Set credentials in environment variables; do not commit them:

```bash
cd frontend/e2e
export OPENLIMS_E2E_BASE_URL=http://127.0.0.1:5173
export OPENLIMS_PERF_USER=your_test_user
export OPENLIMS_PERF_PROJECT='Your project name'
export OPENLIMS_PERF_SAMPLE='Your visible sample ID'
read -s -p 'Test password: ' OPENLIMS_PERF_PASSWORD
export OPENLIMS_PERF_PASSWORD
OPENLIMS_PERF_ROUNDS=5 npx playwright test --config=playwright.performance.config.js
```

The test signs in, then measures clicks from My Work to Projects and Samples until the expected
record is visible, plus returns to My Work until its data-backed page is ready. It uses real
API responses and checks that navigation never reloads the document. It uses one browser/user
and performs read-only navigation after login; it does not seed or change laboratory records.

Results and timing attachments are saved under `frontend/e2e/performance-results/`.
`OPENLIMS_PERF_READY_MS` sets the per-page readiness timeout (default 30 seconds).
`OPENLIMS_PERF_P95_MS` optionally gates each route's p95. Browser measurements include the
first route load; first-load time is also reported separately. Five rounds are useful for a
smoke check; use more rounds for a stable p95. Keep failed traces and reports private because
they may contain test-account data. Never substitute mocked API timings for this suite.

## Initial local smoke baseline

Validated on September 9, 2026 in a local container using SQLite, not the deployment server.
API dataset: 1,000 samples and 1,000 assigned work items; 20 warm requests per scenario.

| API scenario | p95 milliseconds | SQL queries |
|---|---:|---:|
| Session | 2.91 | 3 |
| My Work | 9.11 | 15 |
| Sample list, 50 rows | 74.42 | 207 |
| Sample-ID search | 7.71 | 11 |
| Sample detail | 5.76 | 10 |

This historical baseline predates the v0.33.4 sample-list optimization. These numbers exclude network and
login overhead. First-request time can include Python URL/module initialization and is not
a controlled cold-database-cache measurement.

Real-browser validation used Chromium, Vite development serving and a temporary Django/SQLite
backend with 100 samples/work items. Five Projects and Samples visits plus ten My Work returns
passed with zero document reloads. Observed p95: Projects 439 ms, Samples 462 ms, My Work 505 ms.
These small smoke measurements do not establish production capacity or concurrency limits.
The production frontend build and opt-out behavior of routine pytest collection were also checked.

## v0.33.4 sample loading

The same local SQLite fixture (1,000 samples/work items, 20 warm rounds) now records
9 queries and 17.85 ms p95 for a 50-row sample list, compared with the baseline's
207 queries and 74.42 ms p95. The response remains 36,406 bytes. Query count is
independent of page length; a regression test compares 1 and 50 rows.

Permissions are annotated with a correlated membership EXISTS expression, scoped to
the requesting user. Linked-project summaries consume the ordered prefetch instead
of issuing another query for each sample. Mutation authorization still checks fresh
membership. Search waits 250 ms after typing, cancels older requests, and only reloads
samples when filters or pagination change. Reference data loads on each page visit.

A mocked-browser regression checks request counts, debounce, stale response handling
and page reset; its timing is not a production speed measurement. SQLite results
exclude network/concurrent load and do not establish PostgreSQL deployment capacity.
