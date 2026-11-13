#!/usr/bin/env python3
"""Verify native candidates, publish multi-platform indices and immutable release assets."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from package_release import package
from openlims_lifecycle import REQUIRED_FILES, repository, version

ACCEPT = ", ".join(["application/vnd.oci.image.index.v1+json", "application/vnd.oci.image.manifest.v1+json",
                    "application/vnd.docker.distribution.manifest.list.v2+json", "application/vnd.docker.distribution.manifest.v2+json"])
OCI_INDEX = "application/vnd.oci.image.index.v1+json"
DOCKER_LIST = "application/vnd.docker.distribution.manifest.list.v2+json"


def validate_source(source, release_version, commit):
    """Pin installer bytes to the image source, including during recovery."""
    source = source.resolve()
    head = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    if head != commit:
        raise RuntimeError("Installer source checkout does not match the release image commit.")
    if (source / "VERSION").read_text().strip().removeprefix("v") != release_version.removeprefix("v"):
        raise RuntimeError("Installer source VERSION does not match the selected release.")
    for name in ["VERSION", "deploy/demo.sh.in", *["deploy/" + name for name in sorted(REQUIRED_FILES)]]:
        path = source / name
        committed = subprocess.run(["git", "-C", str(source), "show", f"{commit}:{name}"], check=True, capture_output=True).stdout
        if path.is_symlink() or path.read_bytes() != committed:
            raise RuntimeError("Installer source files differ from their committed release bytes.")
    return source


class Registry:
    """Anonymous reads intentionally ignore Docker/GitHub credentials to verify public access."""
    def __init__(self):
        self.tokens = {}

    def request(self, name, resource, missing_ok=False):
        url = f"https://ghcr.io/v2/{name}/{resource}"
        headers = {"Accept": ACCEPT}
        if name in self.tokens:
            headers["Authorization"] = "Bearer " + self.tokens[name]
        try:
            response = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=45)
        except urllib.error.HTTPError as error:
            if error.code == 404 and missing_ok:
                return None
            if error.code != 401:
                raise RuntimeError("Anonymous GHCR verification failed. Make both image packages public, then rerun the publisher job.") from None
            challenge = error.headers.get("WWW-Authenticate", "")
            fields = dict(re.findall(r'([a-z]+)="([^"]+)"', challenge))
            if fields.get("realm") != "https://ghcr.io/token" or fields.get("service") != "ghcr.io":
                raise RuntimeError("Unexpected registry authentication endpoint.") from None
            token_url = fields["realm"] + "?" + urllib.parse.urlencode({"service": "ghcr.io", "scope": f"repository:{name}:pull"})
            try:
                with urllib.request.urlopen(token_url, timeout=45) as token_response:
                    self.tokens[name] = json.load(token_response)["token"]
            except (urllib.error.HTTPError, KeyError):
                raise RuntimeError("GHCR packages are not anonymously readable. Set package visibility to Public and rerun this publisher job.") from None
            headers["Authorization"] = "Bearer " + self.tokens[name]
            try:
                response = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=45)
            except urllib.error.HTTPError as retry:
                if retry.code == 404 and missing_ok:
                    return None
                raise RuntimeError("Anonymous GHCR verification failed; no existing release asset was overwritten.") from None
        with response:
            if not response.geturl().startswith("https://"):
                raise RuntimeError("Registry read redirected away from HTTPS.")
            content = response.read(4 * 1024 * 1024 + 1)
            if len(content) > 4 * 1024 * 1024:
                raise RuntimeError("Registry metadata exceeds its supported size.")
            return json.loads(content), response.headers.get("Docker-Content-Digest") or "sha256:" + hashlib.sha256(content).hexdigest()

    def manifest(self, reference, missing_ok=False):
        if not reference.startswith("ghcr.io/"):
            raise RuntimeError("Release images must be in GHCR.")
        value = reference.removeprefix("ghcr.io/")
        name, selected = value.split("@", 1) if "@" in value else value.rsplit(":", 1)
        result = self.request(name, "manifests/" + selected, missing_ok)
        if result and "@" in reference and result[1] != selected:
            raise RuntimeError("Registry response digest does not match the requested immutable image.")
        return result


def validate_candidates(records, selected_repository, release_version, commit, registry):
    expected = {"linux/amd64", "linux/arm64"}
    if len(records) != 2 or {record.get("platform") for record in records} != expected:
        raise RuntimeError("Both native platform smoke tests must produce release candidates.")
    output = {"backend": {}, "frontend": {}}
    for record in records:
        if set(record.get("images", {})) != set(output):
            raise RuntimeError("Each platform must provide backend and frontend image digests.")
        for component, reference in record["images"].items():
            name = f"{selected_repository.lower()}-{component}"
            if not re.fullmatch(re.escape("ghcr.io/" + name) + r"@sha256:[a-f0-9]{64}", reference):
                raise RuntimeError("Candidate image does not belong to this release repository.")
            manifest, _ = registry.manifest(reference)
            config, _ = registry.request(name, "blobs/" + manifest["config"]["digest"])
            platform = config.get("os", "") + "/" + config.get("architecture", "")
            labels = config.get("config", {}).get("Labels") or {}
            if (platform != record["platform"] or labels.get("org.opencontainers.image.version") != release_version
                    or labels.get("org.opencontainers.image.revision") != commit
                    or labels.get("org.opencontainers.image.source", "").lower() != "https://github.com/" + selected_repository.lower()):
                raise RuntimeError("A native image has the wrong platform, source revision or version.")
            output[component][platform] = reference
    return output


def verify_index(index, candidates, release_version, commit):
    """Match already-validated native images without replacing an existing tag."""
    media_type = index.get("mediaType")
    if index.get("schemaVersion") != 2 or media_type not in (OCI_INDEX, DOCKER_LIST):
        raise RuntimeError("Unsupported release index format; expected an OCI index or Docker manifest list.")
    descriptors = index.get("manifests", [])
    actual = {}
    for item in descriptors:
        platform = item.get("platform", {})
        key = platform.get("os", "") + "/" + platform.get("architecture", "")
        if key in actual:
            raise RuntimeError("A release index contains duplicate platforms.")
        actual[key] = item.get("digest")
    expected = {platform: reference.split("@", 1)[1] for platform, reference in candidates.items()}
    if actual != expected:
        raise RuntimeError("An existing version tag contains different platform image digests. Publish a new version rather than replacing it.")
    annotations = index.get("annotations", {})
    if not isinstance(annotations, dict):
        raise RuntimeError("Invalid release index annotations.")
    # Docker manifest lists have no OCI index-annotation field. Their exact
    # native digests still bind the version/source labels checked by
    # validate_candidates. OCI indices retain the required annotation checks.
    for key, value in (("org.opencontainers.image.version", release_version),
                       ("org.opencontainers.image.revision", commit)):
        if (media_type == OCI_INDEX or key in annotations) and annotations.get(key) != value:
            raise RuntimeError("The release index has missing or conflicting version/source revision annotations.")


def publish_indices(candidates, selected_repository, release_version, commit, registry, run=subprocess.run):
    images = {}
    for component, platforms in candidates.items():
        name = f"ghcr.io/{selected_repository.lower()}-{component}"
        tag = name + ":" + release_version
        existing = registry.manifest(tag, missing_ok=True)
        if not existing:
            command = ["docker", "buildx", "imagetools", "create", "--tag", tag,
                       "--annotation", "index:org.opencontainers.image.version=" + release_version,
                       "--annotation", "index:org.opencontainers.image.revision=" + commit,
                       "--annotation", "index:org.opencontainers.image.source=https://github.com/" + selected_repository,
                       *[platforms[key] for key in sorted(platforms)]]
            run(command, check=True)
            existing = registry.manifest(tag)
        verify_index(existing[0], platforms, release_version, commit)
        images[component] = name + "@" + existing[1]
    return images


def publish_assets(output, selected_repository, release_version, run=subprocess.run):
    result = run(["gh", "release", "view", release_version, "--repo", selected_repository, "--json", "assets"],
                 check=True, capture_output=True, text=True)
    existing = {item["name"] for item in json.loads(result.stdout)["assets"]}
    # release.json is the readiness marker, uploaded only after all referenced downloads exist.
    names = [f"openlims-{release_version}.tar.gz", "openlims-demo.sh", "SHA256SUMS", "release.json"]
    for name in names:
        path = output / name
        if name in existing:
            with tempfile.TemporaryDirectory() as temporary:
                run(["gh", "release", "download", release_version, "--repo", selected_repository,
                     "--pattern", name, "--dir", temporary], check=True)
                if hashlib.sha256((Path(temporary) / name).read_bytes()).digest() != hashlib.sha256(path.read_bytes()).digest():
                    raise RuntimeError("A published release asset differs. Existing releases are never overwritten.")
        else:
            run(["gh", "release", "upload", release_version, str(path), "--repo", selected_repository], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", type=version, required=True)
    parser.add_argument("--repository", type=repository, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-directory", type=Path, default=Path(__file__).resolve().parents[1],
                        help="Checkout of the original release commit; keeps recovery bundles pinned to their source")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}", args.commit):
        parser.error("A complete source commit is required.")
    source = validate_source(args.source_directory, args.version, args.commit)
    records = [json.loads(path.read_text()) for path in sorted(args.candidates.glob("digests-*.json"))]
    registry = Registry()
    candidates = validate_candidates(records, args.repository, args.version, args.commit, registry)
    images = publish_indices(candidates, args.repository, args.version, args.commit, registry)
    package(args.output, args.version, args.repository, args.commit, images["backend"], images["frontend"], source=source)
    publish_assets(args.output, args.repository, args.version)
    print(f"Published verified {args.version} release indices and installer assets.")


if __name__ == "__main__":
    main()
