import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = ["eval-orchestrator", "eval-define", "eval-analyze", "eval-discover", "eval-compare", "eval-report"]


def text(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8", newline="") as f:
        return f.read()


class RepoTest(unittest.TestCase):
    def test_shared_copies_in_sync(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "sync_shared.py"), "--check"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_frontmatter(self):
        for s in SKILLS:
            body = text("skills", s, "SKILL.md")
            m = re.match(r"---\nname: (.+)\ndescription: (.+)\n---\n", body.replace("\r\n", "\n"))
            self.assertIsNotNone(m, s)
            self.assertEqual(m.group(1), s)
            self.assertLessEqual(len(m.group(2)), 1024, s)

    def test_every_skill_uses_the_script_and_it_exists(self):
        for s in SKILLS:
            self.assertIn("scripts/eval_calc.py", text("skills", s, "SKILL.md"), s)
            self.assertTrue(os.path.exists(os.path.join(ROOT, "skills", s, "scripts", "eval_calc.py")), s)

    def test_deep_researcher_is_bundled_and_has_fallbacks(self):
        # the eval skills name deep-researcher first (contract rule 16); it must ship here, with deep-research and direct research behind it
        self.assertTrue(os.path.exists(os.path.join(ROOT, "skills", "deep-researcher", "SKILL.md")))
        self.assertTrue(os.path.exists(os.path.join(ROOT, "skills", "deep-researcher", "references", "eval-handoff.md")))
        contract = text("shared", "workspace-contract.md")
        self.assertRegex(contract, r"(?s)16\. Research skill\..*`deep-researcher`.*`deep-research`.*research directly")
        for s in SKILLS:
            body = text("skills", s, "SKILL.md")
            for sent in re.split(r"(?<=[.!?])\s+", body):
                if re.search(r"\bdeep-research\b(?!er)", sent):
                    self.assertIn("deep-researcher", sent, (s, sent))

    def test_orchestrator_only_routes_to_existing_skills(self):
        body = text("skills", "eval-orchestrator", "SKILL.md")
        named = set(re.findall(r"eval-[a-z]+", body)) - {"eval-archive"}
        self.assertTrue(named <= set(SKILLS), named - set(SKILLS))
        for step in ("eval-define", "eval-analyze", "eval-discover", "eval-compare", "eval-report"):
            self.assertIn(step, body)

    def test_playground_setup_installs_every_skill(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            r = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "setup_playground.py"), "--dest", tmp], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            for s in SKILLS:
                self.assertTrue(os.path.exists(os.path.join(tmp, ".claude", "skills", s, "SKILL.md")), s)
                self.assertTrue(os.path.exists(os.path.join(tmp, ".claude", "skills", s, "scripts", "eval_calc.py")), s)

    def test_playground_is_ignored_except_its_readme(self):
        ignore = text(".gitignore")
        self.assertIn("playground/*", ignore)
        self.assertIn("!playground/README.md", ignore)

    def test_license_is_apache(self):
        self.assertIn("Apache License", text("LICENSE"))
        self.assertIn("Version 2.0", text("LICENSE"))

    def test_scripts_run_standalone_from_a_skill_folder(self):
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "skills", "eval-analyze", "scripts", "eval_calc.py"),
                            "weights", "a", "b", "c"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"a": 50', r.stdout)

    def test_cli_exit_codes(self):
        script = os.path.join(ROOT, "skills", "eval-compare", "scripts", "eval_calc.py")
        sample = os.path.join(ROOT, "examples", "task-queue", "eval")
        ok = subprocess.run([sys.executable, "-I", script, "validate", sample, "--before", "report"], capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        bad = subprocess.run([sys.executable, "-I", script, "validate", os.path.join(ROOT, "nope")], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 1)


if __name__ == "__main__":
    unittest.main()
