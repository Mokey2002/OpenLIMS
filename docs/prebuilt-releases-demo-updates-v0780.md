# v0.78.0: Prebuilt releases, local demo and updates

## What is distributed

Each successful stable release publishes:

- `ghcr.io/mokey2002/openlims-backend:v0.78.0`, with linux/amd64 and linux/arm64 manifests. API, Celery worker and assistant monitor use the same backend digest with different commands.
- `ghcr.io/mokey2002/openlims-frontend:v0.78.0`, for both architectures, compiled with the release's footer version.
- `release.json`, recording the source commit, supported platforms, immutable image-index digests and installer file/archive checksums.
- `openlims-v0.78.0.tar.gz`, a small Python/Compose installer bundle, `openlims-demo.sh` and `SHA256SUMS`.

PostgreSQL, Redis and Caddy use their official images. Docker selects the native application image automatically. No application source checkout, Node toolchain or Python application dependency installation is required on the target host.

These artifacts are produced by the release workflow; committing the workflow does not publish them. The release manifest is uploaded last so clients do not discover an update before its archive is available.

## Try the local demo

Use Linux, macOS or WSL2 with Docker Engine/Desktop, Compose v2 supporting `up --wait`, Python 3.10+ and curl. Allow at least 10 GiB free disk space and preferably 4 GiB RAM. The launcher does not install system packages or request sudo.

After the v0.78.0 release workflow succeeds:

```bash
curl -fsSL https://github.com/Mokey2002/OpenLIMS/releases/download/v0.78.0/openlims-demo.sh -o openlims-demo.sh && sh openlims-demo.sh
```

The script downloads the versioned bundle over HTTPS, checks its SHA-256 checksum and extracts only regular installer files. It creates `./openlims-demo` with a unique Compose project and data volumes. Only the frontend publishes a port, bound to `127.0.0.1:8080`. Database, Redis and API ports remain private.

The installer initializes the schema, loads fictional example data, creates a generated director password and checks the API, worker and HTTP endpoints. `bootstrap_demo` requires explicit demo mode, loopback-only allowed hosts and no production domain. It refuses to reset an existing password. Normal `seed_demo` behavior remains unchanged.

The URL and credentials are printed at successful startup. Credentials and generated secrets are also retained in the private `openlims-demo/.env` file. Repeating initialization preserves them; an initialized demo does not reseed its data. For another port or directory:

```bash
OPENLIMS_DEMO_PORT=8090 OPENLIMS_DEMO_DIRECTORY="$HOME/protein-demo" sh openlims-demo.sh
```

Manage an installed demo without downloading or rebuilding the application:

```bash
./openlims-demo/openlims doctor
./openlims-demo/openlims stop
./openlims-demo/openlims start
./openlims-demo/openlims backup
```

`stop` retains the database, broker and all volumes. `backup` briefly stops application writers, captures database/uploads/configuration, and restarts the services that were running. The CLI has no volume-deletion or automatic database-downgrade command.

## Install a production instance from images

Download and unpack `openlims-v0.78.0.tar.gz` from the same reviewed release, then run:

```bash
python3 openlims install --directory /opt/openlims-install --domain lims.example.org --version v0.78.0
/opt/openlims-install/openlims admin
/opt/openlims-install/openlims doctor
```

Run as an operator with Docker access and permission to write that installation directory. Production installation requires a fresh directory, a correctly resolving domain and free ports 80/443. Caddy manages HTTPS; production cookies remain secure. Demo initialization is never run in this mode. Create the administrator interactively through Django's password validation.

The installed `openlims` command points to versioned installer tools within `.tools/`. Tool activation occurs only after service checks pass. Application data/configuration live outside the tool bundle and are retained across tool changes.

## Update an existing managed installation

Choose a newer **published** stable version. For example, an earlier managed installation can update to this release with:

```bash
/path/to/installation/openlims update --version v0.78.0
```

If v0.78.0 is already installed, this only checks health. For a future release, replace the version with that release's published tag.

The updater:

1. Validates the installation identity, private configuration and managed Compose files. It checks the actual managed database/upload volumes instead of silently creating replacements. External database configurations are rejected because they would not be covered by its backup.
2. Downloads the release manifest and tool bundle, verifies checksums, pulls both pinned application images and verifies their version/source-revision labels before stopping services.
3. Takes an installation lock, stops the frontend/API/workers/monitor and confirms application writers are no longer running.
4. Writes a private backup under `backups/<timestamp>-<id>/`: PostgreSQL custom-format dump, upload archive, previous configuration, installation metadata and checksums. It verifies the dump is readable by `pg_restore` before migrations.
5. Switches application image references while retaining project/volume identity, database credentials, Django signing key and other configuration values. It runs migrations/collectstatic in a separate one-shot setup container.
6. Starts matching application services, checks Django/Celery/HTTP health, activates verified installer tools and records the completed version and backup path.

Updates never invoke demo seeding or reset credentials. PostgreSQL's major version is not upgraded by this command. Existing production Redis service settings are retained by this release; new local demos use a persistent broker volume.

Existing installations made with the initial `deploy/openlims` installer can use the new release bundle's command:

```bash
python3 openlims update --directory /path/to/existing-installation --version v0.78.0 --from-version v0.77.1
```

The original installer identity and known template hashes are checked. For an unversioned legacy/custom installation, read its current footer and supply that value once with `--from-version` (replace the example if different). The updater does not guess the current schema version or allow a declared downgrade. The selected target must be a verified release. Changed Compose files require review rather than automatic overwrite.

Existing source-built `deploy/docker-compose.prod.yml` installations retain their documented Git/rebuild update path. This command does not adopt arbitrary Compose projects or their data volumes. Moving those installations to the managed image layout requires a separately reviewed backup/restore migration.

## Interrupted updates and backup recovery

Pull/download failures happen before services stop. Later failures retain `update.json`, the last checkpoint and a private `operations.log`. After resolving the reported issue, resume the same target:

```bash
/path/to/installation/openlims update --version v0.78.0 --resume
```

A different target or altered backup is rejected. A still-running setup container blocks a second migration after a lost client connection. Migration failure leaves application writers stopped. Resuming runs the target's remaining Django migrations and health checks; a failed startup resumes startup without taking another backup or repeating migrations. The CLI does not restart old application code against a potentially changed schema.

The database dump, upload archive and previous private configuration are retained together. Restore them into a separate empty instance first and verify sample records, file contents and permissions before any live recovery. `scripts/smoke_release.py` performs an actual restore drill in a separate temporary PostgreSQL container and checks the pre-upgrade scientific record and upload. Keep backup files private: configuration includes secrets. Backups are local; copy them off-server for protection from host/disk loss.

## Publish the first release

1. Merge the reviewed PR and wait for **OpenLIMS CI** on that main-branch commit to pass.
2. Create a stable GitHub release whose tag exactly matches `v` plus `VERSION` (for this change, `v0.78.0`).
3. **Installer and release images** builds images on native Ubuntu AMD64 and ARM64 runners. Both run the PostgreSQL regression suite inside the actual built backend image, scientific-tool checks and a real demo/login/API/Celery, interrupted-migration/resume and backup-restore test. PR/manual runs also test images but do not publish them.
4. Each successful release job pushes only its tested native candidates. The publisher verifies platform/source/version metadata and anonymous access, combines both platforms into versioned indices and records immutable digests.
5. On the first publication, GHCR may default the two packages to private. Set `openlims-backend` and `openlims-frontend` to **Public** in GitHub package settings, then rerun the failed **publish** job. The workflow does not advertise a release whose images require a developer's registry credentials.
6. The publisher checks existing version tags/assets before reuse, refuses replacements and uploads `release.json` only after the other downloads exist. Retry a partially completed publication using **Re-run failed jobs**; a changed release requires a new version.

No GitHub/PAT credential is distributed in application images or installer archives. Publication uses the repository's Actions `GITHUB_TOKEN`. Backend/frontend Docker build contexts exclude local `.env` files, caches, uploads, dependencies and build output. A session CA may be supplied through an optional BuildKit secret for managed-cloud development; it is not copied into an image.

## Validation

Run installer/release tests with `python3 -m unittest discover -s deploy/installer -p 'test_*.py' -v`. Native smoke tests require Docker and two built images:

```bash
python3 scripts/smoke_release.py --backend-image openlims-backend:smoke --frontend-image openlims-frontend:smoke --version v0.78.0
```

The smoke test uses a private temporary directory and registry, a fresh random demo project, a synthetic next-release image containing a real test migration, and a separate restore database. It removes only its own test containers/volumes. Public artifacts contain the tested release images, never the synthetic upgrade image.
