import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))
import eval_calc  # noqa: E402
import export_report  # noqa: E402

SAMPLE = os.path.join(ROOT, "examples", "task-queue", "eval")


def read(d, n):
    with open(os.path.join(d, n), encoding="utf-8") as f:
        return json.load(f)


def write(d, n, data):
    with open(os.path.join(d, n), "w", encoding="utf-8") as f:
        json.dump(data, f)


class EvidenceRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(SAMPLE, self.d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ev(self, fn):
        ev = read(self.d, "evidence.json")
        fn(ev)
        write(self.d, "evidence.json", ev)
        return eval_calc.validate(self.d)

    def test_example_is_clean(self):
        rep = eval_calc.validate(self.d)
        self.assertEqual((rep.errors, [w for w in rep.warnings if "pin" in w]), ([], []))

    def test_unpinned_rows_warn_once(self):
        def f(ev):
            del ev[0]["pin"]
            del ev[1]["pin"]
        warns = [w for w in self.ev(f).warnings if "no pin" in w]
        self.assertEqual(len(warns), 1)
        self.assertIn("E-001", warns[0])

    def test_latest_needs_a_source_date(self):
        def f(ev):
            ev[0]["pin"], ev[0]["source_date"] = "latest", "unknown"
        self.assertTrue(any("only allowed with a source_date" in e for e in self.ev(f).errors))
        def g(ev):
            ev[0]["pin"], ev[0]["source_date"] = "latest", "2026-08-01"
        self.assertEqual(self.ev(g).errors, [])

    def test_moving_branch_url_warns(self):
        def f(ev):
            ev[0]["source_url"] = "https://github.com/x/y/blob/main/docs.md"
        self.assertTrue(any("/main/" in w for w in self.ev(f).warnings))

    def test_same_document_at_two_pins_warns(self):
        def f(ev):
            ev[2]["source_url"] = ev[1]["source_url"]
            ev[2]["pin"] = "v2"
            ev[1]["pin"] = "v1"
        self.assertTrue(any("different pins" in w for w in self.ev(f).warnings))

    def test_uncited_evidence_is_an_error_once_compare_is_done(self):
        ev = read(self.d, "evidence.json")
        ev.append(dict(ev[0], evidence_id="E-099"))
        write(self.d, "evidence.json", ev)
        st = read(self.d, "status.json")
        st["completed_steps"] = ["define", "analyze", "discover", "compare"]
        write(self.d, "status.json", st)
        self.assertTrue(any("E-099 is cited by no score" in e for e in eval_calc.validate(self.d).errors))

    def test_sources_are_numbered_by_first_citation_one_per_document(self):
        class D:
            pass
        d = export_report.Data(self.d)
        n = export_report.source_numbers(d)
        self.assertEqual(sorted(set(n.values())), list(range(1, len(set(n.values())) + 1)))
        self.assertEqual(n["E-002"], n["E-003"])  # same document, one number
        self.assertEqual(n["E-001"], 1)  # first cited in the gate rubric

    def test_source_class_is_checked(self):
        def f(ev):
            ev[0]["source_class"] = "blog"
        self.assertTrue(any("source_class" in e for e in self.ev(f).errors))


class OssInheritance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(SAMPLE, self.d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_inherited_only_evidence_caps_confidence_at_medium(self):
        s = read(self.d, "scores.json")
        s["requirement_scores"]["opt-b"]["F-02"]["confidence"] = "high"
        write(self.d, "scores.json", s)
        ev = read(self.d, "evidence.json")
        for e in ev:
            if e["evidence_id"] in s["requirement_scores"]["opt-b"]["F-02"]["evidence_ids"]:
                e["inherited_from_oss"] = True
        write(self.d, "evidence.json", ev)
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(out["requirement_scores"]["opt-b"]["F-02"]["confidence"], "medium")

    def test_unchecked_option_next_to_an_oss_base_warns(self):
        o = read(self.d, "options.json")
        del o[0]["oss_base"]
        write(self.d, "options.json", o)
        rep, out = eval_calc.compute(self.d)
        self.assertTrue(any("oss_base is set for" in w for w in rep.warnings))

    def test_all_checked_does_not_warn(self):
        rep, out = eval_calc.compute(self.d)
        self.assertFalse(any("oss_base" in w for w in rep.warnings))

    def test_oss_base_needs_project_ref_and_source(self):
        o = read(self.d, "options.json")
        o[1]["oss_base"] = {"project": "x"}
        write(self.d, "options.json", o)
        self.assertTrue(any("oss_base must be" in e for e in eval_calc.validate(self.d).errors))


if __name__ == "__main__":
    unittest.main()
