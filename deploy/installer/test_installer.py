import argparse
from importlib.machinery import SourceFileLoader
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

installer = SourceFileLoader("installer", str(Path(__file__).parents[1] / "openlims")).load_module()


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.args = argparse.Namespace(domain="lims.example.org",
            backend_image="ghcr.io/example/api@sha256:" + "a" * 64,
            frontend_image="ghcr.io/example/web@sha256:" + "b" * 64)

    def test_valid_hostname(self):
        self.assertEqual(installer.domain("LIMS.example.org"), "lims.example.org")

    def test_invalid_hostnames(self):
        for value in ("localhost", "127.0.0.1", "https://lims.org", "lims.org:443",
                      "x.org\nEVIL=yes", "*.example.org", "-bad.example.org", "a..org"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                installer.domain(value)

    def test_images_require_digest(self):
        for value in ("api:latest", "api:v1.2", "-api@sha256:" + "a" * 64):
            with self.assertRaises(argparse.ArgumentTypeError):
                installer.image(value)
        self.assertEqual(installer.image(self.args.backend_image), self.args.backend_image)

    def test_secrets_private_and_stable_on_resume(self):
        installer.prepare(self.root, self.args)
        original = (self.root / ".env").read_bytes()
        installer.prepare(self.root, self.args)
        self.assertEqual(original, (self.root / ".env").read_bytes())
        self.assertEqual((self.root / ".env").stat().st_mode & 0o777, 0o600)
        self.assertIn(b"DJANGO_DEBUG=false", original)

    def test_independent_secrets(self):
        other = self.root / "other"
        other.mkdir()
        installer.prepare(self.root, self.args)
        installer.prepare(other, self.args)
        self.assertNotEqual((self.root / ".env").read_bytes(), (other / ".env").read_bytes())

    def test_domain_change_refused(self):
        installer.prepare(self.root, self.args)
        original = (self.root / ".env").read_bytes()
        self.args.domain = "other.example.org"
        with self.assertRaises(RuntimeError):
            installer.prepare(self.root, self.args)
        self.assertEqual(original, (self.root / ".env").read_bytes())

    def test_upgrade_refused(self):
        installer.prepare(self.root, self.args)
        self.args.backend_image = "example/api@sha256:" + "c" * 64
        with self.assertRaises(RuntimeError):
            installer.prepare(self.root, self.args)

    def test_modified_templates_preserved(self):
        installer.prepare(self.root, self.args)
        (self.root / "compose.yml").write_text("custom")
        with self.assertRaises(RuntimeError):
            installer.prepare(self.root, self.args)
        self.assertEqual((self.root / "compose.yml").read_text(), "custom")

    def test_interrupted_configuration_resumes(self):
        real_write = installer.private_write
        def interrupt(path, content):
            if path.name == "compose.yml":
                raise OSError("interrupted")
            real_write(path, content)
        with patch.object(installer, "private_write", side_effect=interrupt):
            with self.assertRaises(OSError):
                installer.prepare(self.root, self.args)
        original = (self.root / ".env").read_bytes()
        installer.prepare(self.root, self.args)
        self.assertEqual(original, (self.root / ".env").read_bytes())
        self.assertTrue((self.root / "Caddyfile").exists())

    def test_partial_secret_file_fails_closed(self):
        installer.private_write(self.root / ".env", "OPENLIMS_DOMAIN=lims.example.org\n")
        with self.assertRaises(RuntimeError):
            installer.prepare(self.root, self.args)

    def test_public_config_refused(self):
        installer.prepare(self.root, self.args)
        (self.root / ".env").chmod(0o644)
        with self.assertRaises(RuntimeError):
            installer.prepare(self.root, self.args)

    def test_exclusive_write_never_overwrites(self):
        path = self.root / "existing"
        installer.private_write(path, "first")
        with self.assertRaises(FileExistsError):
            installer.private_write(path, "second")
        self.assertEqual(path.read_text(), "first")

    def install_with_mock_services(self, active="", fail_setup=False):
        commands = []
        def fake_run(command, **kwargs):
            commands.append(command)
            if fail_setup and command[-4:] == ["run", "--rm", "--no-deps", "setup"]:
                raise RuntimeError("setup failed")
            return argparse.Namespace(returncode=0, stdout=active)
        argv = ["openlims", "install", "--directory", str(self.root / "installation"),
                "--domain", self.args.domain, "--backend-image", self.args.backend_image,
                "--frontend-image", self.args.frontend_image]
        response = MagicMock()
        response.__enter__.return_value.status = 200
        with patch.object(installer.sys, "argv", argv), \
             patch.object(installer.shutil, "which", return_value="/bin/docker"), \
             patch.object(installer.shutil, "disk_usage", return_value=argparse.Namespace(free=20 * 1024**3)), \
             patch.object(installer.socket, "getaddrinfo", return_value=[]), \
             patch.object(installer.socket, "socket"), \
             patch.object(installer.urllib.request, "urlopen", return_value=response), \
             patch.object(installer, "run", side_effect=fake_run), \
             patch("builtins.print"):
            if fail_setup:
                with self.assertRaises(RuntimeError):
                    installer.main()
            else:
                installer.main()
        return commands

    def test_first_install_initializes_before_application(self):
        commands = self.install_with_mock_services()
        setup = next(i for i, cmd in enumerate(commands) if cmd[-4:] == ["run", "--rm", "--no-deps", "setup"])
        app = next(i for i, cmd in enumerate(commands) if cmd[-4:] == ["api", "worker", "web", "caddy"])
        self.assertLess(setup, app)

    def test_running_application_resume_skips_migrations(self):
        commands = self.install_with_mock_services(active="api\nworker\n")
        self.assertFalse(any(cmd[-4:] == ["run", "--rm", "--no-deps", "setup"] for cmd in commands))

    def test_migration_failure_never_starts_application(self):
        commands = self.install_with_mock_services(fail_setup=True)
        self.assertFalse(any(cmd[-4:] == ["api", "worker", "web", "caddy"] for cmd in commands))
        self.assertTrue((self.root / "installation" / ".env").exists())


if __name__ == "__main__":
    unittest.main()
