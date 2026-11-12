import argparse
import copy
import fcntl
from importlib.machinery import SourceFileLoader
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import sys

import openlims_lifecycle as lifecycle

ROOT = Path(__file__).resolve().parents[2]
packager = SourceFileLoader("openlims_release_packager", str(ROOT / "scripts/package_release.py")).load_module()


def pins(character):
    return {"backend": "example/backend@sha256:" + character * 64,
            "frontend": "example/frontend@sha256:" + character * 64}


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "installation"
        self.root.mkdir(mode=0o700)
        self.releases = {}
        for version, character in [("v0.78.0", "a"), ("v0.78.1", "b")]:
            output = self.base / version
            images = pins(character)
            release = packager.package(output, version, lifecycle.DEFAULT_REPOSITORY, "a" * 40,
                                       images["backend"], images["frontend"])
            release["_origin"] = str(output / "release.json")
            self.releases[version] = release
        first = self.releases["v0.78.0"]
        self.state = {"schema": 2, "project": "openlims-demo-123456789abc", "mode": "demo",
                      "version": first["version"], "images": first["images"], "repository": lifecycle.DEFAULT_REPOSITORY,
                      "phase": "ready", "initialized": True, "files": {}}
        self.args = argparse.Namespace(command="update", directory=self.root, version="v0.78.1",
                                       manifest=Path(self.releases["v0.78.1"]["_origin"]), repository=None,
                                       resume=False, port=8080, domain=None)
        lifecycle.initialize_environment(self.root, self.state, first, self.args)
        stage = lifecycle.stage_release(self.root, first)
        lifecycle.install_controls(self.root, self.state, first, stage)
        self.state["files"] = {name: first["files"][source] for name, source in lifecycle.control_names(self.state).items()}
        lifecycle.write_json(self.root / "installation.json", self.state)
        values = lifecycle.read_env(self.root)
        values["CUSTOM_SMTP_SETTING"] = "keep-this-configuration"
        lifecycle.write_env(self.root, values)
        self.original = values.copy()
        self.running = {"api", "worker", "assistant-monitor", "web", "db", "redis"}
        self.commands = []
        self.fail = None
        self.images = {ref: version for version, release in self.releases.items() for ref in release["images"].values()}
        self.runner = patch.object(lifecycle, "execute", side_effect=self.execute)
        self.runner.start()
        self.addCleanup(self.runner.stop)
        self.health = patch.object(lifecycle, "doctor", return_value="http://127.0.0.1:8080")
        self.health.start()
        self.addCleanup(self.health.stop)
        self.output = patch("builtins.print")
        self.output.start()
        self.addCleanup(self.output.stop)

    def execute(self, root, command, **kwargs):
        self.commands.append(command)
        if command[:2] == ["docker", "ps"]:
            return "running-setup\n" if self.fail == "setup-running" else ""
        if command[:2] == ["docker", "pull"]:
            if self.fail == "pull":
                raise RuntimeError("Registry unavailable")
        elif command[:3] == ["docker", "image", "inspect"]:
            return json.dumps({"org.opencontainers.image.version": self.images[command[3]],
                               "org.opencontainers.image.revision": "a" * 40,
                               "org.opencontainers.image.source": "https://github.com/" + lifecycle.DEFAULT_REPOSITORY})
        elif command[:3] == ["docker", "volume", "inspect"]:
            if self.fail == "volume":
                raise RuntimeError("Missing database volume")
            name = command[-1].split("_")[-1]
            return json.dumps([{"Labels": {"com.docker.compose.project": self.state["project"],
                                           "com.docker.compose.volume": name}}])
        elif command[:2] == ["docker", "run"]:
            content = io.BytesIO()
            with tarfile.open(fileobj=content, mode="w") as archive:
                entry = tarfile.TarInfo("scientific-upload.txt")
                data = b"preserve uploaded protein observations"
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
            kwargs["output"].write(content.getvalue())
        elif command[:2] == ["docker", "compose"]:
            parts = command[command.index("-f") + 2:]
            if parts == ["config", "--services"]:
                return "api\nworker\nassistant-monitor\nweb\ndb\nredis\nsetup\n"
            if parts[:1] == ["ps"]:
                return "\n".join(sorted(self.running))
            if parts[:1] == ["stop"]:
                self.running -= set(lifecycle.APPLICATION_SERVICES)
            elif parts[:1] == ["up"]:
                if self.fail == "start" and "api" in parts:
                    raise RuntimeError("Startup interrupted")
                services = parts[parts.index("--wait-timeout") + 2:]
                self.running.update(services)
            elif "pg_dump" in parts:
                if self.fail == "backup":
                    raise RuntimeError("Backup disk full")
                kwargs["output"].write(b"PGDMP scientific database snapshot")
            elif parts[:1] == ["run"] and "setup" in parts:
                if self.fail == "migrate":
                    raise RuntimeError("Migration interrupted")
        return "" if kwargs.get("capture") else None

    def invoke(self):
        lifecycle.update(self.root, lifecycle.current_state(self.root), self.args)

    def test_upgrade_preserves_secrets_settings_identity_and_upload_backup(self):
        self.invoke()
        state = lifecycle.current_state(self.root)
        self.assertEqual(state["project"], self.state["project"])
        self.assertEqual(state["version"], "v0.78.1")
        values = lifecycle.read_env(self.root)
        for key in set(self.original) - {"OPENLIMS_BACKEND_IMAGE", "OPENLIMS_FRONTEND_IMAGE"}:
            self.assertEqual(values[key], self.original[key], key)
        backup = self.root / state["last_backup"]
        lifecycle.verify_backup(backup, state["project"])
        with tarfile.open(backup / "media.tar") as archive:
            self.assertEqual(archive.extractfile("scientific-upload.txt").read(), b"preserve uploaded protein observations")
        self.assertFalse((self.root / "update.json").exists())
        self.assertTrue((self.root / "openlims").is_file())
        self.assertTrue((self.root / ".tools/current").is_symlink())
        self.assertTrue(all(path.stat().st_mode & 0o077 == 0 for path in backup.iterdir()))

    def test_writers_stop_before_backup_and_migration_finishes_before_startup(self):
        self.invoke()
        stop = next(i for i, command in enumerate(self.commands) if "stop" in command)
        backup = next(i for i, command in enumerate(self.commands) if "pg_dump" in command)
        migration = next(i for i, command in enumerate(self.commands) if "run" in command and "setup" in command)
        start = next(i for i, command in enumerate(self.commands) if "up" in command and "api" in command)
        self.assertLess(stop, backup)
        self.assertLess(backup, migration)
        self.assertLess(migration, start)
        self.assertFalse(any("bootstrap_demo" in command or "seed_demo" in command or "down" in command for command in self.commands))

    def test_failed_pull_does_not_stop_services_or_change_configuration(self):
        self.fail = "pull"
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.assertIn("api", self.running)
        self.assertEqual(lifecycle.read_env(self.root), self.original)
        self.assertFalse((self.root / "update.json").exists())
        self.assertFalse(any("stop" in command for command in self.commands))

    def test_a_surviving_setup_container_blocks_a_second_migration(self):
        self.fail = "setup-running"
        with self.assertRaisesRegex(RuntimeError, "still running"):
            self.invoke()
        self.assertTrue(all(command[:2] == ["docker", "ps"] for command in self.commands))
        self.assertEqual(lifecycle.read_env(self.root), self.original)

    def test_missing_data_volumes_never_create_replacement_storage(self):
        self.fail = "volume"
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.assertFalse(any("up" in command or "stop" in command for command in self.commands))
        self.assertEqual(lifecycle.read_env(self.root), self.original)

    def test_backup_failure_never_changes_images_or_starts_migrations(self):
        self.fail = "backup"
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.assertEqual(lifecycle.read_env(self.root), self.original)
        self.assertFalse(any("run" in command and "setup" in command for command in self.commands))
        self.assertEqual(lifecycle.read_json(self.root / "update.json")["phase"], "stopped")
        self.assertFalse(self.running & set(lifecycle.APPLICATION_SERVICES))

    def test_interrupted_migration_resumes_without_repeating_backup_or_seeding(self):
        self.fail = "migrate"
        with self.assertRaises(RuntimeError):
            self.invoke()
        pending = lifecycle.read_json(self.root / "update.json")
        self.assertEqual(pending["phase"], "migrating")
        self.assertEqual(lifecycle.current_state(self.root)["version"], "v0.78.0")
        self.assertFalse(self.running & set(lifecycle.APPLICATION_SERVICES))
        backups = list((self.root / "backups").iterdir())
        self.fail, self.args.resume = None, True
        self.invoke()
        self.assertEqual(list((self.root / "backups").iterdir()), backups)
        self.assertEqual(lifecycle.current_state(self.root)["version"], "v0.78.1")
        self.assertEqual(sum("run" in command and "setup" in command for command in self.commands), 2)

    def test_failed_start_resumes_health_checks_without_repeating_migration(self):
        self.fail = "start"
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.assertEqual(lifecycle.read_json(self.root / "update.json")["phase"], "starting")
        self.fail, self.args.resume = None, True
        self.invoke()
        self.assertEqual(sum("run" in command and "setup" in command for command in self.commands), 1)

    def test_corrupt_checkpoint_is_rejected_before_any_container_changes(self):
        lifecycle.write_json(self.root / "update.json", {"phase": "migrating"})
        self.args.resume = True
        with self.assertRaisesRegex(RuntimeError, "checkpoint is incomplete"):
            self.invoke()
        self.assertFalse(any("stop" in command or "up" in command for command in self.commands))
        self.assertEqual(lifecycle.read_env(self.root), self.original)

    def test_pending_update_requires_explicit_resume_and_matching_release(self):
        self.fail = "migrate"
        with self.assertRaises(RuntimeError):
            self.invoke()
        self.fail = None
        with self.assertRaisesRegex(RuntimeError, "pending"):
            self.invoke()
        self.args.resume, self.args.version = True, "v0.78.0"
        with self.assertRaisesRegex(RuntimeError, "same release"):
            self.invoke()

    def test_modified_backup_blocks_resume_before_migration(self):
        self.fail = "migrate"
        with self.assertRaises(RuntimeError):
            self.invoke()
        pending = lifecycle.read_json(self.root / "update.json")
        (self.root / pending["backup"] / "database.dump").write_bytes(b"damaged")
        self.fail, self.args.resume = None, True
        before = len(self.commands)
        with self.assertRaisesRegex(RuntimeError, "backup changed"):
            self.invoke()
        self.assertFalse(any("setup" in command for command in self.commands[before:]))

    def test_same_version_is_noop_and_downgrades_are_refused(self):
        self.invoke()
        before = list((self.root / "backups").iterdir())
        self.commands.clear()
        self.args.manifest = None
        self.invoke()
        self.assertEqual(list((self.root / "backups").iterdir()), before)
        self.assertTrue(all(command[:2] == ["docker", "ps"] for command in self.commands))
        self.args.version = "v0.78.0"
        self.args.manifest = Path(self.releases["v0.78.0"]["_origin"])
        with self.assertRaisesRegex(RuntimeError, "newer version"):
            self.invoke()

    def test_unversioned_legacy_update_requires_a_source_version_and_refuses_downgrade(self):
        self.state["version"] = None
        lifecycle.write_json(self.root / "installation.json", self.state)
        with self.assertRaisesRegex(RuntimeError, "from-version"):
            self.invoke()
        self.args.from_version = "v0.79.0"
        with self.assertRaisesRegex(RuntimeError, "newer version"):
            self.invoke()
        self.assertFalse(any("pull" in command or "stop" in command for command in self.commands))
        self.args.from_version = "v0.78.0"
        self.invoke()
        self.assertEqual(lifecycle.current_state(self.root)["version"], "v0.78.1")

    def test_manual_control_file_edits_are_preserved_and_block_update(self):
        (self.root / "compose.yml").write_text("operator customization")
        with self.assertRaisesRegex(RuntimeError, "changed"):
            self.invoke()
        self.assertEqual((self.root / "compose.yml").read_text(), "operator customization")
        self.assertTrue(all(command[:2] == ["docker", "ps"] for command in self.commands))

    def test_unsafe_configuration_permissions_and_symlinks_are_rejected(self):
        (self.root / ".env").chmod(0o644)
        with self.assertRaises(RuntimeError):
            lifecycle.read_env(self.root)
        (self.root / ".env").unlink()
        (self.root / ".env").symlink_to(self.base / "outside")
        with self.assertRaises(RuntimeError):
            lifecycle.atomic_write(self.root / ".env", "do not overwrite")
        self.assertFalse((self.base / "outside").exists())

    def test_external_database_configuration_cannot_receive_an_unbacked_migration(self):
        values = lifecycle.read_env(self.root)
        values["DATABASE_URL"] = "postgres://openlims:secret@another-server/openlims"
        lifecycle.write_env(self.root, values)
        with self.assertRaisesRegex(RuntimeError, "managed PostgreSQL"):
            self.invoke()
        self.assertFalse(self.commands)

    def test_concurrent_operation_cannot_acquire_existing_lock(self):
        self.args.command = "update"
        with (self.root / ".installer.lock").open("a") as lock, \
             patch.object(lifecycle.subprocess, "run", return_value=argparse.Namespace(returncode=0)):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, "Another installation"):
                lifecycle.main(self.args)
        self.assertFalse(self.commands)

    def test_installed_command_works_from_inside_its_managed_directory(self):
        self.args.command = "doctor"
        with patch.object(lifecycle.Path, "cwd", return_value=self.root),              patch.object(lifecycle.subprocess, "run", return_value=argparse.Namespace(returncode=0)):
            lifecycle.main(self.args)
        lifecycle.doctor.assert_called_once()

    def test_older_controller_cannot_manage_a_newer_installed_release(self):
        self.state["version"] = "v9999.0.0"
        lifecycle.write_json(self.root / "installation.json", self.state)
        with patch.object(lifecycle.subprocess, "run", return_value=argparse.Namespace(returncode=0)):
            with self.assertRaisesRegex(RuntimeError, "newer installed tools"):
                lifecycle.main(self.args)
        self.assertFalse(self.commands)

    def test_initialized_demo_resume_never_reseeds_or_resets_credentials(self):
        self.state["phase"] = "initializing"
        lifecycle.write_json(self.root / "installation.json", self.state)
        self.args.command, self.args.version = "demo", "v0.78.0"
        self.args.manifest = Path(self.releases["v0.78.0"]["_origin"])
        lifecycle.initialize(self.root, self.args)
        self.assertFalse(any("bootstrap_demo" in command or "setup" in command and "run" in command for command in self.commands))
        self.assertEqual(lifecycle.read_env(self.root)["OPENLIMS_DEMO_PASSWORD"], self.original["OPENLIMS_DEMO_PASSWORD"])

    def test_release_archive_and_manifest_are_reproducible_and_exclude_configuration(self):
        release = self.releases["v0.78.0"]
        other = self.base / "repeat"
        packager.package(other, release["version"], release["repository"], release["commit"],
                         release["images"]["backend"], release["images"]["frontend"])
        for name in ["release.json", "SHA256SUMS", "openlims-demo.sh", "openlims-v0.78.0.tar.gz"]:
            self.assertEqual((other / name).read_bytes(), (self.base / "v0.78.0" / name).read_bytes())
        with tarfile.open(other / "openlims-v0.78.0.tar.gz") as archive:
            self.assertEqual(set(archive.getnames()), lifecycle.REQUIRED_FILES | {"release.json"})

    def test_release_manifest_rejects_moving_tags_wrong_repository_and_traversal(self):
        original = self.releases["v0.78.1"]
        for change in [
            {"images": {"backend": "example/backend:latest", "frontend": pins("b")["frontend"]}},
            {"platforms": ["linux/amd64"]}, {"version": "../v0.78.1"},
            {"repository": "another/project"},
            {"files": {**original["files"], "installer/../../outside": "a" * 64}},
        ]:
            release = {**original, **change}
            with self.subTest(change=list(change)), self.assertRaises(RuntimeError):
                lifecycle.validate_release(release, lifecycle.DEFAULT_REPOSITORY, "v0.78.1")

    def test_corrupted_archive_is_rejected_without_installing_tool_code(self):
        release = copy.deepcopy(self.releases["v0.78.1"])
        (self.base / "v0.78.1" / release["bundle"]["name"]).write_bytes(b"corrupted")
        with self.assertRaisesRegex(RuntimeError, "checksum"):
            lifecycle.stage_release(self.root, release)
        self.assertFalse((self.root / ".staging/v0.78.1").exists())


if __name__ == "__main__":
    unittest.main()
