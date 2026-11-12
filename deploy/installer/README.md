# Image-based installation and updates

This guide targets OpenLIMS **v0.78.1**, with versioned release bundles, a local demo and backed-up, resumable updates. See the complete [release, demo and update guide](../../docs/prebuilt-releases-demo-updates-v0780.md).

PostgreSQL readiness uses TCP so initialization finishes before migrations or restores. See the [v0.78.1 readiness and CI diagnostics guide](../../docs/release-smoke-readiness-v0781.md).

Requires Python 3.10+, Docker Engine/Desktop and Compose v2 supporting `up --wait`. The convenience demo launcher also needs curl. No application source build or host-side Node/application dependencies are needed. Release downloads exist only after the reviewed GitHub release workflow completes.

## Local demo

```bash
curl -fsSL https://github.com/Mokey2002/OpenLIMS/releases/download/v0.78.1/openlims-demo.sh -o openlims-demo.sh && sh openlims-demo.sh
./openlims-demo/openlims doctor
./openlims-demo/openlims stop
./openlims-demo/openlims start
```

The demo binds only to localhost, creates a unique project/volumes, loads examples and prints generated credentials. Configuration is private and reused on resume. Normal demo seeding does not change credentials; the dedicated bootstrap command is restricted to explicit local demo mode.

## Production

Download/unpack the reviewed release's `openlims-v0.78.1.tar.gz`. Point the domain at a fresh server with ports 80/443 available:

```bash
python3 openlims install --directory /opt/openlims-install --domain lims.example.org --version v0.78.1
/opt/openlims-install/openlims admin
/opt/openlims-install/openlims doctor
```

Caddy supplies HTTPS. Only the edge publishes production ports. Database, broker, API and worker stay on the private Compose network. Public `/media/` is blocked; use authenticated attachment downloads. The API, worker and assistant monitor share the same pinned backend image. No demo login is installed in production. Docker access is privileged; use a trusted operator account with access to the selected directory.

Existing explicit `--backend-image ...@sha256:... --frontend-image ...@sha256:...` fresh-install commands remain supported. Prefer official version manifests to obtain matched images and installed update tooling.

## Update, resume and backup

```bash
/path/to/installation/openlims update --version v0.78.1
/path/to/installation/openlims update --version v0.78.1 --resume
/path/to/installation/openlims backup
```

Choose a newer published version when upgrading. The installed version is a health-only no-op. Updates verify image/source labels, stop writers, back up PostgreSQL/uploads/configuration, migrate with a one-shot container and check services before completing. They retain secrets, project/volume identity and scientific records. Demo data is not reseeded.

An interrupted migration remains in maintenance with a private checkpoint and backup. Resume the same target after fixing the issue. Automatic schema downgrades and volume deletion are not provided. A failed startup resumes startup instead of repeating a successful migration. Private `operations.log` contains command diagnostics; redact secrets before sharing it.

Legacy installer-managed directories are supported using the new bundle's CLI with `--directory`; if no version was recorded, provide the actual current footer once with `--from-version`. Existing source-built Compose deployments are not adopted automatically. Manually changed managed templates are retained and require review. External database connections are rejected because this updater cannot make their backup.

Backups remain local. Configure off-server copies, retention and a restore drill for production. The updater is not an OS patching, SMTP, monitoring-alert or PostgreSQL major-version upgrade tool. See the full guide for release publication, architecture tests and restoring into an isolated instance.

## Guía breve en español

La demostración local descarga imágenes verificadas, genera credenciales y solo publica localhost. Producción usa HTTPS y una cuenta creada con `admin`, sin usuarios de demostración. Ambos modos conservan configuración y volúmenes.

`update --version v0.78.1` selecciona una versión publicada, respalda base de datos/archivos/configuración antes de migrar y comprueba los servicios. Si se interrumpe, corrige la causa y ejecuta el mismo comando con `--resume`. No restablece contraseñas ni vuelve a cargar los ejemplos. Los respaldos privados se conservan en `backups/`; cópialos fuera del servidor y verifica una restauración aislada.

Las instalaciones del instalador anterior pueden actualizarse con el CLI nuevo y `--directory`. Las instalaciones desde código conservan su flujo Git/reconstrucción. No se adoptan proyectos ajenos ni conexiones a bases externas. Las imágenes y descargas solo se anuncian cuando terminan las comprobaciones de CI, ambas arquitecturas y acceso público. Las comprobaciones esperan conexiones TCP de PostgreSQL para que termine la inicialización antes de migrar o restaurar.
