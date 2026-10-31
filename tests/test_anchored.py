import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))
import eval_calc  # noqa: E402

SAMPLE = os.path.join(ROOT, "examples", "task-queue", "eval")


def read(d, name):
    with open(os.path.join(d, name), encoding="utf-8") as f:
        return json.load(f)


def write(d, name, data):
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        json.dump(data, f)


class Anchored(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(SAMPLE, self.d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def score(self):
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(rep.errors, [])
        return out

    def test_total_matches_an_independent_hand_calculation(self):
        out = self.score()
        crit, reqs = read(self.d, "criteria.json"), {r["id"]: r["priority"] for r in read(self.d, "requirements.json")}
        pts = {"must": 5, "should": 3, "could": 1}
        for o, rows in out["requirement_scores"].items():
            total = 0.0
            for c in crit["criteria"]:
                num = sum(pts[reqs[r]] * rows[r]["score"] for r in c["requirement_ids"])
                den = sum(pts[reqs[r]] for r in c["requirement_ids"])
                total += num / den / 5 * c["weight"]
            self.assertAlmostEqual(out["totals"][o], round(total, 1), places=1)

    def test_priority_points_come_from_the_mapping(self):
        base = self.score()["totals"]
        s = read(self.d, "scores.json")
        s["priority_points"] = {"must": 3, "should": 2, "could": 1}
        write(self.d, "scores.json", s)
        self.assertNotEqual(self.score()["totals"], base)

    def test_feature_cell_change_leaves_scores_untouched(self):
        a = self.score()
        before = (json.dumps(a["totals"]), json.dumps(a["criterion_scores"]))
        f = read(self.d, "features.json")
        f[0]["cells"]["opt-a"]["status"] = "missing"
        write(self.d, "features.json", f)
        b = self.score()
        self.assertEqual(before, (json.dumps(b["totals"]), json.dumps(b["criterion_scores"])))

    def test_requirement_score_change_leaves_features_md_untouched(self):
        self.score()
        with open(os.path.join(self.d, "features.md"), "rb") as f:
            before = f.read()
        s = read(self.d, "scores.json")
        s["requirement_scores"]["opt-a"]["F-01"]["score"] = 1
        write(self.d, "scores.json", s)
        self.score()
        with open(os.path.join(self.d, "features.md"), "rb") as f:
            self.assertEqual(before, f.read())

    def test_scorer_rejects_features_inside_scores(self):
        s = read(self.d, "scores.json")
        s["features"] = [{"id": "x"}]
        write(self.d, "scores.json", s)
        rep = eval_calc.validate(self.d)
        self.assertTrue(any("features.json" in e for e in rep.errors))

    def test_long_rationale_warns(self):
        s = read(self.d, "scores.json")
        s["requirement_scores"]["opt-a"]["F-01"]["rationale"] = "word " * 41
        write(self.d, "scores.json", s)
        self.assertTrue(any("rationale has 41 words" in w for w in eval_calc.validate(self.d).warnings))

    def test_score_outside_zero_to_five_is_an_error(self):
        s = read(self.d, "scores.json")
        s["requirement_scores"]["opt-a"]["F-01"]["score"] = 6
        write(self.d, "scores.json", s)
        self.assertTrue(any("0 to 5" in e for e in eval_calc.validate(self.d).errors))

    def test_weak_evidence_caps_a_requirement_at_two(self):
        ev = read(self.d, "evidence.json")
        for e in ev:
            if e["evidence_id"] == "E-001":
                e["confidence"] = "UNVERIFIED"
        write(self.d, "evidence.json", ev)
        out = self.score()
        self.assertEqual(out["requirement_scores"]["opt-a"]["F-01"]["score"], 2)
        self.assertTrue(out["requirement_scores"]["opt-a"]["F-01"]["capped"])

    def test_missing_requirement_score_counts_zero_with_a_best_case(self):
        s = read(self.d, "scores.json")
        del s["requirement_scores"]["opt-b"]["F-01"]
        write(self.d, "scores.json", s)
        out = self.score()
        ub = out["unknown_bounds"]["opt-b"]
        self.assertGreater(ub["if_unknowns_provided"], ub["as_scored"])

    def test_requirement_override_needs_a_reason(self):
        s = read(self.d, "scores.json")
        s["overrides"] = [{"option_id": "opt-a", "requirement_id": "F-01", "score": 3}]
        write(self.d, "scores.json", s)
        rep, _ = eval_calc.compute(self.d)
        self.assertTrue(any("needs a reason" in e for e in rep.errors))

    def test_old_model_still_works(self):
        legacy = os.path.join(ROOT, "tests", "fixtures", "task-queue-legacy")
        d = os.path.join(self.tmp, "old")
        shutil.copytree(legacy, d)
        rep, out = eval_calc.compute(d)
        self.assertEqual(rep.errors, [])
        self.assertEqual(out["scoring_model"], "cell_midpoint")


class Hierarchy(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(SAMPLE, self.d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_largest_remainder_sums_to_the_category_weight(self):
        for total in (30, 33, 7):
            for pts in ({"a": 5, "b": 3, "c": 1}, {"a": 1, "b": 1, "c": 1}, {"a": 5, "b": 5}):
                got = eval_calc.largest_remainder(pts, total)
                self.assertEqual(sum(got.values()), total)

    def test_requirement_shares_sum_to_each_category_weight(self):
        rep, out = eval_calc.compute(self.d)
        crit = {c["id"]: c["weight"] for c in read(self.d, "criteria.json")["criteria"]}
        for cid, shares in out["requirement_shares"].items():
            self.assertEqual(sum(shares.values()), crit[cid])

    def test_contribution_and_attainment_are_reported(self):
        rep, out = eval_calc.compute(self.d)
        cs = out["criterion_scores"]["opt-a"]["crit-core"]
        self.assertAlmostEqual(cs["contribution"], cs["attainment"] * 50, places=1)

    def test_fractional_weight_is_an_error(self):
        c = read(self.d, "criteria.json")
        c["criteria"][0]["weight"] = 50.5
        c["criteria"][1]["weight"] = 29.5
        write(self.d, "criteria.json", c)
        self.assertTrue(any("whole number" in e for e in eval_calc.validate(self.d).errors))

    def test_a_category_with_one_requirement_is_an_error(self):
        c = read(self.d, "criteria.json")
        moved = c["criteria"][0]["requirement_ids"].pop()
        c["criteria"][1]["requirement_ids"].append(moved)
        write(self.d, "criteria.json", c)
        self.assertTrue(any("at least two" in e for e in eval_calc.validate(self.d).errors))

    def test_a_requirement_in_two_categories_is_an_error(self):
        c = read(self.d, "criteria.json")
        c["criteria"][1]["requirement_ids"].append(c["criteria"][0]["requirement_ids"][0])
        write(self.d, "criteria.json", c)
        self.assertTrue(any("covered by 2 criteria" in e for e in eval_calc.validate(self.d).errors))

    def test_weights_must_sum_to_100(self):
        c = read(self.d, "criteria.json")
        c["criteria"][0]["weight"] = 40
        write(self.d, "criteria.json", c)
        self.assertTrue(any("not 100" in e for e in eval_calc.validate(self.d).errors))


if __name__ == "__main__":
    unittest.main()


class AnchoredExport(unittest.TestCase):
    def test_example_exports_html_and_xlsx_with_the_feature_table(self):
        import export_report
        out = tempfile.mkdtemp()
        try:
            self.assertEqual(export_report.main([SAMPLE, "--out", out, "--formats", "html,xlsx"]), 0)
            with open(os.path.join(out, "report.html"), encoding="utf-8") as f:
                page = f.read()
            self.assertIn("does not feed the scores", page)
            self.assertIn("Alpha Queue", page)
        finally:
            shutil.rmtree(out, ignore_errors=True)


class ScopeTags(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(SAMPLE, self.d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_unknown_tag_is_an_error(self):
        f = read(self.d, "features.json")
        f[0]["cells"]["opt-a"]["scope_tags"] = ["cloudy"]
        write(self.d, "features.json", f)
        self.assertTrue(any("unknown scope tag" in e for e in eval_calc.validate(self.d).errors))

    def test_export_has_the_toggle_and_scores_are_untouched(self):
        import export_report
        eval_calc.compute(self.d)
        before = open(os.path.join(self.d, "scores.json"), "rb").read()
        out = os.path.join(self.tmp, "out")
        export_report.main([self.d, "--out", out, "--formats", "html"])
        page = open(os.path.join(out, "report.html"), encoding="utf-8").read()
        self.assertIn('id="strict"', page)
        self.assertIn('data-tags="saas"', page)
        self.assertIn("scores are unchanged", page)
        self.assertEqual(before, open(os.path.join(self.d, "scores.json"), "rb").read())
        # tagging a feature and recomputing leaves every total alone
        totals = eval_calc.compute(self.d)[1]["totals"]
        f = read(self.d, "features.json")
        f[0]["cells"]["opt-a"]["scope_tags"] = ["preview"]
        write(self.d, "features.json", f)
        self.assertEqual(totals, eval_calc.compute(self.d)[1]["totals"])

    def stands_alone(self):
        import export_report
        out = os.path.join(self.tmp, "out")
        export_report.main([self.d, "--out", out, "--formats", "html"])
        page = open(os.path.join(out, "report.html"), encoding="utf-8").read()
        return page[page.index("Stands alone"):page.index("Stands alone") + 600] if "Stands alone" in page else ""

    def test_stands_alone_leaves_out_tagged_and_negative_rows(self):
        f = read(self.d, "features.json")
        row = next(x for x in f if x["id"] == "FT-02-F")  # Beta includes it; Alpha has a note saying schedules are missing
        self.assertNotIn("Delayed and scheduled jobs", self.stands_alone())  # negative evidence on the other side
        row["cells"]["opt-a"]["note"] = ""
        write(self.d, "features.json", f)
        self.assertIn("Delayed and scheduled jobs", self.stands_alone())
        row["cells"]["opt-b"]["scope_tags"] = ["preview"]
        write(self.d, "features.json", f)
        self.assertNotIn("Delayed and scheduled jobs", self.stands_alone())
