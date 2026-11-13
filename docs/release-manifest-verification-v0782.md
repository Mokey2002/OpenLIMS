# v0.78.2: Manifest compatibility and recovery of a partial release

Image uploads and a complete installer release are separate stages. Native images are uploaded first and can already receive pulls. The publisher then creates combined platform tags and uploads the demo launcher, installer archive, checksums and final release manifest.

## Why v0.78.1 stopped

The published backend tag contains the correct tested AMD64 and ARM64 image digests. Both images identify version `v0.78.1`, source commit `8e1953a741dd12bb3ee3f87e686123b95996b051` and the OpenLIMS repository. Docker combined them into a schema-2 Docker manifest list. That format does not carry OCI index annotations, so the old verifier incorrectly rejected it after a successful push.

The corrected verifier accepts that Docker format when its platform/digest mapping exactly matches the already-validated candidates. OCI indices still require matching version/revision annotations. Conflicting annotations, different digests, missing/duplicate platforms and unsupported formats are rejected. Existing valid tags are reused unchanged; different published tags are never replaced.

## Complete the existing v0.78.1 release

After merging this fix and passing its checks:

1. Open **Actions → Recover release publication → Run workflow** and select **main**.
2. Set `release_version` to `v0.78.1` and `original_run_id` to `43341244265`.
3. Run the workflow and wait for success.

The recovery workflow verifies that the original run was a completed release run for the same repository and tag commit. Its checks, release gate, AMD64 job and ARM64 job must have succeeded. It handles publisher-only reruns while refusing to hide a newer failed native attempt behind an earlier pass. It downloads the original run's retained image-digest artifacts and revalidates the public images' platform/version/source labels.

Updated publisher code runs against a separate checkout of the original tag. The original `VERSION`, installer files and demo launcher template must match their committed bytes. The recovered bundle therefore remains v0.78.1 from its original source; current development v0.78.2 files are not substituted. Recovery reuses the existing valid backend index, creates a missing frontend index and uploads only missing or byte-identical release assets. It neither moves the tag nor rebuilds application images.

The original digest artifacts must still be available; their normal retention is 14 days. Recovery stops if tests, metadata or artifacts are missing. A fresh release is needed when the original tested artifacts can no longer be recovered. Public GHCR access remains required.

Re-running the old failed publisher by itself continues to use the old code from the v0.78.1 tag. Use the recovery workflow to apply the corrected publisher to that release. Future releases use the fixed publisher normally.

## Verify availability

Once recovery succeeds, the v0.78.1 release must contain `openlims-demo.sh`, `openlims-v0.78.1.tar.gz`, `SHA256SUMS` and `release.json`. The existing v0.78.1 demo command then becomes available. The README demo command intentionally stays pinned to that release while the development version advances to v0.78.2.

Validation covers the actual public backend index and all four native candidates through anonymous, read-only GHCR requests, plus regression tests for both index formats, partial publication, immutable tags, recovery gates, failed reruns and original source bytes.
