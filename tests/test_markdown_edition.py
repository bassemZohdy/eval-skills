"""Guards for the Markdown-only plugin in plugins/option-evaluator (the edition the plugin directory accepts).

The plugin must hold only allowed file types, no script and no script reference, identical copies of its shared
documents, and calculation rules that match the constants of the script edition (shared/eval_calc.py).
"""
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(ROOT, "plugins", "option-evaluator")
SKILLS_DIR = os.path.join(PLUGIN, "skills")
ALLOWED_EXT = {".md", ".json", ".png"}
ALLOWED_NAMES = {"LICENSE"}
EVAL_SKILLS = ["eval-orchestrator", "eval-define", "eval-analyze", "eval-discover", "eval-compare", "eval-report"]
HEADER = re.compile(r"\A<!-- Copy of plugins/option-evaluator/shared/[^>]*-->\n\n")

sys.path.insert(0, os.path.join(ROOT, "shared"))
import eval_calc  # noqa: E402


def files():
    for d, _, names in os.walk(PLUGIN):
        for n in names:
            yield os.path.join(d, n)


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


class MarkdownEditionTest(unittest.TestCase):
    def test_only_allowed_files(self):
        for p in files():
            name = os.path.basename(p)
            ext = os.path.splitext(name)[1].lower()
            self.assertTrue(ext in ALLOWED_EXT or name in ALLOWED_NAMES, p)
            with open(p, "rb") as fh:
                raw = fh.read()
            self.assertFalse(raw.startswith(b"#!"), p)
            self.assertNotIn(b"\x00", raw if ext != ".png" else b"", p)
            if ext != ".png":
                raw.decode("utf-8")  # must be valid UTF-8

    def test_no_script_references(self):
        bad = re.compile(r"eval_calc|report_draft|export_report|scripts/|\bpython3?\b|\.py\b|\bnpx\b|\bpip\b|\bgit clone\b|\bclone the\b|\bcurl\b|\bwget\b|\bdownload|API_KEY|\$[A-Z_]{3,}", re.I)
        for p in files():
            if p.endswith((".md", ".json")):
                m = bad.search(read(p))
                self.assertIsNone(m, "%s mentions %r" % (p, m and m.group(0)))

    def test_manifest(self):
        m = json.loads(read(os.path.join(PLUGIN, ".claude-plugin", "plugin.json")))
        self.assertEqual(m["name"], "option-evaluator")
        self.assertEqual(m["license"], "Apache-2.0")
        self.assertTrue(os.path.exists(os.path.join(PLUGIN, ".claude-plugin", "icon.png")))

    def test_frontmatter_and_reference_links(self):
        for s in EVAL_SKILLS + ["eval-deep-research"]:
            body = read(os.path.join(SKILLS_DIR, s, "SKILL.md")).replace("\r\n", "\n")
            m = re.match(r"---\nname: (.+)\ndescription: (.+?)\n---\n", body, re.S)
            self.assertIsNotNone(m, s)
            self.assertEqual(m.group(1), s)
            self.assertLessEqual(len(m.group(2)), 1024, s)
            for ref in set(re.findall(r"references/([A-Za-z0-9_.-]+\.md)", body)):
                self.assertTrue(os.path.exists(os.path.join(SKILLS_DIR, s, "references", ref)), "%s -> %s" % (s, ref))

    def test_shared_copies_in_sync(self):
        shared = os.path.join(PLUGIN, "shared")
        for s in EVAL_SKILLS:
            refs = os.path.join(SKILLS_DIR, s, "references")
            for name in os.listdir(refs):
                copy = HEADER.sub("", read(os.path.join(refs, name)), count=1)
                self.assertEqual(copy, read(os.path.join(shared, name)), "%s/%s differs from shared/%s" % (s, name, name))

    def test_every_eval_skill_has_the_contract_and_calculation(self):
        for s in EVAL_SKILLS:
            for name in ("workspace-contract.md", "calculation.md", "validation.md", "procedures.md"):
                self.assertTrue(os.path.exists(os.path.join(SKILLS_DIR, s, "references", name)), (s, name))

    def test_skills_point_at_the_review_protocol(self):
        for s in ("eval-analyze", "eval-discover", "eval-compare"):
            self.assertIn("calculation.md", read(os.path.join(SKILLS_DIR, s, "SKILL.md")), s)


class CalculationMatchesScriptTest(unittest.TestCase):
    """The rules in calculation.md must carry the same constants and examples as the tested script."""

    @classmethod
    def setUpClass(cls):
        cls.calc = read(os.path.join(PLUGIN, "shared", "calculation.md"))

    def test_period_factors(self):
        self.assertEqual(eval_calc.PER, {"hour": 730.0, "day": 365.0 / 12, "month": 1.0, "year": 1.0 / 12})
        for needle in ("`hour` 730", "`day` 365/12", "`month` 1", "`year` 1/12"):
            self.assertIn(needle, self.calc)

    def test_cap_points_and_gap(self):
        self.assertEqual(eval_calc.CAP, 2)
        self.assertEqual(eval_calc.ANCHOR_POINTS, {"must": 5, "should": 3, "could": 1})
        self.assertIn("lowered to 2", self.calc)
        self.assertIn("must 5, should 3, could 1", self.calc)
        self.assertIn("(default 5 points)", self.calc)

    def test_default_cost_scenarios_documented(self):
        self.assertIn("*low* (multiplier 0.5)", self.calc)
        self.assertIn("*high* (multiplier 2)", self.calc)

    def test_rank_sum_examples(self):
        for n, expected in ((3, [50, 33, 17]), (4, [40, 30, 20, 10]), (7, [25, 21, 18, 14, 11, 7, 4])):
            ids = ["c%d" % i for i in range(n)]
            self.assertEqual(list(eval_calc.rank_sum_weights(ids).values()), expected, n)
            self.assertIn(", ".join(str(x) for x in expected), self.calc)

    def test_sensitivity_and_tie_rules(self):
        self.assertIn("+5 and -5", self.calc)
        self.assertIn("three criteria with the highest weight", self.calc)
        self.assertIn("80%", self.calc)


class StressCaseTest(unittest.TestCase):
    """The numbers that independent readers reproduced by following calculation.md on a hard case.

    tests/fixtures/md-edition-stress/eval has missing scores, a weak-evidence cap, a DISPUTED row, an over-claimed
    confidence, an override, custom priority points and every cost component kind. Four blind readers of the Markdown
    rules (two by hand, two with a calculator) matched these figures; the script must keep producing them.
    """

    def test_script_reproduces_the_verified_figures(self):
        import shutil
        import tempfile
        src = os.path.join(ROOT, "tests", "fixtures", "md-edition-stress", "eval")
        tmp = tempfile.mkdtemp()
        try:
            d = os.path.join(tmp, "eval")
            shutil.copytree(src, d)
            rep, out = eval_calc.compute(d, write=True)
            self.assertFalse(rep.errors, rep.errors)
            self.assertEqual(out["totals"], {"opt-1": 72.3, "opt-2": 60.0})
            self.assertEqual(out["ranking"], ["opt-1", "opt-2"])
            self.assertEqual(out["lead"], 12.3)
            self.assertEqual(out["must_gaps"], {"opt-1": 0, "opt-2": 3})
            self.assertEqual(out["unknown_bounds"]["opt-2"]["if_unknowns_provided"], 68.0)
            self.assertEqual(out["order_changes"], "0 of 6 scenarios")
            cost = json.loads(read(os.path.join(d, "cost.json")))["results"]["options"]
            self.assertEqual(cost["opt-1"]["tco"], 115496.0)
            self.assertEqual(cost["opt-2"]["tco"], 79880.0)
            self.assertEqual(cost["opt-1"]["scenarios"], {"half": 104936.0, "double": 134696.0, "tenx": 257576.0})
            self.assertEqual(cost["opt-2"]["scenarios"], {"half": 65360.0, "double": 80360.0, "tenx": 118760.0})
            f03 = out["requirement_scores"]["opt-1"]["F-03"]
            self.assertEqual((f03["score"], f03["confidence"], f03["capped"]), (2, "low", True))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
