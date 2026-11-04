"""Build a portable skill archive from an explicit, checked file allowlist."""

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import sys
import zipfile


ROOT = Path(__file__).resolve().parent.parent
NAME = "deep-researcher"
RESULTS = "tests/results/skill-smoke-2026-11-01"
FILES = (
    "README.md",
    "SKILL.md",
    "references/claim-specific-checks.md",
    "references/delegation.md",
    "references/eval-handoff.md",
    "references/quantified-confidence.md",
    "scripts/package_skill.py",
    "tests/TESTING.md",
    "tests/check_skill.py",
    "tests/record_observations.py",
    "tests/replay_sources.py",
    "tests/replay-sources.json",
    "tests/research-cases.json",
    "tests/test_package_skill.py",
    "tests/test_record_observations.py",
    "tests/test_replay_sources.py",
)
EVIDENCE = (
    "baseline-answers.json", "baseline-observations.json", "baseline-reviews.json",
    "baseline-trace.jsonl", "candidate-answers.json", "candidate-observations.json",
    "candidate-reviews.json", "candidate-trace.jsonl", "evaluation.json",
)
LOCAL_PATH = re.compile(r"/(?:Users|home)/[^/\s]+/|[.](?:copilot)/session-state/")


def collect_payload():
    sources = {name: ROOT / name for name in FILES}
    sources.update({f"{RESULTS}/{name}": ROOT / RESULTS / name for name in EVIDENCE})
    baseline = ROOT / RESULTS / "baseline-source.md"
    if not baseline.exists():
        baseline = ROOT / RESULTS / "baseline-skill" / "SKILL.md"
    sources[f"{RESULTS}/baseline-source.md"] = baseline
    payload = {}
    for name, source in sorted(sources.items()):
        if source.is_symlink() or ROOT not in source.resolve().parents:
            raise ValueError(f"Package source escapes the skill directory: {name}")
        if not source.is_file():
            raise ValueError(f"Missing required package source: {name}")
        content = source.read_bytes()
        if LOCAL_PATH.search(content.decode("utf-8")):
            raise ValueError(f"Machine-specific path in package source: {name}")
        payload[name] = content
    validate_entrypoint(payload)
    return payload


def validate_entrypoint(payload):
    text = payload["SKILL.md"].decode()
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError("Skill frontmatter delimiters are missing")
    frontmatter = text.split("---\n", 2)[1]
    if not re.search(rf"^name: {NAME}$", frontmatter, re.MULTILINE):
        raise ValueError("Skill name must match the archive's root directory")
    lines = frontmatter.split("description: >-\n", 1)
    if len(lines) != 2:
        raise ValueError("Expected folded skill description")
    description = " ".join(line.strip() for line in lines[1].splitlines())
    if not 1 <= len(description) <= 1024:
        raise ValueError("Skill description must contain 1-1024 characters")
    for link in re.findall(r"\]\(([^)]+)\)", text):
        path = PurePosixPath(link)
        if path.is_absolute() or ".." in path.parts or link not in payload:
            raise ValueError(f"Skill link is not included in the package: {link}")
    entries = [name for name in payload if PurePosixPath(name).name == "SKILL.md"]
    if entries != ["SKILL.md"]:
        raise ValueError("Package must contain exactly one discoverable SKILL.md")


def build_archive(payload):
    manifest = {
        "format": "agent-skill-package/1",
        "name": NAME,
        "entrypoint": "SKILL.md",
        "python_minimum": "3.9",
        "license": "UNSPECIFIED",
        "evidence_status": "conditional-smoke-pass",
        "files": [
            {"path": name, "bytes": len(content),
             "sha256": hashlib.sha256(content).hexdigest()}
            for name, content in sorted(payload.items())
        ],
    }
    files = dict(payload)
    files["package-manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    files["SHA256SUMS"] = "".join(
        f"{hashlib.sha256(content).hexdigest()}  {name}\n"
        for name, content in sorted(files.items())
    ).encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, content in sorted(files.items()):
            entry = zipfile.ZipInfo(f"{NAME}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, content, compresslevel=9)
    return output.getvalue(), len(files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    try:
        archive_path = args.output_dir / f"{NAME}.zip"
        checksum_path = args.output_dir / f"{NAME}.zip.sha256"
        if not args.replace and (archive_path.exists() or checksum_path.exists()):
            raise ValueError("Output exists; choose another directory or explicitly use --replace")
        content, count = build_archive(collect_payload())
        digest = hashlib.sha256(content).hexdigest()
        args.output_dir.mkdir(parents=True, exist_ok=True)
        mode = "wb" if args.replace else "xb"
        with archive_path.open(mode) as stream:
            stream.write(content)
        with checksum_path.open("w" if args.replace else "x") as stream:
            stream.write(f"{digest}  {archive_path.name}\n")
        print(json.dumps({"archive": str(archive_path), "checksum": str(checksum_path),
                          "sha256": digest, "files": count, "bytes": len(content)}, indent=2))
        return 0
    except (OSError, ValueError, UnicodeError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
