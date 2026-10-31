import hashlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
import zipfile


SPEC = importlib.util.spec_from_file_location(
    "package_skill", Path(__file__).resolve().parent.parent / "scripts" / "package_skill.py"
)
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)


class PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = PACKAGE.collect_payload()

    def test_repeated_builds_are_identical(self):
        first, _ = PACKAGE.build_archive(self.payload)
        second, _ = PACKAGE.build_archive(self.payload)
        self.assertEqual(first, second)

    def test_manifest_and_checksums_cover_the_payload(self):
        content, count = PACKAGE.build_archive(self.payload)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            manifest = json.loads(archive.read("deep-researcher/package-manifest.json"))
            self.assertEqual(len(archive.namelist()), count)
            for record in manifest["files"]:
                actual = archive.read(f"deep-researcher/{record['path']}")
                self.assertEqual(len(actual), record["bytes"])
                self.assertEqual(hashlib.sha256(actual).hexdigest(), record["sha256"])
            for line in archive.read("deep-researcher/SHA256SUMS").decode().splitlines():
                digest, name = line.split("  ", 1)
                self.assertEqual(
                    hashlib.sha256(archive.read(f"deep-researcher/{name}")).hexdigest(), digest
                )

    def test_historical_input_does_not_add_another_skill_entry(self):
        content, _ = PACKAGE.build_archive(self.payload)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = [name for name in archive.namelist() if name.endswith("/SKILL.md")]
            self.assertEqual(entries, ["deep-researcher/SKILL.md"])
            self.assertTrue(any(name.endswith("/baseline-source.md") for name in archive.namelist()))

    def test_missing_or_escaping_reference_is_rejected(self):
        for link in ("references/missing.md", "../outside.md"):
            with self.subTest(link=link):
                payload = dict(self.payload)
                payload["SKILL.md"] += f"\n[Invalid link]({link})\n".encode()
                with self.assertRaisesRegex(ValueError, "not included"):
                    PACKAGE.validate_entrypoint(payload)


if __name__ == "__main__":
    unittest.main()
