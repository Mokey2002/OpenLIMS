#!/usr/bin/env python3
"""Exercise real release images, demo startup, interrupted upgrade and backup restore."""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/installer"))
import openlims_lifecycle as lifecycle
from package_release import package
import release_diagnostics


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def restore_backup(run, log, name, backup, sample_code, work):
    # The official image's temporary server accepts Unix-socket connections while
    # init scripts run. A delay makes the old premature-readiness race repeatable.
    init = work / "restore-readiness.sh"
    init.write_text("sleep 3\ntouch /tmp/openlims-initialization-complete\n")
    init.chmod(0o644)
    password = secrets.token_hex(24)
    run(["docker", "run", "-d", "--name", name, "-e", "POSTGRES_PASSWORD=" + password,
         "-e", "POSTGRES_DB=openlims", "-e", "POSTGRES_USER=openlims", "--mount",
         f"type=bind,source={init.resolve()},target=/docker-entrypoint-initdb.d/001-readiness.sh,readonly", "postgres:16"])
    for attempt in range(60):
        with log.open("ab") as output:
            result = subprocess.run(["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "openlims", "-d", "openlims"],
                                    stdout=output, stderr=output)
        if result.returncode == 0:
            break
        if attempt == 59:
            raise RuntimeError("Restore database did not start.")
        time.sleep(0.5)
    run(["docker", "exec", name, "test", "-f", "/tmp/openlims-initialization-complete"])
    with (backup / "database.dump").open("rb") as source:
        run(["docker", "exec", "-i", name, "pg_restore", "-U", "openlims", "-d", "openlims", "--exit-on-error", "--no-owner"], input_file=source)
    restored = run(["docker", "exec", name, "psql", "-U", "openlims", "-d", "openlims", "-Atc",
                    f"SELECT sample_id FROM samples_sample WHERE sample_id = '{sample_code}'"], capture=True)
    assert restored.strip() == sample_code
    with tarfile.open(backup / "media.tar") as archive:
        assert archive.extractfile("./release-smoke.txt").read() == b"protein observations retained"


def smoke(args):
    work = Path(tempfile.mkdtemp(prefix="openlims-release-smoke-", dir=args.work_directory))
    log = work / "smoke.log"
    log.touch(mode=0o600)
    identifier = secrets.token_hex(6)
    registry, restore = "openlims-smoke-registry-" + identifier, "openlims-smoke-restore-" + identifier
    installation = work / "instance"
    project = None

    def run(command, *, capture=False, expected_failure=False, input_file=None):
        with log.open("ab") as output:
            result = subprocess.run([str(item) for item in command], stdin=input_file or subprocess.DEVNULL,
                                    stdout=subprocess.PIPE if capture else output, stderr=output, text=capture)
        if bool(result.returncode) != bool(expected_failure):
            raise RuntimeError(f"Smoke operation failed; private diagnostics: {log}")
        return result.stdout if capture else None

    def dc(*parts, **kwargs):
        return run(["docker", "compose", "--project-name", project, "--project-directory", installation,
                    "--env-file", installation / ".env", "-f", installation / "compose.yml", *parts], **kwargs)

    def cli(*parts, expected_failure=False):
        installed = installation / "openlims"
        command = [installed, *parts] if installed.is_file() else [sys.executable, ROOT / "deploy/openlims", *parts, "--directory", installation]
        return run(command, expected_failure=expected_failure)

    def image_pin(image, tag):
        run(["docker", "tag", image, tag])
        run(["docker", "push", tag])
        refs = json.loads(run(["docker", "image", "inspect", tag, "--format", "{{json .RepoDigests}}"], capture=True))
        name = tag.rsplit(":", 1)[0]
        return next(ref for ref in refs if ref.startswith(name + "@"))

    try:
        print("Checking scientific tools in the native backend image...", flush=True)
        run(["docker", "run", "--rm", args.backend_image, "sh", "-c",
             "python -c 'import numpy, pyopenms; print(pyopenms.__version__)' && blastn -version && blastp -version && makeblastdb -version && clustalo --version"])
        labels = json.loads(run(["docker", "image", "inspect", args.backend_image, "--format", "{{json .Config.Labels}}"], capture=True))
        source_commit = labels["org.opencontainers.image.revision"]
        source_repository = lifecycle.repository(labels["org.opencontainers.image.source"].removeprefix("https://github.com/"))
        registry_port = free_port()
        run(["docker", "run", "-d", "--name", registry, "-p", f"127.0.0.1:{registry_port}:5000", "registry:2"])
        address = f"127.0.0.1:{registry_port}"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for attempt in range(50):
            try:
                with opener.open(f"http://{address}/v2/", timeout=2):
                    break
            except OSError:
                if attempt == 49:
                    raise RuntimeError("The isolated test registry did not start.")
                time.sleep(0.2)
        images = {"backend": image_pin(args.backend_image, f"{address}/openlims-backend:{args.version}"),
                  "frontend": image_pin(args.frontend_image, f"{address}/openlims-frontend:{args.version}")}
        initial = work / "initial"
        package(initial, args.version, source_repository, source_commit, images["backend"], images["frontend"])
        http_port = free_port()
        print("Launching an isolated demo with the real installer...", flush=True)
        cli("demo", "--version", args.version, "--manifest", initial / "release.json", "--port", str(http_port), "--repository", source_repository)
        state = lifecycle.current_state(installation)
        project = state["project"]
        original = lifecycle.read_env(installation)
        base_url = f"http://127.0.0.1:{http_port}"
        cookies = http.cookiejar.CookieJar()
        client = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPCookieProcessor(cookies))

        def request(path, body=None):
            headers = {"Origin": base_url, "Referer": base_url + "/"}
            token = next((cookie.value for cookie in cookies if cookie.name == "csrftoken"), None)
            if token:
                headers["X-CSRFToken"] = token
            if body is not None:
                headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode() if body is not None else None
            with client.open(urllib.request.Request(base_url + path, data=data, headers=headers), timeout=30) as response:
                content = response.read()
                return json.loads(content) if content else None

        request("/api/v1/auth/csrf/")
        request("/api/v1/auth/login/", {"username": "director", "password": original["OPENLIMS_DEMO_PASSWORD"]})
        sample_code = "RELEASE-" + identifier
        created = request("/api/v1/samples/", {"sample_id": sample_code, "sample_type": "GENERAL", "status": "RECEIVED"})
        assert created["sample_id"] == sample_code
        health = request("/health/")
        assert all(health[key] for key in ("db_ok", "redis_ok", "blastn_ok", "clustalo_ok", "pyopenms_ok"))
        upload_code = "from pathlib import Path; Path('/app/media/release-smoke.txt').write_text('protein observations retained')"
        dc("exec", "-T", "api", "python", "-c", upload_code)
        with client.open(base_url + "/media/release-smoke.txt", timeout=20) as response:
            assert response.read() == b"protein observations retained"
        task_code = "from config.celery import app; r=app.send_task('celery.accumulate', args=['release-smoke']); assert r.get(timeout=30)[0]=='release-smoke'"
        dc("exec", "-T", "api", "python", "manage.py", "shell", "-c", task_code)
        cli("demo", "--version", args.version, "--manifest", initial / "release.json", "--port", str(http_port), "--repository", source_repository)
        assert lifecycle.read_env(installation) == original

        next_tuple = list(lifecycle.version_tuple(args.version))
        next_tuple[2] += 1
        target_version = "v" + ".".join(map(str, next_tuple))
        derived = work / "derived"
        derived.mkdir()
        latest_core = sorted((ROOT / "backend/core/migrations").glob("[0-9]*.py"))[-1].stem
        migration = f'''import os
from django.db import migrations

def apply(apps, schema_editor):
    if os.environ.get("OPENLIMS_RELEASE_SMOKE_FAIL") == "true":
        raise RuntimeError("Deliberate smoke-test interruption before the schema change")
    schema_editor.execute("CREATE TABLE release_smoke_probe (value text NOT NULL)")
    schema_editor.execute("INSERT INTO release_smoke_probe VALUES ('upgrade migrated')")

class Migration(migrations.Migration):
    dependencies = [("core", "{latest_core}")]
    operations = [migrations.RunPython(apply)]
'''
        (derived / "9999_release_smoke.py").write_text(migration)
        (derived / "Dockerfile").write_text(f'''FROM {args.backend_image}
COPY 9999_release_smoke.py /app/core/migrations/9999_release_smoke.py
ENV OPENLIMS_VERSION={target_version}
LABEL org.opencontainers.image.version={target_version}
''')
        backend_target = "openlims-smoke-upgrade-backend:" + identifier
        frontend_target = "openlims-smoke-upgrade-frontend:" + identifier
        print("Building a synthetic next release with a real schema migration...", flush=True)
        run(["docker", "build", "-t", backend_target, derived])
        # Reuse the already built assets; the synthetic version marker is sufficient for the update protocol test.
        # Real published frontend releases are compiled with their own version build argument.
        (derived / "Dockerfile.frontend").write_text(f"FROM {args.frontend_image}\nLABEL org.opencontainers.image.version={target_version}\n")
        run(["docker", "build", "-f", derived / "Dockerfile.frontend", "-t", frontend_target, derived])
        target_images = {"backend": image_pin(backend_target, f"{address}/openlims-backend:{target_version}"),
                         "frontend": image_pin(frontend_target, f"{address}/openlims-frontend:{target_version}")}
        target = work / "target"
        package(target, target_version, source_repository, source_commit, target_images["backend"], target_images["frontend"])
        configured = lifecycle.read_env(installation)
        configured["OPENLIMS_RELEASE_SMOKE_FAIL"] = "true"
        configured["CUSTOM_SETTING_TO_RETAIN"] = "scientific-configuration"
        lifecycle.write_env(installation, configured)
        print("Interrupting the upgrade and checking maintenance/backup state...", flush=True)
        cli("update", "--version", target_version, "--manifest", target / "release.json", expected_failure=True)
        pending = lifecycle.read_json(installation / "update.json")
        assert pending["phase"] == "migrating"
        assert not set(dc("ps", "--status", "running", "--services", capture=True).splitlines()) & set(lifecycle.APPLICATION_SERVICES)
        backup = installation / pending["backup"]
        lifecycle.verify_backup(backup, project)
        configured = lifecycle.read_env(installation)
        configured.pop("OPENLIMS_RELEASE_SMOKE_FAIL")
        lifecycle.write_env(installation, configured)
        print("Resuming the same upgrade and verifying scientific data and credentials...", flush=True)
        cli("update", "--version", target_version, "--resume")
        after = lifecycle.read_env(installation)
        for key, value in original.items():
            if key not in ("OPENLIMS_BACKEND_IMAGE", "OPENLIMS_FRONTEND_IMAGE"):
                assert after[key] == value, key
        assert after["CUSTOM_SETTING_TO_RETAIN"] == "scientific-configuration"
        assert lifecycle.current_state(installation)["version"] == target_version
        assert request(f"/api/v1/samples/{created['id']}/")["sample_id"] == sample_code
        dc("exec", "-T", "api", "python", "-c", "from pathlib import Path; assert Path('/app/media/release-smoke.txt').read_text()=='protein observations retained'")
        with client.open(base_url + "/media/release-smoke.txt", timeout=20) as response:
            assert response.read() == b"protein observations retained"
        dc("exec", "-T", "db", "psql", "-U", "openlims", "-d", "openlims", "-c", "SELECT * FROM release_smoke_probe")
        dc("exec", "-T", "api", "python", "manage.py", "shell", "-c", task_code)
        before = list((installation / "backups").iterdir())
        cli("update", "--version", target_version)
        assert list((installation / "backups").iterdir()) == before
        assert not (installation / "update.json").exists()
        cli("update", "--version", args.version, "--manifest", initial / "release.json", expected_failure=True)
        assert lifecycle.current_state(installation)["version"] == target_version

        print("Restoring the pre-upgrade backup into a separate database...", flush=True)
        restore_backup(run, log, restore, backup, sample_code, work)
        print("Release smoke passed: scientific tools, demo/login/API, Celery, failed/resumed migration, retained data and backup restore.", flush=True)
    finally:
        failure = sys.exc_info()[1]
        if (installation / "installation.json").is_file():
            # Only the fresh, randomly named installation created in this smoke directory is removed.
            state = lifecycle.current_state(installation)
            if state["mode"] == "demo" and installation.is_relative_to(work) and state["project"].startswith("openlims-demo-"):
                project = state["project"]
                containers = []
                if failure is not None:
                    # Capture state/health and application logs, never container environment/configuration.
                    with log.open("ab") as output:
                        ids = subprocess.run(["docker", "compose", "--project-name", project,
                                              "--project-directory", str(installation), "--env-file", str(installation / ".env"),
                                              "-f", str(installation / "compose.yml"), "ps", "--all", "--quiet"],
                                             stdout=subprocess.PIPE, stderr=output, text=True).stdout.splitlines()
                        for identifier in ids:
                            status = subprocess.run(["docker", "inspect", "--format", "{{.Name}} {{json .State}}", identifier],
                                                    stdout=subprocess.PIPE, stderr=output, text=True).stdout
                            recent = subprocess.run(["docker", "logs", "--tail", "30", identifier],
                                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
                            containers.append(("Container " + identifier, status + recent))
                            output.write((status + recent).encode())
                if failure is not None:
                    release_diagnostics.publish(args.diagnostics or work / "diagnostics.txt", [
                        ("Smoke failure", str(failure)),
                        ("Installer operations", release_diagnostics.read_log(installation / "operations.log")),
                        ("Smoke and container diagnostics", release_diagnostics.read_log(log)),
                    ] + containers, release_diagnostics.environment_secrets(installation / ".env"))
                with log.open("ab") as output:
                    subprocess.run(["docker", "compose", "--project-name", project, "--project-directory", str(installation),
                                    "--env-file", str(installation / ".env"), "-f", str(installation / "compose.yml"),
                                    "down", "--volumes", "--remove-orphans"], stdout=output, stderr=output)
        elif failure is not None:
            release_diagnostics.publish(args.diagnostics or work / "diagnostics.txt",
                                        [("Smoke failure", str(failure)), ("Smoke operations", release_diagnostics.read_log(log))])
        with log.open("ab") as output:
            subprocess.run(["docker", "rm", "-f", "-v", registry, restore], stdout=output, stderr=output)
        print(f"Private smoke diagnostics retained at {work}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-image", required=True)
    parser.add_argument("--frontend-image", required=True)
    parser.add_argument("--version", type=lifecycle.version, required=True)
    parser.add_argument("--work-directory", type=Path)
    parser.add_argument("--diagnostics", type=Path, help="Write a redacted failure report for CI artifacts")
    smoke(parser.parse_args())


if __name__ == "__main__":
    main()
