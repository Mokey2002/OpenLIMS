# Guided installation — initial implementation

This is a fresh-server installer, not an upgrade tool. Existing `deploy/docker-compose.prod.yml`
installations are unchanged. Python 3.10+, Docker Engine and Compose v2 supporting `up --wait`
must already be installed on Ubuntu. Use a dedicated Ubuntu 24.04 server, at least 2 GiB RAM
(4 GiB recommended), 10 GiB free disk space, and inbound TCP 80/443. This implementation has
unit tests; a clean Ubuntu deployment and restore drill remain required before production use.

## Images and prerequisites

Run the **Installer checks and optional images** workflow manually on a reviewed release commit.
It builds amd64 images and records both immutable `@sha256:` references in its summary.
This does not constitute a validated release. Package access/visibility must be configured by
the owner; for private images, authenticate using `docker login ghcr.io` on the server.
Images are not presumed published simply because this workflow exists.

Point the domain's A and (if present) AAAA records at the server. The installer verifies DNS
resolution, not authoritative DNS ownership or IP equality. Caddy obtains certificates;
incorrect DNS, firewall rules, or certificate issuance limits can prevent HTTPS verification.
Do not use this on the current live OpenLIMS server: it deliberately refuses occupied ports
for a new installation, and creates a unique Compose project and data volumes.

Download `deploy/openlims` together with its adjacent `deploy/installer/compose.yml` and
`Caddyfile` from the same reviewed commit. A source checkout is convenient for developers,
but the application source is not needed on the target machine.

```bash
python3 deploy/openlims install --directory /opt/openlims-install \
  --domain lims.example.org \
  --backend-image ghcr.io/OWNER/openlims-backend@sha256:BACKEND_DIGEST \
  --frontend-image ghcr.io/OWNER/openlims-frontend@sha256:FRONTEND_DIGEST
python3 deploy/openlims admin --directory /opt/openlims-install
python3 deploy/openlims doctor --directory /opt/openlims-install
```

Replace all placeholders with actual values. The directory must be writable by the operator;
Docker access is privileged and should be granted only to trusted administrators.
The admin command uses Django's interactive password validation; credentials are not passed
as command-line arguments. No default password, demo accounts, or public bootstrap endpoint
are installed. An expiring web setup link is deferred.

## Resume, diagnostics and safety

Rerun the identical install command after a failure. Secrets are created exclusively with
0600 permissions and never regenerated on resume. Concurrent operations are locked. Existing
configuration, templates, images and domain must match; changes require manual review.
Partial secret-file writes fail closed. Initialization is a separate one-shot task before
the application starts. When application services are already running, resume skips migrations.
No commands remove volumes or restore/overwrite a database. Do not use this as an upgrade tool.

`doctor` checks Django, the addressed Celery worker, and public HTTPS frontend/API endpoints.
It returns nonzero on failure and suppresses Docker output to avoid disclosing configuration.
For deeper investigation, an authorized operator can read Compose logs locally using the
project name in `installation.json`; redact secrets and laboratory data before sharing logs.
Certificate issuance may still be pending after services start; correct DNS/firewall issues
and rerun `doctor`. No automatic certificate retry loop hides a failure.

Only Caddy publishes host ports. Database/Redis/API/web stay on the Compose network.
The edge denies `/media/*`, and the web container does not mount uploads: use authenticated
application download endpoints. Features relying on public media URLs may need adaptation.
Ollama is not enabled. Persistent data includes PostgreSQL, uploads, static files, certificates.

## Production gate and remaining work

The installer does **not** configure scheduled/off-server backups, restore automation,
OS patching, SMTP, persistent diagnostic logs, LTS, upgrades, or monitoring alerts.
It explicitly warns that passing installation checks is not production readiness.
Before production: select an off-server backup destination and retention policy, capture
database plus uploads consistently during a maintenance window, protect configuration secrets,
and restore on an isolated server. Confirm sample, attachment, permissions, audit history,
worker processing and restart persistence. Never test restoration over live data.
Measure setup and recovery time with a lab administrator who did not write this software.

Run local tests: `python3 -m unittest discover -s deploy/installer -p 'test_*.py' -v`.

## Guía breve en español

Instalador inicial para un servidor Ubuntu dedicado; no actualiza instalaciones existentes.
Requiere Python 3.10+, Docker y Compose v2, DNS correcto, puertos 80/443 disponibles,
2 GiB de RAM como mínimo y 10 GiB de disco libre. Use las referencias inmutables de imágenes
publicadas mediante el flujo manual y sustituya los valores del ejemplo anterior.

`install` genera secretos privados, prepara la base de datos y comprueba HTTPS.
`admin` crea la cuenta mediante el asistente interactivo de Django, sin contraseña predeterminada.
`doctor` comprueba la aplicación, el trabajador y HTTPS. Después de un fallo, repita el mismo
comando: conserva los secretos y los datos. Si cambió la configuración, se detiene para revisión.
No ejecutarlo en el servidor de producción existente. No habilita usuarios de demostración ni Ollama.

Esta versión no configura copias programadas, almacenamiento externo, restauración automática,
alertas ni actualizaciones. Antes de usarla en producción, configure copias externas de la base
de datos y archivos, proteja los secretos y pruebe una restauración en otro servidor aislado.
Los enlaces públicos `/media/` están bloqueados; use descargas autenticadas. La instalación real
en Ubuntu y la prueba de restauración todavía deben validarse. El enlace web de configuración
con caducidad y la distribución de un paquete de instalación quedan pendientes.
