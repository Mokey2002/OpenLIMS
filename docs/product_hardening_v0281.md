# OpenLIMS v0.28.1 — Product Hardening

v0.28.1 focuses on making the existing OpenLIMS feature set cohesive, testable, and safer to deploy before adding more product breadth.

## User workflow

- The signed-in landing page is **My Work** and summarizes assigned work items, active requests, notebook experiments when enabled, QC attention, inventory/notification alerts, and overdue work.
- Primary navigation is organized around **Plan → Receive → Execute → Review → Report**.
- Admin-only and technician-only destinations are filtered by role.
- Users can pin frequently used destinations to a local Favorites menu.
- The previous dashboard remains available at `/dashboard`.

## Browser authentication

Browser authentication no longer stores JWT access or refresh tokens in `localStorage` or `sessionStorage`.

- Access and refresh JWTs are stored in `HttpOnly` cookies.
- Cookie-authenticated unsafe API requests enforce Django CSRF validation.
- Refresh tokens rotate and the replaced token is blacklisted.
- Logout blacklists the current refresh token and clears both authentication cookies.
- Bearer JWT authentication remains supported for scripts and non-browser API clients.
- Browser WebSockets authenticate from the same-origin access cookie instead of a query-string JWT.

For HTTPS deployments set:

```env
JWT_COOKIE_SECURE=true
CSRF_COOKIE_SECURE=true
SESSION_COOKIE_SECURE=true
```

Set `SECURE_SSL_REDIRECT=true` when Django consistently receives the original HTTPS scheme through the reverse proxy.

## Versioned API

The frontend API client normalizes application requests onto `/api/v1/`. The legacy `/api/` router remains available for backwards compatibility, but new browser traffic uses the versioned API. Health/schema/docs endpoints remain intentionally unversioned.

## Feature flags

Notebook and Registry feature flags are enforced at the HTTP API boundary for both `/api/` and `/api/v1/`. A disabled module returns `404` even when a user guesses a direct endpoint URL.

## Production deployment

`deploy/docker-compose.prod.yml` provides a production-shaped stack:

- PostgreSQL and Redis are internal-only and have health checks.
- Django runs with Daphne rather than the development server.
- Celery runs as a separate worker.
- Nginx serves the built React application and proxies API, media, and WebSocket traffic.
- Static and media files use persistent volumes.
- Ollama is optional under the `llm` Compose profile.
- Browser security headers, including CSP, are emitted by the production web tier.

Example:

```bash
cd deploy
cp .env.example .env
# Edit .env before continuing.
docker compose -f docker-compose.prod.yml up -d --build
```

The default public port is `8080` and can be changed with `OPENLIMS_HTTP_PORT`. In an Internet-facing deployment, place a TLS reverse proxy such as Caddy in front of this port.

## Testing

CI now runs:

- Django checks and migration validation
- the backend pytest suite
- the production Compose configuration parser
- the frontend production build
- Playwright Chromium tests against a seeded Docker backend and Vite frontend

The Playwright suite verifies the My Work landing page, workflow navigation, `/api/v1/` browser traffic, absence of browser-stored JWTs, `HttpOnly` authentication cookies, and logout behavior.

## Deferred to later releases

The broader laboratory-record retention/archive migration remains deferred to the production-readiness work because it requires coordinated model and API lifecycle changes. S3/MinIO storage, automated backups, monitoring, SSO/MFA, load testing, and connector credential scoping likewise remain follow-on production-readiness work.
