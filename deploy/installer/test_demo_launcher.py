import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class DemoLauncherTests(unittest.TestCase):
    def launch(self, *, bad_checksum=False, malicious=None, selected_version="v0.78.0"):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture, tools = root / "fixture", root / "tools"
            fixture.mkdir()
            tools.mkdir()
            marker = root / "started.json"
            archive = fixture / "openlims-v0.78.0.tar.gz"
            with tarfile.open(archive, "w:gz") as handle:
                files = {"openlims": b"import json,os,sys\nfrom pathlib import Path\nPath(os.environ['LAUNCH_MARKER']).write_text(json.dumps(sys.argv[1:]))\n",
                         "release.json": b"{}", "installer/openlims_lifecycle.py": b"# fixture\n"}
                if malicious:
                    files[malicious] = b"do not extract"
                for name, content in files.items():
                    member = tarfile.TarInfo(name)
                    member.size = len(content)
                    handle.addfile(member, io.BytesIO(content))
            checksum = "0" * 64 if bad_checksum else hashlib.sha256(archive.read_bytes()).hexdigest()
            (fixture / "SHA256SUMS").write_text(checksum + "  openlims-v0.78.0.tar.gz\n")
            fake_curl = tools / "curl"
            fake_curl.write_text('''#!/usr/bin/env python3
import os,sys
from pathlib import Path
args=sys.argv[1:]
target=Path(args[args.index('-o')+1])
name='SHA256SUMS' if any(value.endswith('/SHA256SUMS') for value in args) else 'openlims-v0.78.0.tar.gz'
target.write_bytes((Path(os.environ['LAUNCH_FIXTURE'])/name).read_bytes())
Path(os.environ['LAUNCH_DOWNLOAD_MARKER']).touch()
''')
            fake_curl.chmod(0o700)
            (tools / "docker").write_text("#!/bin/sh\nexit 0\n")
            (tools / "docker").chmod(0o700)
            launcher = root / "demo.sh"
            launcher.write_text((ROOT / "deploy/demo.sh.in").read_text().replace("@VERSION@", "v0.78.0").replace("@REPOSITORY@", "Example/OpenLIMS"))
            environment = {**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"],
                           "LAUNCH_FIXTURE": str(fixture), "LAUNCH_MARKER": str(marker),
                           "LAUNCH_DOWNLOAD_MARKER": str(root / "downloaded"),
                           "OPENLIMS_DEMO_DIRECTORY": str(root / "instance"), "OPENLIMS_DEMO_PORT": "8090",
                           "OPENLIMS_RELEASE": selected_version}
            result = subprocess.run(["sh", str(launcher)], cwd=root, env=environment, capture_output=True, text=True)
            return result.returncode, json.loads(marker.read_text()) if marker.exists() else None, (root / "downloaded").exists()

    def test_one_line_launcher_checks_bundle_and_passes_selected_directory_port_and_repository(self):
        code, arguments, downloaded = self.launch()
        self.assertEqual(code, 0)
        self.assertTrue(downloaded)
        self.assertEqual(arguments[0], "demo")
        self.assertEqual(arguments[arguments.index("--port") + 1], "8090")
        self.assertEqual(arguments[arguments.index("--version") + 1], "v0.78.0")
        self.assertEqual(arguments[arguments.index("--repository") + 1], "Example/OpenLIMS")
        self.assertEqual(Path(arguments[arguments.index("--directory") + 1]).name, "instance")

    def test_changed_archive_is_not_executed(self):
        code, arguments, _ = self.launch(bad_checksum=True)
        self.assertNotEqual(code, 0)
        self.assertIsNone(arguments)

    def test_valid_checksum_does_not_allow_archive_path_traversal(self):
        for name in ("../outside", "/tmp/outside", "installer/../../outside"):
            with self.subTest(name=name):
                code, arguments, _ = self.launch(malicious=name)
                self.assertNotEqual(code, 0)
                self.assertIsNone(arguments)

    def test_invalid_version_is_rejected_before_download(self):
        code, arguments, downloaded = self.launch(selected_version="v0.78.0/../../other")
        self.assertNotEqual(code, 0)
        self.assertIsNone(arguments)
        self.assertFalse(downloaded)


if __name__ == "__main__":
    unittest.main()
