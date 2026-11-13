import copy
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import publish_release as publisher
from recover_release import validate_run


class RecoveryGateTests(unittest.TestCase):
    def setUp(self):
        self.commit, self.repository = "a" * 40, "Example/OpenLIMS"
        self.run = {"id": 123, "event": "release", "status": "completed", "conclusion": "failure",
                    "head_sha": self.commit, "path": ".github/workflows/installer.yml",
                    "repository": {"full_name": self.repository}}
        names = ["checks", "release-gate", "images (amd64, linux/amd64, ubuntu-24.04)",
                 "images (arm64, linux/arm64, ubuntu-24.04-arm)"]
        self.jobs = [{"id": index + 1, "name": name, "run_id": 123, "run_attempt": 1,
                      "status": "completed", "conclusion": "success"} for index, name in enumerate(names)]

    def test_failed_publisher_can_recover_when_original_gates_and_both_image_jobs_passed(self):
        validate_run(self.run, self.jobs, self.commit, self.repository)

    def test_wrong_run_event_repository_commit_or_workflow_is_rejected(self):
        for change in ({"event": "pull_request"}, {"head_sha": "b" * 40}, {"status": "in_progress"},
                       {"path": ".github/workflows/other.yml"}, {"repository": {"full_name": "Foreign/Project"}}):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                validate_run({**self.run, **change}, self.jobs, self.commit, self.repository)

    def test_missing_failed_cancelled_or_foreign_original_jobs_block_recovery(self):
        with self.assertRaises(RuntimeError):
            validate_run(self.run, self.jobs[:-1], self.commit, self.repository)
        for index in range(len(self.jobs)):
            for change in ({"conclusion": "failure"}, {"conclusion": "cancelled"}, {"run_id": 456}):
                jobs = copy.deepcopy(self.jobs)
                jobs[index].update(change)
                with self.subTest(job=index, change=change), self.assertRaises(RuntimeError):
                    validate_run(self.run, jobs, self.commit, self.repository)

    def test_publisher_only_rerun_keeps_earlier_successful_native_jobs(self):
        jobs = self.jobs + [{"id": 10, "name": "publish", "run_id": 123, "run_attempt": 2,
                             "status": "completed", "conclusion": "failure"}]
        validate_run(self.run, jobs, self.commit, self.repository)

    def test_a_newer_failed_native_attempt_cannot_fall_back_to_an_older_success(self):
        latest = {**self.jobs[-1], "id": 10, "run_attempt": 2, "conclusion": "failure"}
        with self.assertRaisesRegex(RuntimeError, "arm64"):
            validate_run(self.run, self.jobs + [latest], self.commit, self.repository)


class ReleaseSourceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Release tests")
        self.git("config", "user.email", "release-tests@example.invalid")
        (self.root / "VERSION").write_text("0.78.1\n")
        for name in publisher.REQUIRED_FILES | {"demo.sh.in"}:
            path = self.root / "deploy" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("original installer bytes\n")
        self.git("add", "VERSION", "deploy")
        self.git("commit", "-qm", "Original release")
        self.commit = self.git("rev-parse", "HEAD").strip()

    def git(self, *arguments):
        return subprocess.run(["git", "-C", str(self.root), *arguments], check=True, capture_output=True, text=True).stdout

    def test_original_clean_release_source_is_accepted(self):
        self.assertEqual(publisher.validate_source(self.root, "v0.78.1", self.commit), self.root)

    def test_original_source_is_pinned_even_when_newer_publisher_code_is_running(self):
        (self.root / "candidates").mkdir()
        (self.root / "candidates/amd64.json").write_text("downloaded CI artifact")
        self.assertEqual(publisher.validate_source(self.root, "v0.78.1", self.commit), self.root)

    def test_a_different_checkout_commit_or_version_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "commit"):
            publisher.validate_source(self.root, "v0.78.1", "b" * 40)
        with self.assertRaisesRegex(RuntimeError, "VERSION"):
            publisher.validate_source(self.root, "v0.78.2", self.commit)

    def test_modified_installer_bytes_cannot_be_bundled_under_the_old_commit(self):
        for name in ("openlims", "demo.sh.in"):
            path = self.root / "deploy" / name
            original = path.read_bytes()
            path.write_text("changed installer bytes\n")
            with self.subTest(file=name), self.assertRaisesRegex(RuntimeError, "committed release bytes"):
                publisher.validate_source(self.root, "v0.78.1", self.commit)
            path.write_bytes(original)

    def test_redirected_installer_files_are_rejected(self):
        original = self.root / "deploy/openlims"
        content = self.root / "external-file"
        original.rename(content)
        original.symlink_to(content)
        with self.assertRaisesRegex(RuntimeError, "committed release bytes"):
            publisher.validate_source(self.root, "v0.78.1", self.commit)


if __name__ == "__main__":
    unittest.main()
