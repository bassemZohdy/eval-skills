"""A second, separate implementation of the total, run over the shipped examples.

It uses only the JSON files and none of the scorer's code, so a rounding slip or a stale total in scores.json shows up here.
"""
import json
import os
import unittest
from decimal import Decimal, ROUND_HALF_UP

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASES = [os.path.join(ROOT, "examples", "task-queue", "eval"), os.path.join(ROOT, "tests", "fixtures", "task-queue-legacy")]


def load(d, n):
    with open(os.path.join(d, n), encoding="utf-8") as f:
        return json.load(f)


def one_decimal(x):
    return float(Decimal(repr(x + 1e-9)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


class Recompute(unittest.TestCase):
    def test_totals_equal_the_weighted_criterion_scores(self):
        for d in CASES:
            s, c = load(d, "scores.json"), load(d, "criteria.json")
            top = c["scale"]["max"]
            for o, total in s["totals"].items():
                mine = sum(s["criterion_scores"][o][k["id"]]["score"] / top * k["weight"] for k in c["criteria"])
                self.assertAlmostEqual(total, one_decimal(mine), places=1, msg=d)

    def test_anchored_total_from_requirement_scores_alone(self):
        d = CASES[0]
        s, c = load(d, "scores.json"), load(d, "criteria.json")
        prio = {r["id"]: r["priority"] for r in load(d, "requirements.json")}
        pts = s.get("priority_points") or {"must": 5, "should": 3, "could": 1}
        for o, rows in s["requirement_scores"].items():
            total = 0.0
            for k in c["criteria"]:
                num = sum(pts[prio[r]] * rows[r]["score"] for r in k["requirement_ids"])
                den = sum(pts[prio[r]] for r in k["requirement_ids"])
                total += k["weight"] * num / den / 5
            self.assertEqual(s["totals"][o], one_decimal(total))

    def test_category_shares_add_up_to_each_weight(self):
        d = CASES[0]
        s, c = load(d, "scores.json"), load(d, "criteria.json")
        for k in c["criteria"]:
            if k["weight"] > 0:
                self.assertEqual(sum(s["requirement_shares"][k["id"]].values()), k["weight"])

    def test_displayed_percentages_never_drift(self):
        s = load(CASES[0], "scores.json")
        for o in s["totals"]:
            parts = [v["contribution"] for v in s["criterion_scores"][o].values()]
            self.assertAlmostEqual(sum(parts), s["totals"][o], delta=0.1 * len(parts))


if __name__ == "__main__":
    unittest.main()
