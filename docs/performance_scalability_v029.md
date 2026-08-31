# OpenLIMS v0.29.0 — Performance & Scalability

v0.29.0 focuses on reducing startup work, bounding dashboard queries, shrinking the initial JavaScript bundle, and preparing the existing OpenLIMS feature set to remain responsive as laboratory record counts grow.

## My Work

The My Work landing page no longer paginates through every visible work item, workflow request, notification, inventory alert, and notebook experiment in the browser.

`GET /api/v1/my-work/` now performs the filtering and aggregation server-side and returns a bounded payload containing:

- complete counts for assigned work, active requests, active experiments, QC attention, inventory alerts, unread notifications, and overdue work;
- at most 12 assigned work rows;
- at most 8 overdue rows;
- at most 5 unread notifications.

The response size therefore stays bounded even when a deployment contains thousands of work items or notifications.

## Application bootstrap

`GET /api/v1/session/` combines the small pieces of state required by the persistent application shell:

- current user and roles;
- feature flags;
- unread notification count.

This replaces separate startup calls for `/me/`, `/feature-flags/`, and `/notifications/`.

## API pagination

Normal paginated API responses now use 50 rows per page instead of 10. Clients may explicitly request a larger page with `?page_size=` up to a maximum of 200 rows.

The frontend `apiGetAll()` helper uses 200-row pages when a screen intentionally needs the complete collection. Existing full-collection screens therefore make up to 20 times fewer pagination requests while normal list responses remain bounded.

## Frontend code splitting

OpenLIMS routes are loaded with React `lazy()` and `Suspense`. The login shell is kept eager, while feature pages such as Registry, Notebook, Inventory, Mass Spec, BLAST, reporting, and administration are downloaded only when the user opens them.

The production Nginx configuration also enables gzip compression and gives Vite's content-hashed `/assets/` files a one-year immutable cache lifetime. `index.html` remains non-cacheable so deployments pick up a new release promptly.

## Database and cache settings

Production deployments can reuse healthy PostgreSQL connections instead of opening a new connection for every request:

```env
DB_CONN_MAX_AGE=60
```

The production environment template also reserves Redis database 3 for Django application caching:

```env
CACHE_URL=redis://redis:6379/3
```

When `CACHE_URL` is not configured, OpenLIMS uses Django's in-memory cache, which keeps development and test environments independent of Redis.

## Targeted indexes

v0.29.0 adds composite indexes for two high-frequency access paths introduced or emphasized by My Work and the application shell:

- work items: `(assigned_to, status, due_at)`;
- notifications: `(user, is_read, -created_at)`.

These complement the existing workflow/project indexes instead of adding broad indexes to every table.

## Performance regression coverage

The v0.29 tests verify that My Work returns complete counts while keeping row payloads bounded, that session bootstrap combines shell state correctly, that pagination uses the new bounded defaults and larger intentional fetch pages, and that the performance endpoints remain authenticated.

Future performance work should use realistic seeded datasets plus query-count and latency budgets before adding further indexes or cache layers.
