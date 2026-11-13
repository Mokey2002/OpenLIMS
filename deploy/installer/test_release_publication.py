import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import publish_release as publisher
import verify_release_ci as gate


class ReleaseGateTests(unittest.TestCase):
    def run_data(self, **changes):
        return {"id": 1, "head_sha": "a" * 40, "event": "push", "head_branch": "main",
                "name": "OpenLIMS CI", "status": "completed", "conclusion": "success", **changes}

    def test_requires_completed_ci_for_the_exact_main_commit(self):
        commit = "a" * 40
        self.assertTrue(gate.successful_run([self.run_data()], commit))
        for change in ({"head_sha": "b" * 40}, {"head_branch": "feature"}, {"event": "pull_request"},
                       {"name": "Installer checks"}, {"status": "in_progress", "conclusion": None}):
            with self.subTest(change=change):
                self.assertFalse(gate.successful_run([self.run_data(**change)], commit))

    def test_newer_failed_ci_cannot_be_hidden_by_an_older_success(self):
        with self.assertRaisesRegex(RuntimeError, "did not succeed"):
            gate.successful_run([self.run_data(), self.run_data(id=2, conclusion="failure")], "a" * 40)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.repository, self.version, self.commit = "Example/OpenLIMS", "v0.78.0", "a" * 40
        self.registry = Mock()
        self.records = []
        self.configs = {}
        for arch, character in [("amd64", "b"), ("arm64", "c")]:
            images = {}
            for component in ("backend", "frontend"):
                ref = f"ghcr.io/example/openlims-{component}@sha256:{character * 64}"
                images[component] = ref
                self.configs[(f"example/openlims-{component}", "blobs/sha256:" + character * 64)] = {
                    "os": "linux", "architecture": arch, "config": {"Labels": {
                        "org.opencontainers.image.version": self.version,
                        "org.opencontainers.image.revision": self.commit,
                        "org.opencontainers.image.source": "https://github.com/" + self.repository}}}
            self.records.append({"platform": "linux/" + arch, "images": images})
        self.registry.manifest.side_effect = lambda ref: ({"config": {"digest": ref.split("@", 1)[1]}}, ref.split("@", 1)[1])
        self.registry.request.side_effect = lambda name, path: (self.configs[(name, path)], "unused")

    def test_candidates_require_both_platforms_and_matching_image_labels(self):
        result = publisher.validate_candidates(self.records, self.repository, self.version, self.commit, self.registry)
        self.assertEqual(set(result["backend"]), {"linux/amd64", "linux/arm64"})
        with self.assertRaises(RuntimeError):
            publisher.validate_candidates(self.records[:1], self.repository, self.version, self.commit, self.registry)
        first = next(iter(self.configs.values()))
        first["config"]["Labels"]["org.opencontainers.image.revision"] = "f" * 40
        with self.assertRaisesRegex(RuntimeError, "wrong platform, source revision or version"):
            publisher.validate_candidates(self.records, self.repository, self.version, self.commit, self.registry)

    def test_mismatched_native_platform_and_foreign_images_are_refused(self):
        next(iter(self.configs.values()))["architecture"] = "arm64"
        with self.assertRaises(RuntimeError):
            publisher.validate_candidates(self.records, self.repository, self.version, self.commit, self.registry)
        self.records[0]["images"]["backend"] = "ghcr.io/foreign/project@sha256:" + "b" * 64
        with self.assertRaisesRegex(RuntimeError, "does not belong"):
            publisher.validate_candidates(self.records, self.repository, self.version, self.commit, self.registry)

    def index(self):
        return {"schemaVersion": 2, "mediaType": publisher.OCI_INDEX,
                "annotations": {"org.opencontainers.image.version": self.version, "org.opencontainers.image.revision": self.commit},
                "manifests": [{"platform": {"os": "linux", "architecture": record["platform"].split("/")[1]},
                               "digest": record["images"]["backend"].split("@")[1]} for record in self.records]}

    def docker_list(self):
        result = self.index()
        result["mediaType"] = publisher.DOCKER_LIST
        result.pop("annotations")
        return result

    def _validated_candidates(self):
        return publisher.validate_candidates(self.records, self.repository, self.version, self.commit, self.registry)

    def test_docker_manifest_list_matches_validated_native_images_without_oci_annotations(self):
        candidates = self._validated_candidates()
        publisher.verify_index(self.docker_list(), candidates["backend"], self.version, self.commit)

    def test_oci_index_still_requires_version_and_revision_annotations(self):
        index = self.index()
        index.pop("annotations")
        with self.assertRaisesRegex(RuntimeError, "missing or conflicting"):
            publisher.verify_index(index, self._validated_candidates()["backend"], self.version, self.commit)

    def test_docker_manifest_list_refuses_conflicting_metadata(self):
        for key in ("org.opencontainers.image.version", "org.opencontainers.image.revision"):
            index = self.docker_list()
            index["annotations"] = {key: "different"}
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "conflicting"):
                publisher.verify_index(index, self._validated_candidates()["backend"], self.version, self.commit)

    def test_docker_manifest_list_does_not_bypass_native_version_or_source_checks(self):
        first = next(iter(self.configs.values()))["config"]["Labels"]
        for key in ("org.opencontainers.image.version", "org.opencontainers.image.revision", "org.opencontainers.image.source"):
            original = first[key]
            first[key] = "different"
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "wrong platform, source revision or version"):
                self._validated_candidates()
            first[key] = original

    def test_docker_manifest_list_rejects_changed_digests_or_platforms(self):
        candidates = self._validated_candidates()["backend"]
        for mutation in ("digest", "duplicate", "platform"):
            index = self.docker_list()
            if mutation == "digest":
                index["manifests"][0]["digest"] = "sha256:" + "d" * 64
            elif mutation == "duplicate":
                index["manifests"].append(index["manifests"][0])
            else:
                index["manifests"][0]["platform"]["architecture"] = "386"
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                publisher.verify_index(index, candidates, self.version, self.commit)

    def test_partial_publication_reuses_valid_docker_tag_and_only_creates_missing_component(self):
        candidates = self._validated_candidates()
        self.registry.manifest.side_effect = [(self.docker_list(), "sha256:" + "d" * 64), None,
                                              (self.docker_list(), "sha256:" + "e" * 64)]
        run = Mock()
        images = publisher.publish_indices(candidates, self.repository, self.version, self.commit, self.registry, run)
        self.assertEqual(images["backend"], "ghcr.io/example/openlims-backend@sha256:" + "d" * 64)
        self.assertEqual(images["frontend"], "ghcr.io/example/openlims-frontend@sha256:" + "e" * 64)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][run.call_args.args[0].index("--tag") + 1], "ghcr.io/example/openlims-frontend:" + self.version)

    def test_existing_docker_tag_with_different_images_is_never_overwritten(self):
        candidates = self._validated_candidates()
        index = self.docker_list()
        index["manifests"][0]["digest"] = "sha256:" + "d" * 64
        self.registry.manifest.side_effect = None
        self.registry.manifest.return_value = index, "sha256:" + "e" * 64
        run = Mock()
        with self.assertRaisesRegex(RuntimeError, "different platform image digests"):
            publisher.publish_indices(candidates, self.repository, self.version, self.commit, self.registry, run)
        run.assert_not_called()

    def test_unknown_index_formats_are_not_accepted_by_compatibility_handling(self):
        index = self.docker_list()
        index["mediaType"] = "application/example"
        with self.assertRaisesRegex(RuntimeError, "Unsupported release index format"):
            publisher.verify_index(index, self._validated_candidates()["backend"], self.version, self.commit)

    def test_index_must_preserve_exact_verified_digests_and_unique_platforms(self):
        candidates = {record["platform"]: record["images"]["backend"] for record in self.records}
        publisher.verify_index(self.index(), candidates, self.version, self.commit)
        for mutation in ("digest", "duplicate", "revision"):
            value = self.index()
            if mutation == "digest":
                value["manifests"][0]["digest"] = "sha256:" + "d" * 64
            elif mutation == "duplicate":
                value["manifests"].append(value["manifests"][0])
            else:
                value["annotations"]["org.opencontainers.image.revision"] = "d" * 40
            with self.subTest(mutation=mutation), self.assertRaises(RuntimeError):
                publisher.verify_index(value, candidates, self.version, self.commit)

    def test_existing_different_version_tag_is_never_overwritten(self):
        self.registry.manifest.side_effect = None
        index = self.index()
        index["manifests"] = []
        self.registry.manifest.return_value = (index, "sha256:" + "d" * 64)
        run = Mock()
        candidates = {"backend": {record["platform"]: record["images"]["backend"] for record in self.records}}
        with self.assertRaisesRegex(RuntimeError, "different platform image digests"):
            publisher.publish_indices(candidates, self.repository, self.version, self.commit, self.registry, run)
        run.assert_not_called()

    def test_different_existing_release_asset_is_not_overwritten(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for name in [f"openlims-{self.version}.tar.gz", "openlims-demo.sh", "SHA256SUMS", "release.json"]:
                (output / name).write_text("expected")
            calls = []
            def run(command, **kwargs):
                calls.append(command)
                if "view" in command:
                    return type("Result", (), {"stdout": json.dumps({"assets": [{"name": f"openlims-{self.version}.tar.gz"}]})})()
                if "download" in command:
                    target = Path(command[command.index("--dir") + 1]) / command[command.index("--pattern") + 1]
                    target.write_text("different")
            with self.assertRaisesRegex(RuntimeError, "never overwritten"):
                publisher.publish_assets(output, self.repository, self.version, run)
            self.assertFalse(any("upload" in command for command in calls))

    def test_readiness_manifest_is_uploaded_after_its_downloads(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for name in [f"openlims-{self.version}.tar.gz", "openlims-demo.sh", "SHA256SUMS", "release.json"]:
                (output / name).write_text("expected")
            calls = []
            def run(command, **kwargs):
                calls.append(command)
                return type("Result", (), {"stdout": '{"assets": []}'})()
            publisher.publish_assets(output, self.repository, self.version, run)
            uploads = [Path(command[4]).name for command in calls if "upload" in command]
            self.assertEqual(uploads, [f"openlims-{self.version}.tar.gz", "openlims-demo.sh", "SHA256SUMS", "release.json"])


if __name__ == "__main__":
    unittest.main()
