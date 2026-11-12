#!/usr/bin/env python3
"""Create a small reproducible installer bundle from verified image digests."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy" / "installer"))
from openlims_lifecycle import REQUIRED_FILES, validate_release, version, repository


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def package(output, release_version, source_repository, commit, backend_image, frontend_image, source=ROOT):
    output.mkdir(parents=True, exist_ok=True)
    files = {name: (source / "deploy" / name).read_bytes() for name in sorted(REQUIRED_FILES)}
    manifest = {"schema": 1, "version": release_version, "repository": source_repository, "commit": commit,
                "images": {"backend": backend_image, "frontend": frontend_image},
                "platforms": ["linux/amd64", "linux/arm64"],
                "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    validate_release(manifest, source_repository, release_version)
    files["release.json"] = canonical(manifest)
    archive = output / f"openlims-{release_version}.tar.gz"
    with archive.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed, \
            tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as bundle:
        for name, content in sorted(files.items()):
            entry = tarfile.TarInfo(name)
            entry.size, entry.mtime = len(content), 0
            entry.mode = 0o700 if name == "openlims" else 0o600
            bundle.addfile(entry, io.BytesIO(content))
    manifest["bundle"] = {"name": archive.name, "sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
    (output / "release.json").write_bytes(canonical(manifest))
    launcher = (source / "deploy" / "demo.sh.in").read_text().replace("@VERSION@", release_version).replace("@REPOSITORY@", source_repository)
    (output / "openlims-demo.sh").write_text(launcher)
    artifacts = [archive, output / "release.json", output / "openlims-demo.sh"]
    (output / "SHA256SUMS").write_text("".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n" for path in artifacts))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", type=version, required=True)
    parser.add_argument("--repository", type=repository, default="Mokey2002/OpenLIMS")
    parser.add_argument("--commit", required=True)
    parser.add_argument("--backend-image", required=True)
    parser.add_argument("--frontend-image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package(args.output, args.version, args.repository, args.commit, args.backend_image, args.frontend_image)
    print(f"Prepared {args.version} installer artifacts in {args.output}.")


if __name__ == "__main__":
    main()
