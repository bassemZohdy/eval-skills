#!/usr/bin/env python3
"""Copy the single-source files in shared/ into every skill folder.

Usage: python scripts/sync_shared.py [--check]

Each skill must be installable on its own, so the shared contract and calculation
script are copied into skills/<name>/references/ and skills/<name>/scripts/.
--check makes no changes and exits 1 if any copy has drifted.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = ["eval-orchestrator", "eval-define", "eval-analyze", "eval-discover", "eval-compare", "eval-report"]
HEADER = "<!-- Generated from shared/workspace-contract.md by scripts/sync_shared.py. Edit the source, not this copy. -->\n\n"


def expected():
    with open(os.path.join(ROOT, "shared", "workspace-contract.md"), "rb") as f:
        contract = f.read()
    with open(os.path.join(ROOT, "shared", "eval_calc.py"), "rb") as f:
        script = f.read()
    with open(os.path.join(ROOT, "shared", "export_report.py"), "rb") as f:
        export = f.read()
    for s in SKILLS:
        yield os.path.join(ROOT, "skills", s, "references", "workspace-contract.md"), HEADER.encode() + contract
        yield os.path.join(ROOT, "skills", s, "scripts", "eval_calc.py"), script
    yield os.path.join(ROOT, "skills", "eval-report", "scripts", "export_report.py"), export
    with open(os.path.join(ROOT, "shared", "report_draft.py"), "rb") as f:
        yield os.path.join(ROOT, "skills", "eval-report", "scripts", "report_draft.py"), f.read()


def main():
    check = "--check" in sys.argv
    drift = []
    for path, data in expected():
        current = open(path, "rb").read() if os.path.exists(path) else None
        if current != data:
            drift.append(os.path.relpath(path, ROOT))
            if not check:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(data)
    if drift and check:
        print("Out of sync with shared/ (run python scripts/sync_shared.py):\n  " + "\n  ".join(drift))
        return 1
    print("in sync" if not drift else "updated %d files" % len(drift))
    return 0


if __name__ == "__main__":
    sys.exit(main())
