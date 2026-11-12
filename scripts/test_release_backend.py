#!/usr/bin/env python3
"""Run the backend suite inside the actual native image with isolated PostgreSQL/Redis."""
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile


def check_image(image, work_directory=None):
    root = Path(tempfile.mkdtemp(prefix="openlims-image-tests-", dir=work_directory))
    project = "openlims-release-unit-" + secrets.token_hex(6)
    password, signing_key = secrets.token_hex(32), secrets.token_hex(64)
    services = {"services": {
        "db": {"image": "postgres:16", "environment": {"POSTGRES_USER": "openlims", "POSTGRES_DB": "openlims", "POSTGRES_PASSWORD": password},
               "volumes": ["database:/var/lib/postgresql/data"],
               "healthcheck": {"test": ["CMD", "pg_isready", "-U", "openlims"], "interval": "2s", "timeout": "5s", "retries": 60}},
        "redis": {"image": "redis:7-alpine", "healthcheck": {"test": ["CMD", "redis-cli", "ping"], "interval": "2s", "timeout": "5s", "retries": 60}},
        "tests": {"image": image, "working_dir": "/app", "command": ["pytest", "-q", "--reuse-db"],
                  "environment": {"DATABASE_URL": f"postgres://openlims:{password}@db:5432/openlims", "DJANGO_SECRET_KEY": signing_key,
                                  "DJANGO_DEBUG": "true", "DJANGO_ALLOWED_HOSTS": "localhost,127.0.0.1,testserver",
                                  "INSTRUMENT_API_KEY": "my-shared-lab-instrument-key", "REQUIRE_POSTGRES_TESTS": "1", "PGOPTIONS": "-c jit=off"},
                  "depends_on": {"db": {"condition": "service_healthy"}, "redis": {"condition": "service_healthy"}}},
    }, "volumes": {"database": {}}}
    path = root / "compose.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(services, handle)
    compose = ["docker", "compose", "--project-name", project, "--project-directory", str(root), "-f", str(path)]
    log = root / "backend-tests.log"
    log.touch(mode=0o600)
    try:
        with log.open("ab") as output:
            subprocess.run(compose + ["up", "-d", "--wait", "--wait-timeout", "180", "db", "redis"], stdout=output, stderr=output, check=True)
            result = subprocess.run(compose + ["run", "--rm", "tests"], stdout=output, stderr=output)
        text = log.read_text(errors="replace").replace(password, "[redacted]").replace(signing_key, "[redacted]")
        print(text[-18000:], flush=True)
        if result.returncode:
            raise RuntimeError("The actual backend image failed its PostgreSQL regression suite.")
    finally:
        with log.open("ab") as output:
            subprocess.run(compose + ["down", "--volumes", "--remove-orphans"], stdout=output, stderr=output)
        print(f"Private image-test diagnostics: {root}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-image", required=True)
    parser.add_argument("--work-directory", type=Path)
    args = parser.parse_args()
    check_image(args.backend_image, args.work_directory)


if __name__ == "__main__":
    main()
