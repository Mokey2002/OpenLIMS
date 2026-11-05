# OpenLIMS v0.72.2: import privacy and recovery fixes

This release fixes reproduced issues in existing workflows. It adds no new database migration or service.

## Protected instrument source downloads

Original assistant-uploaded CSV/TSV files previously used the ordinary `/media/imports/` namespace. The production media alias could serve a file without checking the requester when its URL was known. New original uploads now use `assistant_artifacts/instrument_uploads/`, alongside the existing protected reports and repair files.

Production NGINX and Django deny raw media requests for both the protected namespace and the generated legacy assistant filenames. Django's development media handler checks normalized paths too, covering repeated slashes and dot components. The legacy rule matches generated UUID filenames, preserving ordinary imports such as `assistant-calibration.csv`. Other media policies are unchanged.

Use **Download source file** in either chat receipt. The new authenticated `GET /api/assistant/instrument-imports/<id>/source/` endpoint (also under `/api/v1/`) checks the existing import ownership/admin and current project-access rules, then verifies the stored source checksum before returning an attachment. Ordinary project collaborators cannot read someone else's assistant source. A creator who loses project access cannot download it. Administrators retain their existing access.

The general import API returns this authenticated source URL for the owner/admin and hides it from other collaborators. Source and row-report responses use `Cache-Control: private, no-store`. Ordinary, non-assistant import files retain their existing serializer behavior. Legacy assistant files work through the authenticated endpoint without moving files or changing database records.

## Repair confirmation recovery

Repeating validation of the same corrections previously returned an expired/cancelled action or a failed repair receipt without a new confirmable preview. It now renews that preview after validating current permissions, mapping, file identity and rows. The corrected child file, import ID and original-row claims are reused. Live current previews are still recovered rather than duplicated.

Queued/running/completed repairs return their current receipt. They are never silently reset or requeued by preview renewal. Measurements still require explicit confirmation, and worker redelivery retains the existing idempotency and row-accounting checks. Replacing corrections, supersession and duplicate-repair restrictions remain in force.

## Missing stored files

A missing on-disk source or repair file previously raised an unhandled filesystem exception during revalidation. It now returns a controlled error asking for the stored file to be restored. No measurements, row claims or prior receipts are removed. This is an error-handling fix; it does not reconstruct missing files or replace backups.

## Combined roles

Accounts with both `admin`/`tech` and `viewer` roles previously saw a generic read-only banner despite being allowed to write. The banner now follows the existing write-access helper. Viewer-only and reviewer/viewer accounts retain their read-only explanation for ordinary data changes; QC review permissions remain separate. No authorization policy is broadened.

## Deployment and verification

Version/footer: **0.72.2**. Both READMEs retain exactly **v0.72.2, v0.72.1 and v0.72.0** release updates.

For the repository production deployment, rebuild/recreate **API, worker and web** from the same commit. The web rebuild installs the NGINX media protections; an API-only rollout leaves the old NGINX media alias in place. Keep your existing Compose file, environment and project name. This patch adds no migration, dependency, automatic deployment or external notification.

Regression coverage includes real stored files, creator/admin/collaborator/anonymous/revoked access, checksum mismatch, legacy source access, normalized Django paths, missing files, expired/cancelled/failed repairs, retained row claims and duplicate worker delivery. Authenticated HTTP tests download actual source bytes and verify the checksum. Browser tests exercise source downloads/errors in both chat surfaces and combined-role banners, using simulated API responses. Exact release counts are recorded in the PR.

Run the isolated production NGINX check from the checkout:

```bash
python3 scripts/check_assistant_media.py
```

It uses the production NGINX configuration with synthetic fixtures in a temporary container, verifies denied private URLs and accessible ordinary media, and removes the container afterward. Docker and the NGINX image are required; no lab data is mounted.
