import contextlib
import io
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.parse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import release_diagnostics as diagnostics
import smoke_release
import test_release_backend


class ReleaseDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_private_environment_is_only_used_to_remove_secrets(self):
        path = self.root / ".env"
        path.write_text("DJANGO_SECRET_KEY=private-signing-key\nOPENLIMS_DEMO_PASSWORD=demo-private\nOPENLIMS_HTTP_PORT=8080\n")
        confidential = diagnostics.environment_secrets(path)
        with contextlib.redirect_stdout(io.StringIO()):
            report = diagnostics.publish(self.root / "diagnostics.txt", [("Failure", "private-signing-key demo-private port 8080")], confidential)
        self.assertNotIn("private-signing-key", report)
        self.assertNotIn("demo-private", report)
        self.assertIn("port 8080", report)
        self.assertEqual((self.root / "diagnostics.txt").stat().st_mode & 0o777, 0o600)

    def test_passwords_and_url_encoded_values_are_removed(self):
        password = "private:/ +credential"
        content = " ".join([password, urllib.parse.quote(password, safe=""), urllib.parse.quote_plus(password),
                            "postgres://user:other-password@db/openlims", "connection refused"])
        report = diagnostics.redact(content, [password])
        for value in [password, urllib.parse.quote(password, safe=""), urllib.parse.quote_plus(password), "other-password"]:
            self.assertNotIn(value, report)
        self.assertIn("connection refused", report)

    def test_truncation_cannot_disclose_the_end_of_a_secret(self):
        secret = "long-sensitive-value" * 20
        with contextlib.redirect_stdout(io.StringIO()):
            report = diagnostics.publish(self.root / "report.txt", [("Failure", secret + " END")], [secret], tail_size=20)
        self.assertNotIn("sensitive", report)
        self.assertIn("[redacted] END", report)

    def test_report_does_not_overwrite_a_symlink_target(self):
        target = self.root / "keep.txt"
        target.write_text("preserve")
        link = self.root / "report.txt"
        link.symlink_to(target)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            diagnostics.publish(link, [("Failure", "safe diagnostic")])
        self.assertEqual(target.read_text(), "preserve")
        self.assertIn("safe diagnostic", output.getvalue())

    def test_github_command_processing_is_suspended_while_logs_are_printed(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), contextlib.redirect_stdout(io.StringIO()) as output:
            diagnostics.publish(self.root / "report.txt", [("Failure", "::error::untrusted-log-message")])
        text = output.getvalue()
        token = re.search(r"::stop-commands::([a-f0-9]+)", text)[1]
        self.assertLess(text.index("::stop-commands::"), text.index("::error::"))
        self.assertGreater(text.index("::" + token + "::"), text.index("::error::"))

    def test_backend_startup_failure_retains_redacted_report_and_original_exception(self):
        password, signing_key = "private-database-password", "private-signing-key"

        def run(command, **kwargs):
            if "up" in command:
                kwargs["stdout"].write(f"connection refused postgres://openlims:{password}@db/openlims {signing_key}\n".encode())
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0)

        report = self.root / "backend.txt"
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}), \
             patch.object(test_release_backend.secrets, "token_hex", side_effect=["123456abcdef", password, signing_key]), \
             patch.object(test_release_backend.subprocess, "run", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(subprocess.CalledProcessError):
                test_release_backend.check_image("example/backend:smoke", self.root, report)
        text = report.read_text()
        self.assertIn("connection refused", text)
        self.assertNotIn(password, text)
        self.assertNotIn(signing_key, text)

    def test_smoke_failure_before_installation_still_retains_diagnostics(self):
        def run(command, **kwargs):
            if command[:2] == ["docker", "run"]:
                kwargs["stdout"].write(b"scientific dependency could not start\n")
                return subprocess.CompletedProcess(command, 1)
            return subprocess.CompletedProcess(command, 0)

        import argparse
        report = self.root / "smoke.txt"
        args = argparse.Namespace(work_directory=self.root, backend_image="example/backend:smoke", diagnostics=report)
        with patch.object(smoke_release.subprocess, "run", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "Smoke operation failed"):
                smoke_release.smoke(args)
        self.assertIn("scientific dependency could not start", report.read_text())


if __name__ == "__main__":
    unittest.main()
