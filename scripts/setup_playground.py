#!/usr/bin/env python3
"""Install the skills into playground/ so Claude Code started there can use them.

Usage: python scripts/setup_playground.py [--dest DIR]

Copies every folder in skills/ to <dest>/.claude/skills/ (default: playground/).
Run it again after you change a skill. The playground is git-ignored.
"""
import argparse
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", default=os.path.join(ROOT, "playground"))
    a = ap.parse_args(argv)
    target = os.path.join(a.dest, ".claude", "skills")
    names = sorted(n for n in os.listdir(os.path.join(ROOT, "skills")) if os.path.isfile(os.path.join(ROOT, "skills", n, "SKILL.md")))
    for n in names:
        dst = os.path.join(target, n)
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(os.path.join(ROOT, "skills", n), dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    print("installed %d skills into %s" % (len(names), target))
    print("next: open Claude Code in %s and say what decision you want to evaluate" % os.path.abspath(a.dest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
