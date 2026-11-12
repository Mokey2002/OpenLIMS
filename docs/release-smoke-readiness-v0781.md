# v0.78.1: PostgreSQL readiness and release diagnostics

The official PostgreSQL image starts a temporary server while it creates the database and runs initialization scripts. That server accepts Unix-socket connections but does not accept TCP connections. `pg_isready` without a hostname can therefore report healthy before applications can connect, or before PostgreSQL shuts the temporary server down and starts its final server.

Demo and production installer templates, source-built production, native backend regressions and the backup-restore drill now use `pg_isready -h 127.0.0.1 -U openlims -d openlims` (with the configured role/database in source-built production). This tests the final TCP listener. Existing databases, credentials and volumes are retained; no application schema migration is added.

The restore drill installs a three-second initialization script with a completion marker. It must wait for TCP readiness and verify that marker before restoring the dump. This makes premature startup reproducible instead of depending on runner speed. Validation includes an old-check negative control, followed by the corrected check restoring an actual OpenLIMS test backup and verifying its sample row and upload archive.

## Failed CI jobs

Native backend and smoke-test failures print a bounded, redacted diagnostic report. The workflow saves only those `.txt` reports as `release-diagnostics-amd64` or `release-diagnostics-arm64`, retained for seven days. Smoke reports include the installer operation log and the captured container state/health and recent logs. Failures before installation also produce a report.

Generated database passwords, signing keys, demo credentials, URL-encoded forms and connection URL credentials are removed before truncation or publication. The artifact never includes `.env`, Compose environment/configuration dumps, database backups or uploaded files. Raw private logs remain in the temporary test directory. GitHub workflow-command processing is suspended while redacted log contents are printed.

`release-gate` is intentionally skipped on pull requests. It runs for stable release publication, where both native image jobs and successful application CI remain required. A skipped release gate on a PR is expected. A failed image job still blocks publication.

Run CI on the patch commit to use these changes; rerunning the old failed commit continues to use its old readiness checks and workflow. The original AMD64 traceback is needed to attribute a particular earlier failure; a reproduced readiness race does not by itself prove that every failed smoke run had the same cause.

## Local validation

```bash
python3 -m unittest discover -s deploy/installer -p 'test_*.py' -v
python3 scripts/smoke_release.py --backend-image openlims-backend:smoke --frontend-image openlims-frontend:smoke --version v0.78.1 --diagnostics /tmp/openlims-release-diagnostics/smoke.txt
```

The native CI jobs run the complete image tests and interrupted-update/restore drill on AMD64 and ARM64. Source-level diagnostic regressions additionally verify redaction, truncation boundaries, private report permissions, workflow-command isolation, and reports for backend or smoke failures before normal startup.
