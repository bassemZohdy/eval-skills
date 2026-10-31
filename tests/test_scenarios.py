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


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(SAMPLE, self.d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class Scenarios(Base):
    def test_all_scenarios_are_stored(self):
        rep, out = eval_calc.compute(self.d)
        names = [x["name"] for x in out["scenarios"]]
        for want in ("base weights", "equal category weights", "must-have requirements only"):
            self.assertIn(want, names)
        self.assertEqual(sum(1 for n in names if n.startswith("5 points moved")), 2)
        self.assertTrue(out["order_changes"].endswith("of %d scenarios" % len(names)))
        self.assertTrue(all("leader" in x for x in out["scenarios"]))

    def test_meaningful_gap_defaults_to_five_and_is_configurable(self):
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(out["meaningful_gap"], 5)
        self.assertTrue(out["ties"])  # the example leads by about one point
        c = read(self.d, "criteria.json")
        c["meaningful_gap"] = 1
        write(self.d, "criteria.json", c)
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(out["ties"], [])

    def test_equal_weights_that_flip_the_leader_forbid_high_confidence(self):
        c = read(self.d, "criteria.json")
        c["criteria"][0]["weight"], c["criteria"][1]["weight"], c["criteria"][2]["weight"] = 90, 5, 5
        write(self.d, "criteria.json", c)
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(rep.errors, [])
        flipped = [x for x in out["scenarios"] if x["changed"]]
        self.assertTrue(flipped, out["order_changes"])
        report_draft.draft(self.d, {"recommendation": "Choose %s." % out["ranking"][0], "confidence": "high", "confidence_why": "x", "options": {o: ["a", "b"] for o in out["ranking"]},
                                    "bias": "b", "cost": "c", "sensitivity": "s", "next_steps": ["n"], "risks": ["r"], "excluded": "e"})
        text = open(os.path.join(self.d, "report.md"), encoding="utf-8").read().replace("Choose ", "Choose ")
        self.assertTrue(any("confidence is high" in p for p in report_draft.check(self.d)))


class WeightLock(Base):
    def test_analyze_records_the_lock_date(self):
        os.remove(os.path.join(self.d, "status.json")) if False else None
        st = read(self.d, "status.json")
        st["completed_steps"] = ["define"]
        write(self.d, "status.json", st)
        rep, st = eval_calc.complete_step(self.d, "analyze", today="2026-10-02")
        self.assertEqual(st["weights_locked_on"], "2026-10-02")

    def test_weight_change_after_compare_needs_a_reason(self):
        st = read(self.d, "status.json")
        st["completed_steps"] = ["define", "analyze", "discover", "compare"]
        write(self.d, "status.json", st)
        rep, res = eval_calc.mark_changed(self.d, "weights")
        self.assertIsNone(res)
        self.assertTrue(any("--reason" in e for e in rep.errors))
        rep, res = eval_calc.mark_changed(self.d, "weights", "stakeholders re-weighted operability")
        st = read(self.d, "status.json")
        self.assertTrue(st["post_scoring_weight_change"])
        self.assertEqual(st["weight_change_reason"], "stakeholders re-weighted operability")

    def test_validation_requires_the_reason_when_flagged(self):
        st = read(self.d, "status.json")
        st["post_scoring_weight_change"] = True
        write(self.d, "status.json", st)
        self.assertTrue(any("weight_change_reason" in e for e in eval_calc.validate(self.d).errors))

    def test_report_states_the_late_weight_change(self):
        st = read(self.d, "status.json")
        st["post_scoring_weight_change"], st["weight_change_reason"] = True, "stakeholder sign-off"
        write(self.d, "status.json", st)
        report_draft.draft(self.d, {})
        text = open(os.path.join(self.d, "report.md"), encoding="utf-8").read()
        self.assertIn("Weights were changed after scoring: stakeholder sign-off", text)


if __name__ == "__main__":
    unittest.main()
