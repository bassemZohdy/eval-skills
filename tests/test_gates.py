import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))
import eval_calc  # noqa: E402
import report_draft  # noqa: E402

SAMPLE = os.path.join(ROOT, "examples", "task-queue", "eval")


def read(d, n):
    with open(os.path.join(d, n), encoding="utf-8") as f:
        return json.load(f)


def write(d, n, data):
    with open(os.path.join(d, n), "w", encoding="utf-8") as f:
        json.dump(data, f)


class GateRubric(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(SAMPLE, self.d)
        self.crit = read(self.d, "criteria.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def errors(self):
        write(self.d, "criteria.json", self.crit)
        return eval_calc.validate(self.d).errors

    def verdict(self, o):
        return self.crit["gates"][0]["verdicts"][o]

    def test_example_is_valid(self):
        self.assertEqual(self.errors(), [])

    def test_a_missing_clause_note_is_an_error(self):
        self.verdict("opt-a")["clauses"].pop()
        self.assertTrue(any("one clause note for each" in e for e in self.errors()))

    def test_pass_with_an_unchecked_clause_is_rejected(self):
        self.verdict("opt-a")["clauses"][1]["met"] = None
        self.assertTrue(any("PASS needs every clause met" in e for e in self.errors()))

    def test_unverified_is_the_right_verdict_for_an_unchecked_clause(self):
        v = self.verdict("opt-a")
        v["clauses"][1]["met"] = None
        v["verdict"] = "UNVERIFIED"
        del v["basis"]
        o = read(self.d, "options.json")
        o[0]["gate_status"]["F-01"] = "unverified"
        write(self.d, "options.json", o)
        self.assertEqual(self.errors(), [])

    def test_not_met_needs_a_failed_clause(self):
        v = self.verdict("opt-c")
        for c in v["clauses"]:
            c["met"] = None
        self.assertTrue(any("NOT MET needs at least one clause" in e for e in self.errors()))

    def test_a_pass_needs_a_basis(self):
        del self.verdict("opt-a")["basis"]
        self.assertTrue(any("needs a basis" in e for e in self.errors()))

    def test_documented_pass_must_name_what_confirms_it(self):
        del self.verdict("opt-b")["confirm_by"]
        self.assertTrue(any("confirm_by" in e for e in self.errors()))

    def test_verdict_must_agree_with_gate_status(self):
        o = read(self.d, "options.json")
        o[0]["gate_status"]["F-01"] = "fail"
        write(self.d, "options.json", o)
        self.assertTrue(any("rubric verdict is PASS" in e for e in self.errors()))

    def test_a_rubric_for_a_non_gate_requirement_is_an_error(self):
        self.crit["gates"][0]["requirement_id"] = "F-02"
        self.assertTrue(any("not a gate requirement" in e for e in self.errors()))


class Eligibility(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(SAMPLE, self.d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_report_opens_with_eligibility_and_basis_is_shown(self):
        report_draft.draft(self.d, {})
        text = open(os.path.join(self.d, "report.md"), encoding="utf-8").read()
        self.assertLess(text.index("Eligibility: 2 of 3 options pass every gate"), text.index("## Decision recommendation"))
        self.assertIn("F-01 pass (documented)", text)

    def test_check_flags_a_missing_eligibility_line(self):
        report_draft.draft(self.d, {})
        p = os.path.join(self.d, "report.md")
        text = open(p, encoding="utf-8").read().replace("Eligibility: 2 of 3", "Gates")
        open(p, "w", encoding="utf-8").write(text)
        self.assertTrue(any("Eligibility" in x for x in report_draft.check(self.d)))

    def test_when_no_option_passes_the_report_recommends_none(self):
        opts = read(self.d, "options.json")
        for o in opts:
            o["gate_status"] = {"F-01": "fail"}
            o["excluded"], o["exclusion_reason"] = True, "fails F-01"
        write(self.d, "options.json", opts)
        crit = read(self.d, "criteria.json")
        crit.pop("gates")
        write(self.d, "criteria.json", crit)
        report_draft.draft(self.d, {"next_steps": ["Ask each vendor to confirm delivery."]})
        text = open(os.path.join(self.d, "report.md"), encoding="utf-8").read()
        self.assertIn("Eligibility: 0 of 3 options pass every gate", text)
        self.assertIn("Shortlist the options below and close their blockers", text)
        self.assertNotRegex(text, r"recommended option|[Cc]hoose [A-Z]")
        self.assertEqual(report_draft.check(self.d), [])


if __name__ == "__main__":
    unittest.main()
