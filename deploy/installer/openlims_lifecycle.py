"""Image-based installations and resumable upgrades; Python standard library only."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import socket
import subprocess
import tarfile
import tempfile
import urllib.request
import urllib.parse

DEFAULT_REPOSITORY = "Mokey2002/OpenLIMS"
TEMPLATES = Path(__file__).resolve().parent
TOOL_ROOT = TEMPLATES.parent
REQUIRED_FILES = {"openlims", "installer/openlims_lifecycle.py", "installer/compose.yml",
                  "installer/demo-compose.yml", "installer/Caddyfile"}
APPLICATION_SERVICES = ("caddy", "web", "worker", "assistant-monitor", "api")
LEGACY_HASHES = {"compose.yml": "4534ddf1163d6cfb72e49afbf9e049a76bb0d6fb7dd6ed25545fb09db7b944cb",
                 "Caddyfile": "bdacf6f6f3e4a8bc082ecf51a1c984cb8f8d27d8b2fe487acd76a14029213790"}
VERSION_PATTERN = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z")
IMAGE_PATTERN = re.compile(r"[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}\Z")
MAX_MANIFEST = 1024 * 1024
MAX_BUNDLE = 16 * 1024 * 1024


def version(value):
    if not VERSION_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError("Use a stable release version, such as v0.78.0.")
    return value


def version_tuple(value):
    return tuple(map(int, VERSION_PATTERN.fullmatch(version(value)).groups()))


def repository(value):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value) or ".." in value:
        raise argparse.ArgumentTypeError("Use a GitHub owner/repository name.")
    return value


def port(value):
    value = int(value)
    if not 1024 <= value <= 65535:
        raise argparse.ArgumentTypeError("Choose a local port from 1024 to 65535.")
    return value


def digest(content):
    return hashlib.sha256(content).hexdigest()


def file_digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def read_private(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise RuntimeError(f"{path.name} must be a private regular file (0600).")
    return path.read_bytes()


def atomic_write(path, content, mode=0o600):
    if path.is_symlink():
        raise RuntimeError(f"Refusing to replace symlink {path.name}.")
    data = content.encode() if isinstance(content, str) else content
    descriptor, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, value):
    atomic_write(path, json.dumps(value, sort_keys=True, indent=2) + "\n")


def read_json(path):
    data = read_private(path)
    if len(data) > MAX_MANIFEST:
        raise RuntimeError("Installation metadata exceeds its supported size.")
    result = json.loads(data)
    if not isinstance(result, dict):
        raise RuntimeError("Installation metadata must be an object.")
    return result


def private_directory(path):
    if path.is_symlink():
        raise RuntimeError("Installation directories must not contain redirected paths.")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def read_env(root):
    values = {}
    for line in read_private(root / ".env").decode().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in values:
            raise RuntimeError("Configuration has an invalid or duplicate setting; review it before continuing.")
        values[key] = value
    required = {"POSTGRES_PASSWORD", "DJANGO_SECRET_KEY", "DATABASE_URL", "DJANGO_DEBUG",
                "OPENLIMS_BACKEND_IMAGE", "OPENLIMS_FRONTEND_IMAGE"}
    if not required <= values.keys() or values["DJANGO_DEBUG"] != "false":
        raise RuntimeError("Configuration is incomplete or enables debug mode.")
    database = urllib.parse.urlparse(values["DATABASE_URL"])
    if (database.scheme not in ("postgres", "postgresql") or database.hostname != "db"
            or database.port not in (None, 5432) or database.path != "/openlims"
            or database.username != "openlims"
            or urllib.parse.unquote(database.password or "") != values["POSTGRES_PASSWORD"]):
        raise RuntimeError("This updater requires the installation's managed PostgreSQL database. External databases need a separate upgrade procedure.")
    return values


def write_env(root, values):
    if any("\n" in str(value) or "\r" in str(value) for value in values.values()):
        raise RuntimeError("Configuration values cannot contain newlines.")
    atomic_write(root / ".env", "".join(f"{key}={value}\n" for key, value in values.items()))


def fetch(url, limit):
    if not url.startswith("https://github.com/"):
        raise RuntimeError("Release downloads must use GitHub HTTPS URLs.")
    with urllib.request.urlopen(url, timeout=60) as response:
        if not response.geturl().startswith("https://"):
            raise RuntimeError("A release download redirected away from HTTPS.")
        content = response.read(limit + 1)
    if len(content) > limit:
        raise RuntimeError("Release download exceeds its supported size.")
    return content


def validate_release(data, expected_repository=None, expected_version=None):
    if not isinstance(data, dict) or data.get("schema") != 1:
        raise RuntimeError("Unsupported release manifest.")
    if not isinstance(data.get("version"), str) or not VERSION_PATTERN.fullmatch(data["version"]):
        raise RuntimeError("The manifest must select a stable release version.")
    try:
        repository(data.get("repository", ""))
    except (TypeError, argparse.ArgumentTypeError):
        raise RuntimeError("The manifest has an invalid repository.") from None
    if expected_version and data["version"] != expected_version:
        raise RuntimeError("The release manifest does not match the requested version.")
    if expected_repository and data["repository"].lower() != expected_repository.lower():
        raise RuntimeError("The release belongs to a different repository.")
    if not isinstance(data.get("commit"), str) or not re.fullmatch(r"[a-f0-9]{40}", data["commit"]):
        raise RuntimeError("The release must identify its source commit.")
    images = data.get("images", {})
    if not isinstance(images, dict) or set(images) != {"backend", "frontend"} or not all(isinstance(ref, str) and IMAGE_PATTERN.fullmatch(ref) for ref in images.values()):
        raise RuntimeError("Both application images must be pinned with immutable SHA-256 digests.")
    if (not isinstance(data.get("platforms"), list) or not all(isinstance(item, str) for item in data["platforms"])
            or sorted(data["platforms"]) != ["linux/amd64", "linux/arm64"]):
        raise RuntimeError("The release must support linux/amd64 and linux/arm64.")
    files = data.get("files", {})
    if not isinstance(files, dict) or not REQUIRED_FILES <= files.keys():
        raise RuntimeError("The release is missing installer files.")
    for name, checksum in files.items():
        if not isinstance(name, str):
            raise RuntimeError("Release file names must be strings.")
        path = PurePosixPath(name)
        if (path.is_absolute() or ".." in path.parts or "\\" in name or str(path) != name
                or not (name == "openlims" or name.startswith("installer/"))
                or not re.fullmatch(r"[a-f0-9]{64}", str(checksum))):
            raise RuntimeError("Invalid release file or checksum.")
    if "bundle" in data:
        bundle = data["bundle"]
        if (not isinstance(bundle, dict) or bundle.get("name") != f"openlims-{data['version']}.tar.gz"
                or not re.fullmatch(r"[a-f0-9]{64}", str(bundle.get("sha256", "")))):
            raise RuntimeError("Invalid release archive metadata.")
    return data


def load_release(requested_version=None, manifest=None, selected_repository=DEFAULT_REPOSITORY):
    repository(selected_repository)
    if manifest:
        path = Path(manifest).resolve()
        content = path.read_bytes()
        origin = str(path)
    elif (TOOL_ROOT / "release.json").is_file():
        path = TOOL_ROOT / "release.json"
        bundled = json.loads(path.read_bytes())
        if not requested_version or bundled.get("version") == requested_version:
            content, origin = path.read_bytes(), str(path)
        else:
            content, origin = None, None
    else:
        content, origin = None, None
    if content is None:
        if not requested_version:
            source_version = TOOL_ROOT.parent / "VERSION"
            if not source_version.is_file():
                raise RuntimeError("Specify --version or use an official release bundle.")
            requested_version = "v" + source_version.read_text().strip().removeprefix("v")
        version(requested_version)
        content = fetch(f"https://github.com/{selected_repository}/releases/download/{requested_version}/release.json", MAX_MANIFEST)
    if len(content) > MAX_MANIFEST:
        raise RuntimeError("Release manifest is too large.")
    data = validate_release(json.loads(content), selected_repository, requested_version)
    data["_origin"] = origin
    return data


def verify_files(directory, release):
    for name, checksum in release["files"].items():
        path = directory / name
        if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != checksum:
            raise RuntimeError(f"Installer file verification failed: {name}.")


def stage_release(root, release):
    staging = private_directory(root / ".staging")
    target = staging / release["version"]
    if target.exists():
        verify_files(target, release)
        return target
    temporary = Path(tempfile.mkdtemp(prefix="release-", dir=staging))
    try:
        origin = Path(release["_origin"]).parent if release.get("_origin") else None
        if origin and all((origin / name).is_file() for name in release["files"]):
            verify_files(origin, release)
            for name in release["files"]:
                destination = temporary / name
                private_directory(destination.parent)
                atomic_write(destination, (origin / name).read_bytes(), 0o700 if name == "openlims" else 0o600)
        else:
            bundle = release.get("bundle")
            if not bundle:
                raise RuntimeError("A release archive is required to install these tool files.")
            local = origin / bundle["name"] if origin else None
            content = local.read_bytes() if local and local.is_file() else fetch(
                f"https://github.com/{release['repository']}/releases/download/{release['version']}/{bundle['name']}", MAX_BUNDLE)
            if len(content) > MAX_BUNDLE or digest(content) != bundle["sha256"]:
                raise RuntimeError("Release archive checksum verification failed.")
            with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
                seen = set()
                total = 0
                for member in archive:
                    if member.name in seen or not member.isfile() or member.name not in set(release["files"]) | {"release.json"}:
                        raise RuntimeError("The release archive contains an unexpected file or link.")
                    seen.add(member.name)
                    total += member.size
                    if total > MAX_BUNDLE:
                        raise RuntimeError("Unpacked release exceeds its supported size.")
                    data = archive.extractfile(member).read(MAX_BUNDLE + 1)
                    if member.name == "release.json":
                        embedded = validate_release(json.loads(data), release["repository"], release["version"])
                        if any(embedded[key] != release[key] for key in ("images", "files", "commit", "platforms")):
                            raise RuntimeError("The embedded release manifest does not match the selected release.")
                        continue
                    if digest(data) != release["files"][member.name]:
                        raise RuntimeError("Installer file checksum verification failed.")
                    destination = temporary / member.name
                    private_directory(destination.parent)
                    atomic_write(destination, data, 0o700 if member.name == "openlims" else 0o600)
                if seen != set(release["files"]) | {"release.json"}:
                    raise RuntimeError("The release archive is incomplete.")
        verify_files(temporary, release)
        write_json(temporary / "release.json", {key: value for key, value in release.items() if not key.startswith("_") and key != "bundle"})
        os.replace(temporary, target)
        return target
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def execute(root, arguments, *, capture=False, output=None, input_file=None, interactive=False):
    if interactive:
        result = subprocess.run(arguments)
    else:
        log_path = root / "operations.log"
        if log_path.is_symlink() or (log_path.exists() and log_path.stat().st_mode & 0o077):
            raise RuntimeError("Operation log must not be a symlink.")
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, "ab") as log:
            result = subprocess.run(arguments, stdin=input_file if input_file else subprocess.DEVNULL,
                                    stdout=subprocess.PIPE if capture else output if output else log,
                                    stderr=log, text=capture)
    if result.returncode:
        raise RuntimeError(f"Container operation failed. Private details: {root / 'operations.log'}")
    return result.stdout if capture else None


def compose(root, state, *arguments, **kwargs):
    command = ["docker", "compose", "--project-name", state["project"], "--project-directory", str(root),
               "--env-file", str(root / ".env"), "-f", str(root / "compose.yml"), *arguments]
    return execute(root, command, **kwargs)


def current_state(root):
    state = read_json(root / "installation.json")
    if not re.fullmatch(r"openlims-[a-z0-9-]{6,60}", str(state.get("project", ""))):
        raise RuntimeError("Invalid managed installation identity.")
    if state.get("schema", 1) not in (1, 2):
        raise RuntimeError("Unsupported installation metadata version.")
    if state.get("schema", 1) == 1:
        state.update(schema=2, mode="production", version=None, repository=DEFAULT_REPOSITORY,
                     files=LEGACY_HASHES.copy(), phase="ready", initialized=True)
    if state.get("mode") not in ("demo", "production"):
        raise RuntimeError("Unsupported installation mode.")
    return state


def control_names(state):
    return {"compose.yml": "installer/demo-compose.yml" if state["mode"] == "demo" else "installer/compose.yml",
            **({"Caddyfile": "installer/Caddyfile"} if state["mode"] == "production" else {})}


def verify_controls(root, state, pending=None):
    for name, source in control_names(state).items():
        allowed = {state.get("files", {}).get(name)}
        if pending and pending.get("phase") in ("backed_up", "configured", "migrating", "starting", "complete"):
            allowed.add(pending["target"]["files"][source])
        path = root / name
        if not path.is_file() or path.is_symlink() or digest(path.read_bytes()) not in allowed:
            raise RuntimeError(f"Managed {name} changed. Preserve it and review the change before updating.")


def configured_services(root, state):
    return set(compose(root, state, "config", "--services", capture=True).splitlines())


def running_services(root, state):
    return set(compose(root, state, "ps", "--status", "running", "--services", capture=True).splitlines())


def application_services(root, state):
    available = configured_services(root, state)
    return [name for name in APPLICATION_SERVICES if name in available]


def stop_writers(root, state):
    ensure_setup_idle(root, state)
    services = application_services(root, state)
    compose(root, state, "stop", "--timeout", "120", *services)
    if running_services(root, state) & set(services):
        raise RuntimeError("Application writers are still running; backup and migration were not started.")


def ensure_setup_idle(root, state):
    active = execute(root, ["docker", "ps", "--filter", "label=com.docker.compose.project=" + state["project"],
                            "--filter", "label=com.docker.compose.service=setup", "--format", "{{.ID}}"], capture=True)
    if active.strip():
        raise RuntimeError("A setup or migration container is still running. Wait for it to finish or inspect it before resuming.")


def start_services(root, state, selected=None):
    ensure_setup_idle(root, state)
    services = list(selected) if selected is not None else application_services(root, state)
    if services:
        compose(root, state, "up", "-d", "--wait", "--wait-timeout", "240", *services)


def verify_images(root, release):
    for image in release["images"].values():
        labels = json.loads(execute(root, ["docker", "image", "inspect", image, "--format",
                                          '{{json .Config.Labels}}'], capture=True)) or {}
        if (labels.get("org.opencontainers.image.version") != release["version"]
                or labels.get("org.opencontainers.image.revision") != release["commit"]
                or labels.get("org.opencontainers.image.source", "").lower() != "https://github.com/" + release["repository"].lower()):
            raise RuntimeError("An image's version or source revision does not match the selected release.")


def pull_images(root, release):
    for image in release["images"].values():
        execute(root, ["docker", "pull", image])
    verify_images(root, release)


def verify_data_volumes(root, state):
    for name in ("database", "media"):
        result = json.loads(execute(root, ["docker", "volume", "inspect", f"{state['project']}_{name}"], capture=True))
        labels = result[0].get("Labels") or {}
        if labels.get("com.docker.compose.project") != state["project"] or labels.get("com.docker.compose.volume") != name:
            raise RuntimeError("Data volumes do not match this installation; refusing to create replacement volumes.")


def backup_data(root, state):
    verify_data_volumes(root, state)
    folder = private_directory(private_directory(root / "backups") /
                               (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(4)))
    for name in (".env", "installation.json", *control_names(state)):
        atomic_write(folder / name, read_private(root / name))
    for name in ("database.dump", "media.tar"):
        descriptor = os.open(folder / (name + ".partial"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            if name == "database.dump":
                compose(root, state, "exec", "-T", "db", "pg_dump", "--username=openlims", "--dbname=openlims", "--format=custom", output=output)
            else:
                image = read_env(root)["OPENLIMS_BACKEND_IMAGE"]
                execute(root, ["docker", "run", "--rm", "--network", "none", "--mount",
                               f"type=volume,source={state['project']}_media,target=/data,readonly", image,
                               "tar", "-C", "/data", "-cf", "-", "."], output=output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(folder / (name + ".partial"), folder / name)
    with (folder / "database.dump").open("rb") as source:
        compose(root, state, "exec", "-T", "db", "pg_restore", "--list", input_file=source)
    with tarfile.open(folder / "media.tar") as archive:
        for _ in archive:
            pass
    checksums = {path.name: file_digest(path) for path in folder.iterdir() if path.is_file()}
    write_json(folder / "backup.json", {"schema": 1, "complete": True, "project": state["project"],
                                       "version": state.get("version"), "files": checksums})
    return folder


def verify_backup(folder, project):
    record = read_json(folder / "backup.json")
    if record.get("complete") is not True or record.get("project") != project:
        raise RuntimeError("The update backup is incomplete or belongs to another installation.")
    for name, checksum in record["files"].items():
        if (PurePosixPath(name).name != name or (folder / name).is_symlink()
                or (folder / name).stat().st_mode & 0o077 or file_digest(folder / name) != checksum):
            raise RuntimeError("The update backup changed; migration was not started.")


def initialize_environment(root, state, release, args):
    if (root / ".env").exists():
        values = read_env(root)
        if (values["OPENLIMS_BACKEND_IMAGE"] != release["images"]["backend"]
                or values["OPENLIMS_FRONTEND_IMAGE"] != release["images"]["frontend"]):
            raise RuntimeError("Existing images differ. Use the update command for version changes.")
        if state["mode"] == "demo" and str(args.port) != values.get("OPENLIMS_HTTP_PORT"):
            raise RuntimeError("The existing demo uses a different port; its configuration was retained.")
        if state["mode"] == "production" and args.domain != values.get("OPENLIMS_DOMAIN"):
            raise RuntimeError("The existing installation uses a different domain.")
        return
    password = secrets.token_hex(32)
    values = {"OPENLIMS_BACKEND_IMAGE": release["images"]["backend"],
              "OPENLIMS_FRONTEND_IMAGE": release["images"]["frontend"],
              "POSTGRES_PASSWORD": password, "DJANGO_SECRET_KEY": secrets.token_hex(64),
              "DATABASE_URL": f"postgres://openlims:{password}@db:5432/openlims", "DJANGO_DEBUG": "false",
              "CELERY_BROKER_URL": "redis://redis:6379/0", "CELERY_RESULT_BACKEND": "redis://redis:6379/1",
              "CHANNEL_REDIS_URL": "redis://redis:6379/2"}
    if state["mode"] == "demo":
        values.update(OPENLIMS_DEMO_MODE="true", OPENLIMS_DEMO_PASSWORD=secrets.token_urlsafe(36),
                      OPENLIMS_HTTP_PORT=str(args.port), DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1,[::1]",
                      CSRF_TRUSTED_ORIGINS=f"http://localhost:{args.port},http://127.0.0.1:{args.port}",
                      JWT_COOKIE_SECURE="false", SESSION_COOKIE_SECURE="false", CSRF_COOKIE_SECURE="false")
    else:
        values.update(OPENLIMS_DOMAIN=args.domain, DJANGO_ALLOWED_HOSTS=f"{args.domain},127.0.0.1,localhost",
                      CSRF_TRUSTED_ORIGINS=f"https://{args.domain}", JWT_COOKIE_SECURE="true",
                      SESSION_COOKIE_SECURE="true", CSRF_COOKIE_SECURE="true")
    write_env(root, values)


def install_controls(root, state, release, staged):
    for target, source in control_names(state).items():
        atomic_write(root / target, (staged / source).read_bytes())
    values = read_env(root)
    values.update(OPENLIMS_BACKEND_IMAGE=release["images"]["backend"], OPENLIMS_FRONTEND_IMAGE=release["images"]["frontend"])
    write_env(root, values)


def install_tools(root, release, staged):
    tools = private_directory(root / ".tools")
    destination = tools / release["version"]
    if destination.exists():
        verify_files(destination, release)
    else:
        temporary = Path(tempfile.mkdtemp(prefix="tools-", dir=tools))
        try:
            for name in release["files"]:
                path = temporary / name
                private_directory(path.parent)
                atomic_write(path, (staged / name).read_bytes(), 0o700 if name == "openlims" else 0o600)
            write_json(temporary / "release.json", {key: value for key, value in release.items() if not key.startswith("_") and key != "bundle"})
            os.replace(temporary, destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    current = tools / "current"
    if current.exists() and not current.is_symlink():
        raise RuntimeError("The installer tools pointer was replaced; review it before continuing.")
    temporary_link = tools / ("current-" + secrets.token_hex(6))
    temporary_link.symlink_to(release["version"])
    os.replace(temporary_link, current)
    wrapper = '#!/bin/sh\nset -eu\nroot=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec python3 "$root/.tools/current/openlims" "$@" --directory "$root"\n'
    atomic_write(root / "openlims", wrapper, 0o700)


def doctor(root, state):
    compose(root, state, "exec", "-T", "api", "python", "manage.py", "check")
    compose(root, state, "exec", "-T", "worker", "sh", "-c",
            'celery -A config inspect ping -d worker@$HOSTNAME --timeout 5 | grep -q pong')
    missing = set(application_services(root, state)) - running_services(root, state)
    if missing:
        raise RuntimeError("Some application services are not running; inspect the private operation log.")
    values = read_env(root)
    if state["mode"] == "demo":
        url = f"http://127.0.0.1:{port(values['OPENLIMS_HTTP_PORT'])}"
    else:
        host = values.get("OPENLIMS_DOMAIN", "")
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]+", host):
            raise RuntimeError("Invalid configured domain.")
        url = f"https://{host}"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if state["mode"] == "demo" else urllib.request.build_opener()
    for path in ("/", "/health/"):
        with opener.open(url + path, timeout=20) as response:
            if response.status != 200:
                raise RuntimeError("Application HTTP health verification failed.")
    print(f"Application, worker and HTTP checks passed: {url}")
    return url


def initialize(root, args):
    mode = "demo" if args.command == "demo" else "production"
    release = load_release(args.version, args.manifest, args.repository or DEFAULT_REPOSITORY)
    marker = root / "installation.json"
    if marker.exists():
        state = current_state(root)
        if state["mode"] != mode or state.get("version") != release["version"]:
            raise RuntimeError("This directory contains a different installation. Use update for version changes.")
        if state.get("phase") == "ready":
            verify_controls(root, state)
            url = doctor(root, state)
            show_access(root, state, url)
            return
        if state.get("images") != release["images"]:
            raise RuntimeError("Release digests changed during initialization; the original configuration was retained.")
    else:
        if any(path.name != ".installer.lock" for path in root.iterdir()):
            raise RuntimeError("Use an empty directory; existing deployments are never adopted automatically.")
        if shutil.disk_usage(root).free < 2 * 1024 ** 3:
            raise RuntimeError("At least 2 GiB free space is required for the installation and images.")
        if mode == "demo":
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", args.port))
                except OSError:
                    raise RuntimeError("The demo port is occupied; select another --port.") from None
        else:
            if not args.domain:
                raise RuntimeError("Production installation requires --domain.")
            socket.getaddrinfo(args.domain, 443)
            for number in (80, 443):
                with socket.socket() as probe:
                    probe.bind(("0.0.0.0", number))
        state = {"schema": 2, "project": "openlims-" + mode + "-" + secrets.token_hex(6), "mode": mode,
                 "repository": release["repository"], "version": release["version"], "images": release["images"],
                 "phase": "initializing", "initialized": False, "files": {}}
        write_json(marker, state)
    staged = stage_release(root, release)
    initialize_environment(root, state, release, args)
    if state.get("files"):
        verify_controls(root, state)
    install_controls(root, state, release, staged)
    state["files"] = {name: release["files"][source] for name, source in control_names(state).items()}
    write_json(marker, state)
    print(f"Downloading {release['version']} images...", flush=True)
    compose(root, state, "config", "--quiet")
    compose(root, state, "--profile", "setup", "pull")
    verify_images(root, release)
    compose(root, state, "up", "-d", "--wait", "--wait-timeout", "180", "db", "redis")
    if not state["initialized"]:
        ensure_setup_idle(root, state)
        if running_services(root, state) & set(APPLICATION_SERVICES):
            raise RuntimeError("Application writers are active during initialization; stop them before resuming.")
        print("Initializing the database...", flush=True)
        compose(root, state, "run", "--rm", "--no-deps", "setup")
        if mode == "demo":
            compose(root, state, "run", "--rm", "--no-deps", "setup", "python", "manage.py", "bootstrap_demo")
        state["initialized"] = True
        write_json(marker, state)
    start_services(root, state)
    url = doctor(root, state)
    install_tools(root, release, staged)
    state["phase"] = "ready"
    write_json(marker, state)
    show_access(root, state, url)


def show_access(root, state, url):
    print(f"OpenLIMS {state['version']} is available at {url}")
    if state["mode"] == "demo":
        print("Demo username: director")
        print("Demo password: " + read_env(root)["OPENLIMS_DEMO_PASSWORD"])
    else:
        print(f"Create an administrator with: {root / 'openlims'} admin")
    print(f"Manage this installation with: {root / 'openlims'}")


def validate_journal(pending, state):
    phases = {"prepared", "stopped", "backed_up", "configured", "migrating", "starting"}
    if (pending.get("schema") != 1 or pending.get("project") != state["project"]
            or pending.get("phase") not in phases or not isinstance(pending.get("target"), dict)):
        raise RuntimeError("The update checkpoint is incomplete or belongs to another installation. Review update.json and its backups.")
    validate_release(pending["target"], state["repository"])
    if pending["phase"] not in {"prepared", "stopped"}:
        backup = pending.get("backup")
        if (not isinstance(backup, str) or not backup.startswith("backups/")
                or ".." in PurePosixPath(backup).parts or PurePosixPath(backup).is_absolute()):
            raise RuntimeError("The update checkpoint has an invalid backup location.")


def update(root, state, args):
    read_env(root)
    ensure_setup_idle(root, state)
    journal_path = root / "update.json"
    pending = read_json(journal_path) if journal_path.exists() else None
    if pending is not None:
        validate_journal(pending, state)
    if pending:
        if not args.resume:
            raise RuntimeError(f"An update is pending at {pending['phase']}. Resume with --version {pending['target']['version']} --resume.")
        if args.version and args.version != pending["target"]["version"]:
            raise RuntimeError("Resume must use the same release as the interrupted update.")
        release = validate_release(pending["target"], state["repository"], args.version)
        if args.manifest:
            supplied = load_release(args.version, args.manifest, state["repository"])
            if any(supplied[key] != release[key] for key in ("version", "images", "files", "commit")):
                raise RuntimeError("The resumed release differs from the original update.")
    else:
        if args.resume:
            raise RuntimeError("There is no interrupted update to resume.")
        if state.get("phase") != "ready":
            raise RuntimeError("Complete installation before updating.")
        if not args.version and not args.manifest:
            raise RuntimeError("Select the release with --version vX.Y.Z.")
        if args.version == state.get("version") and not args.manifest:
            doctor(root, state)
            print("This release is already installed; no data or services were changed.")
            return
        current_version = state.get("version")
        declared_version = getattr(args, "from_version", None)
        if not current_version:
            if not declared_version:
                raise RuntimeError("This legacy installation has no recorded version. Read its current footer and specify --from-version vX.Y.Z once.")
            current_version = declared_version
        elif declared_version and declared_version != current_version:
            raise RuntimeError("The declared source version differs from the recorded installation.")
        release = load_release(args.version, args.manifest, state["repository"])
        if version_tuple(release["version"]) <= version_tuple(current_version):
            if release["version"] == state["version"] and release["images"] == state.get("images"):
                doctor(root, state)
                return
            raise RuntimeError("Updates must move to a newer version; database downgrades are not automatic.")
        verify_controls(root, state)
        verify_data_volumes(root, state)
        print(f"Downloading and verifying {release['version']} before stopping services...", flush=True)
        pull_images(root, release)
        stage_release(root, release)
        pending = {"schema": 1, "project": state["project"], "phase": "prepared", "target": release,
                   "previous_version": current_version, "previous_services": sorted(running_services(root, state) & set(APPLICATION_SERVICES))}
        write_json(journal_path, pending)
    if pending.get("schema") != 1 or pending.get("project") != state["project"]:
        raise RuntimeError("The update journal belongs to a different installation.")
    verify_controls(root, state, pending)
    staged = stage_release(root, release)
    verify_images(root, release)
    phase = pending["phase"]
    if phase in ("prepared", "stopped"):
        print("Stopping application writers and making a consistent backup...", flush=True)
        stop_writers(root, state)
        pending["phase"] = "stopped"
        write_json(journal_path, pending)
        compose(root, state, "up", "-d", "--wait", "--wait-timeout", "180", "db", "redis")
        backup = backup_data(root, state)
        pending.update(phase="backed_up", backup=str(backup.relative_to(root)))
        write_json(journal_path, pending)
    backup = (root / pending["backup"]).resolve()
    if not backup.is_relative_to(root / "backups"):
        raise RuntimeError("Invalid update backup location.")
    verify_backup(backup, state["project"])
    if pending["phase"] in ("backed_up", "configured", "migrating"):
        if running_services(root, state) & set(APPLICATION_SERVICES):
            raise RuntimeError("Application services were restarted during maintenance. Review backup freshness before resuming.")
        if pending["phase"] == "backed_up":
            install_controls(root, state, release, staged)
            pending["phase"] = "configured"
            write_json(journal_path, pending)
        compose(root, state, "config", "--quiet")
        pending["phase"] = "migrating"
        write_json(journal_path, pending)
        print("Applying database migrations; the backup is retained...", flush=True)
        ensure_setup_idle(root, state)
        compose(root, state, "run", "--rm", "--no-deps", "setup")
        pending["phase"] = "starting"
        write_json(journal_path, pending)
    if pending["phase"] != "starting":
        raise RuntimeError("Unsupported update checkpoint; inspect update.json before proceeding.")
    start_services(root, state)
    url = doctor(root, state)
    install_tools(root, release, staged)
    state.update(schema=2, version=release["version"], images=release["images"], phase="ready", initialized=True,
                 files={name: release["files"][source] for name, source in control_names(state).items()},
                 last_backup=str(backup.relative_to(root)))
    write_json(root / "installation.json", state)
    pending["phase"] = "complete"
    write_json(root / "last-update.json", pending)
    journal_path.unlink()
    print(f"Updated to {release['version']}: {url}")
    print(f"Database, uploads and previous configuration backup: {backup}")


def tool_version():
    bundled = TOOL_ROOT / "release.json"
    source = TOOL_ROOT.parent / "VERSION"
    if bundled.is_file():
        return validate_release(json.loads(bundled.read_bytes()))["version"]
    if source.is_file():
        return version("v" + source.read_text().strip().removeprefix("v"))
    return None


def record_legacy_install(root, project):
    values = read_env(root)
    write_json(root / "installation.json", {
        "schema": 2, "project": project, "mode": "production", "version": None,
        "repository": DEFAULT_REPOSITORY, "phase": "ready", "initialized": True,
        "images": {"backend": values["OPENLIMS_BACKEND_IMAGE"], "frontend": values["OPENLIMS_FRONTEND_IMAGE"]},
        "files": {name: digest((root / name).read_bytes()) for name in ("compose.yml", "Caddyfile")},
    })


def main(args):
    root = args.directory.resolve()
    if root in (Path("/"), Path.home()) or (root == Path.cwd() and not (root / "installation.json").is_file()):
        raise RuntimeError("Use a dedicated installation directory.")
    if not shutil.which("docker"):
        raise RuntimeError("Install Docker Engine/Desktop and Docker Compose v2 first.")
    private_directory(root)
    for command in (["docker", "info"], ["docker", "compose", "version"]):
        if subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            raise RuntimeError("Docker Engine and Docker Compose v2 must be running.")
    lock_path = root / ".installer.lock"
    if lock_path.is_symlink():
        raise RuntimeError("Installation lock must not be a symlink.")
    with lock_path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another installation operation is running.") from None
        if args.command in ("demo", "install"):
            initialize(root, args)
            return
        state = current_state(root)
        read_env(root)
        supported = tool_version()
        if state.get("version") and supported and version_tuple(state["version"]) > version_tuple(supported):
            raise RuntimeError(f"Use the newer installed tools: {root / 'openlims'}. Older controllers cannot safely manage this release.")
        if args.command == "update":
            try:
                update(root, state, args)
            except (OSError, ValueError, RuntimeError) as error:
                journal = root / "update.json"
                if journal.exists():
                    pending = read_json(journal)
                    try:
                        log_path = root / "operations.log"
                        if not log_path.is_symlink() and (not log_path.exists() or not log_path.stat().st_mode & 0o077):
                            descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                            with os.fdopen(descriptor, "a") as log:
                                log.write(f"\nUpdate checkpoint {pending['phase']}: {error}\n")
                    except OSError:
                        pass
                    raise RuntimeError(f"Update paused at {pending['phase']}. Data and backups were retained. "
                                       f"Resume with: {root / 'openlims'} update --version {pending['target']['version']} --resume. "
                                       f"Private details: {root / 'operations.log'}") from error
                raise
            return
        if (root / "update.json").exists():
            raise RuntimeError("Resume the pending update before starting services or changing accounts.")
        verify_controls(root, state)
        if args.command == "doctor":
            doctor(root, state)
        elif args.command == "admin":
            compose(root, state, "exec", "api", "python", "manage.py", "createsuperuser", interactive=True)
        elif args.command == "stop":
            stop_writers(root, state)
            print("Application services stopped. Database, broker and data volumes were retained.")
        elif args.command == "start":
            start_services(root, state)
            doctor(root, state)
        elif args.command == "backup":
            before = sorted(running_services(root, state) & set(APPLICATION_SERVICES))
            stop_writers(root, state)
            try:
                compose(root, state, "up", "-d", "--wait", "--wait-timeout", "180", "db", "redis")
                folder = backup_data(root, state)
                print(f"Consistent database, uploads and configuration backup: {folder}")
            finally:
                start_services(root, state, before)
        else:
            raise RuntimeError("Unsupported installation command.")
