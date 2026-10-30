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


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(SAMPLE, self.d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class WeightsTest(unittest.TestCase):
    def test_rank_sum_three(self):
        self.assertEqual(eval_calc.rank_sum_weights(["a", "b", "c"]), {"a": 50, "b": 33, "c": 17})

    def test_rank_sum_four_is_exact(self):
        self.assertEqual(list(eval_calc.rank_sum_weights(list("abcd")).values()), [40, 30, 20, 10])

    def test_rank_sum_five_largest_remainder(self):
        w = eval_calc.rank_sum_weights(list("abcde"))
        self.assertEqual(list(w.values()), [33, 27, 20, 13, 7])

    def test_always_sums_to_100(self):
        for n in range(1, 13):
            self.assertEqual(sum(eval_calc.rank_sum_weights([str(i) for i in range(n)]).values()), 100)


class ValidateTest(Sandbox):
    def test_sample_is_valid(self):
        rep = eval_calc.validate(self.d, "report")
        self.assertEqual(rep.errors, [])

    def test_missing_evidence_id(self):
        ev = read(self.d, "evidence.json")
        del ev[0]["evidence_id"]
        write(self.d, "evidence.json", ev)
        self.assertTrue(any("evidence_id" in e for e in eval_calc.validate(self.d).errors))

    def test_duplicate_requirement_id(self):
        reqs = read(self.d, "requirements.json")
        reqs[1]["id"] = "F-01"
        write(self.d, "requirements.json", reqs)
        self.assertTrue(any("duplicate requirement" in e for e in eval_calc.validate(self.d).errors))

    def test_weights_must_sum_to_100(self):
        c = read(self.d, "criteria.json")
        c["criteria"][0]["weight"] = 45
        write(self.d, "criteria.json", c)
        self.assertTrue(any("not 100" in e for e in eval_calc.validate(self.d).errors))

    def test_cost_requirement_required(self):
        reqs = [r for r in read(self.d, "requirements.json") if r["category"] != "Cost"]
        write(self.d, "requirements.json", reqs)
        self.assertTrue(any("no cost requirement" in e for e in eval_calc.validate(self.d).errors))

    def test_gate_needs_scope(self):
        reqs = read(self.d, "requirements.json")
        del reqs[0]["gate_scope"]
        write(self.d, "requirements.json", reqs)
        self.assertTrue(any("gate_scope" in e for e in eval_calc.validate(self.d).errors))

    def test_bad_confidence_label(self):
        ev = read(self.d, "evidence.json")
        ev[0]["confidence"] = "MAYBE"
        write(self.d, "evidence.json", ev)
        self.assertTrue(any("confidence" in e for e in eval_calc.validate(self.d).errors))

    def test_before_requires_completed_steps(self):
        st = read(self.d, "status.json")
        st["completed_steps"] = ["define", "analyze"]
        write(self.d, "status.json", st)
        errs = eval_calc.validate(self.d, "compare").errors
        self.assertTrue(any("step discover is not complete" in e for e in errs))

    def test_before_blocks_on_stale_steps(self):
        st = read(self.d, "status.json")
        st["stale_steps"] = ["compare"]
        write(self.d, "status.json", st)
        self.assertTrue(any("stale" in e for e in eval_calc.validate(self.d, "report").errors))

    def test_missing_status_file(self):
        os.remove(os.path.join(self.d, "status.json"))
        errs = eval_calc.validate(self.d, "analyze").errors
        self.assertTrue(any("status.json is missing" in e for e in errs))

    def test_unknown_evidence_id_in_cell(self):
        s = read(self.d, "scores.json")
        s["cell_values"]["opt-a"]["F-01"]["evidence_ids"] = ["E-999"]
        write(self.d, "scores.json", s)
        self.assertTrue(any("E-999" in e for e in eval_calc.validate(self.d).errors))


class ScoreTest(Sandbox):
    def run_score(self):
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(rep.errors, [])
        return out

    def test_totals_and_ranking(self):
        out = self.run_score()
        self.assertEqual(out["totals"], {"opt-a": 76.0, "opt-b": 78.0})
        self.assertEqual(out["ranking"], ["opt-b", "opt-a"])

    def test_near_tie_is_reported_and_broken_by_top_criterion(self):
        out = self.run_score()
        self.assertEqual(out["ties"], [{"options": ["opt-b", "opt-a"], "tie_break": "higher score on highest-weight criterion"}])

    def test_unverified_only_evidence_caps_score(self):
        cs = self.run_score()["criterion_scores"]["opt-b"]["crit-ops"]
        self.assertEqual((cs["score"], cs["capped"], cs["confidence"]), (2, True, "low"))

    def test_half_up_rounding(self):
        # Beta crit-core mean is exactly 4.5 and must round to 5
        self.assertEqual(self.run_score()["criterion_scores"]["opt-b"]["crit-core"]["score"], 5)

    def test_priority_weighting(self):
        # Alpha crit-ops: must provided (4.5) and could not provided (0.5) -> (3*4.5 + 0.5) / 4 = 3.5 -> 4
        self.assertEqual(self.run_score()["criterion_scores"]["opt-a"]["crit-ops"]["score"], 4)

    def test_sensitivity_values(self):
        sens = {(x["criterion_id"], x["delta"]): x for x in self.run_score()["sensitivity"]}
        self.assertEqual(sens[("crit-core", 5)]["totals"], {"opt-a": 76.4, "opt-b": 80.2})
        self.assertEqual(sens[("crit-core", -5)]["totals"], {"opt-a": 75.6, "opt-b": 75.8})
        self.assertFalse(any(x["changed"] for x in sens.values()))

    def test_confidence_test_flips_top_option(self):
        tests = self.run_score()["confidence_tests"]
        self.assertTrue(tests[0]["changed"])
        self.assertEqual(tests[0]["top"], "opt-a")
        self.assertEqual(tests[0]["totals"]["opt-b"], 72.0)

    def test_must_summary_and_excluded(self):
        out = self.run_score()
        self.assertEqual(out["must_summary"]["opt-b"]["partial"], 1)
        self.assertEqual([e["option_id"] for e in out["excluded"]], ["opt-c"])

    def test_features_md_matches_committed_copy(self):
        self.run_score()
        with open(os.path.join(self.d, "features.md"), encoding="utf-8", newline="") as a, \
                open(os.path.join(SAMPLE, "features.md"), encoding="utf-8", newline="") as b:
            self.assertEqual(a.read(), b.read())

    def test_scoring_is_deterministic(self):
        first = self.run_score()
        second = self.run_score()
        self.assertEqual(first, second)

    def test_unverified_gate_blocks_ranking(self):
        o = read(self.d, "options.json")
        o[0]["gate_status"] = {"F-01": "unverified"}
        write(self.d, "options.json", o)
        rep, out = eval_calc.compute(self.d)
        self.assertIsNone(out)
        self.assertTrue(any("unverified gate" in e for e in rep.errors))

    def test_waived_gate_is_ranked(self):
        o = read(self.d, "options.json")
        o[0]["gate_status"] = {"F-01": "waived_by_user"}
        write(self.d, "options.json", o)
        self.assertIsNotNone(eval_calc.compute(self.d)[1])

    def test_failed_gate_is_excluded_even_if_not_flagged(self):
        o = read(self.d, "options.json")
        o[1]["gate_status"] = {"F-01": "fail"}
        write(self.d, "options.json", o)
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(out["ranking"], ["opt-a"])
        self.assertTrue(any("treated as excluded" in w for w in rep.warnings))

    def test_override_applies_and_needs_reason(self):
        s = read(self.d, "scores.json")
        s["overrides"] = [{"option_id": "opt-a", "criterion_id": "crit-core", "score": 5, "reason": "Demo showed scheduling works"}]
        write(self.d, "scores.json", s)
        out = self.run_score()
        self.assertTrue(out["criterion_scores"]["opt-a"]["crit-core"]["overridden"])
        self.assertEqual(out["totals"]["opt-a"], 86.0)
        s["overrides"][0]["reason"] = ""
        write(self.d, "scores.json", s)
        self.assertTrue(any("needs a reason" in e for e in eval_calc.compute(self.d)[0].errors))

    def test_missing_cell_counts_as_unknown(self):
        s = read(self.d, "scores.json")
        del s["cell_values"]["opt-a"]["N-02"]
        write(self.d, "scores.json", s)
        rep, out = eval_calc.compute(self.d)
        self.assertEqual([w for w in rep.warnings if "counted as unknown" in w], ["Alpha Queue has no cell value for N-02; counted as unknown"])
        # (3*4.5 + 1*1) / 4 = 3.625 -> 4
        self.assertEqual(out["criterion_scores"]["opt-a"]["crit-ops"]["score"], 4)

    def test_vendor_claimed_counts_as_gap(self):
        s = read(self.d, "scores.json")
        s["cell_values"]["opt-a"]["F-01"]["value"] = "vendor-claimed"
        write(self.d, "scores.json", s)
        out = self.run_score()
        self.assertEqual(out["must_summary"]["opt-a"]["vendor-claimed"], 1)

    def test_cost_separate_excludes_cost_from_total(self):
        c = read(self.d, "criteria.json")
        c["cost_mode"] = "separate"
        c["criteria"][0]["weight"] = 60
        c["criteria"][1]["weight"] = 40
        c["criteria"][2]["weight"] = 0
        write(self.d, "criteria.json", c)
        out = self.run_score()
        self.assertEqual(out["totals"], {"opt-a": 80.0, "opt-b": 76.0})


class BalanceTest(Sandbox):
    def test_option_with_thin_evidence_is_flagged(self):
        # Beta has evidence-backed values for 3 requirements against 5 for Alpha: below two-thirds
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(out["evidence_coverage"], {"opt-a": 5, "opt-b": 3})
        self.assertTrue(any("Beta Queue has evidence-backed values for 3 of 6" in w for w in rep.warnings), rep.warnings)

    def test_balanced_evidence_is_quiet(self):
        s = read(self.d, "scores.json")
        for cell in s["cell_values"]["opt-b"].values():
            cell["evidence_ids"] = ["E-006"]
        write(self.d, "scores.json", s)
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(out["evidence_coverage"]["opt-b"], 6)
        self.assertFalse(any("evidence-backed values" in w for w in rep.warnings))

    def test_unknown_cells_do_not_count_as_evidence(self):
        s = read(self.d, "scores.json")
        s["cell_values"]["opt-a"]["F-01"]["value"] = "unknown"
        write(self.d, "scores.json", s)
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(out["evidence_coverage"]["opt-a"], 4)


class CostTest(Sandbox):
    def cost(self):
        rep, res = eval_calc.compute_cost(self.d)
        self.assertEqual(rep.errors, [])
        return res

    def edit_cost(self, fn):
        c = read(self.d, "cost.json")
        fn(c)
        write(self.d, "cost.json", c)

    def test_tco_matches_hand_calculation(self):
        res = self.cost()
        # Alpha: tiers 0 + 900k*0.0004 + 4M*0.0002 = 1160, plus 100 support = 1260/month for 36 months
        self.assertEqual(res["options"]["opt-a"]["monthly"], 1260.0)
        self.assertEqual(res["options"]["opt-a"]["tco"], 45360.0)
        # Beta: (2*150 + 80)/month for 36 months plus 2000 setup
        self.assertEqual(res["options"]["opt-b"]["tco"], 15680.0)
        self.assertEqual(res["ranking"], ["opt-b", "opt-a"])
        self.assertEqual(res["options"]["opt-a"]["index_vs_cheapest"], 2.89)

    def test_cheapest_option_flips_between_scenarios(self):
        res = self.cost()
        self.assertEqual(res["options"]["opt-a"]["scenarios"], {"pilot (100k jobs/month)": 3600.0, "growth (10M jobs/month)": 81360.0})
        self.assertEqual(res["cheapest_by_scenario"], {"pilot (100k jobs/month)": "opt-a", "growth (10M jobs/month)": "opt-b"})

    def test_weak_evidence_is_listed_as_a_gap(self):
        res = self.cost()
        self.assertEqual(res["options"]["opt-b"]["evidence_gaps"], ["b-plugin"])
        self.assertEqual(res["options"]["opt-a"]["evidence_gaps"], [])

    def test_unknown_price_marks_option_incomplete_and_is_not_guessed(self):
        def fn(c):
            comp = c["options"]["opt-b"]["components"][1]
            comp.pop("amount"), comp.pop("evidence_id")
            comp["price_unknown"] = True
        self.edit_cost(fn)
        res = self.cost()
        self.assertTrue(res["options"]["opt-b"]["incomplete"])
        self.assertEqual(res["options"]["opt-b"]["tco"], 2000 + 300 * 36)
        self.assertIn("b-plugin", res["options"]["opt-b"]["evidence_gaps"])

    def test_incomplete_options_are_never_ranked_cheapest(self):
        def fn(c):
            comp = c["options"]["opt-a"]["components"][1]
            comp.pop("amount"), comp.pop("evidence_id")
            comp["price_unknown"] = True
        self.edit_cost(fn)
        res = self.cost()
        self.assertEqual(res["ranking"], ["opt-b", "opt-a"])
        self.assertEqual(res["cheapest"], "opt-b")
        self.assertIsNone(res["options"]["opt-a"]["index_vs_cheapest"])
        self.assertEqual(set(res["cheapest_by_scenario"].values()), {"opt-b"})

    def test_all_prices_unknown_means_no_cheapest(self):
        def fn(c):
            for o in c["options"].values():
                for comp in o["components"]:
                    for k in ("amount", "evidence_id", "tiers", "driver"):
                        comp.pop(k, None)
                    comp["kind"], comp["price_unknown"] = "fixed_monthly", True
        self.edit_cost(fn)
        res = self.cost()
        self.assertIsNone(res["cheapest"])
        self.assertEqual(set(res["cheapest_by_scenario"].values()), {None})
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(rep.errors, [])
        with open(os.path.join(self.d, "features.md"), encoding="utf-8") as f:
            self.assertIn("quote needed", f.read())

    def test_zero_weight_criterion_needs_no_rationale(self):
        c = read(self.d, "criteria.json")
        c["cost_mode"] = "separate"
        c["criteria"][0]["weight"], c["criteria"][1]["weight"], c["criteria"][2]["weight"] = 60, 40, 0
        write(self.d, "criteria.json", c)
        s = read(self.d, "scores.json")
        for o in s["rationales"].values():
            o.pop("crit-cost", None)
        write(self.d, "scores.json", s)
        rep, out = eval_calc.compute(self.d)
        self.assertFalse(any("crit-cost" in w for w in rep.warnings))

    def test_cited_evidence_counts_toward_confidence(self):
        s = read(self.d, "scores.json")
        s["cell_values"]["opt-b"]["N-02"]["evidence_ids"] = ["E-009"]
        write(self.d, "scores.json", s)
        rep, out = eval_calc.compute(self.d)
        d = out["criterion_scores"]["opt-b"]["crit-ops"]
        self.assertIn("E-009", d["evidence_ids"])

    def test_tiered_graduated_and_volume_modes(self):
        comp = {"tiers": [{"up_to": 100, "unit_price": 1.0}, {"up_to": 200, "unit_price": 0.5}, {"up_to": None, "unit_price": 0.1}]}
        self.assertAlmostEqual(eval_calc._tiered_monthly(comp, 50), 50.0)
        self.assertAlmostEqual(eval_calc._tiered_monthly(comp, 250), 100 + 50 + 5)
        comp["tier_mode"] = "volume"
        self.assertAlmostEqual(eval_calc._tiered_monthly(comp, 150), 75.0)
        self.assertAlmostEqual(eval_calc._tiered_monthly(comp, 1000), 100.0)

    def test_usage_included_free_and_quantity_driver(self):
        vals = {"A-01": 1000, "A-02": 4}
        usage = {"kind": "usage", "unit_price": 0.01, "driver": "A-01", "included_free": 400}
        self.assertAlmostEqual(eval_calc._component_cost(usage, vals)[0], 6.0)
        seats = {"kind": "fixed_monthly", "amount": 10, "quantity_driver": "A-02"}
        self.assertEqual(eval_calc._component_cost(seats, vals)[0], 40)
        self.assertEqual(eval_calc._component_cost({"kind": "usage", "unit_price": 1, "driver": "A-01", "included_free": 5000}, vals)[0], 0)

    def test_priced_component_needs_evidence(self):
        self.edit_cost(lambda c: c["options"]["opt-a"]["components"][1].pop("evidence_id"))
        self.assertTrue(any("evidence_id" in e for e in eval_calc.validate(self.d).errors))

    def test_unknown_evidence_driver_and_option_are_rejected(self):
        self.edit_cost(lambda c: c["options"]["opt-a"]["components"][1].update(evidence_id="E-404"))
        self.assertTrue(any("E-404" in e for e in eval_calc.validate(self.d).errors))
        self.edit_cost(lambda c: c["options"]["opt-a"]["components"][0].update(driver="A-99"))
        self.assertTrue(any("A-99" in e for e in eval_calc.validate(self.d).errors))
        self.edit_cost(lambda c: c["options"].update({"opt-zzz": c["options"]["opt-a"]}))
        self.assertTrue(any("opt-zzz" in e for e in eval_calc.validate(self.d).errors))

    def test_every_profiled_option_needs_a_cost_model(self):
        self.edit_cost(lambda c: c["options"].pop("opt-b"))
        self.assertTrue(any("no cost model for Beta Queue" in e for e in eval_calc.validate(self.d).errors))

    def test_tiers_must_end_with_null(self):
        self.edit_cost(lambda c: c["options"]["opt-a"]["components"][0]["tiers"][-1].update(up_to=5))
        self.assertTrue(any("end with up_to null" in e for e in eval_calc.validate(self.d).errors))

    def test_cost_json_required_before_compare(self):
        os.remove(os.path.join(self.d, "cost.json"))
        self.assertTrue(any("cost.json is missing" in e for e in eval_calc.validate(self.d, "compare").errors))

    def test_score_adds_cost_summary_and_features_table(self):
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(rep.errors, [])
        self.assertEqual(out["cost_summary"]["options"]["opt-a"]["tco"], 45360.0)
        self.assertEqual(out["cost_summary"]["cheapest"], "opt-b")
        with open(os.path.join(self.d, "features.md"), encoding="utf-8") as f:
            md = f.read()
        self.assertIn("## Cost (total cost of ownership over 36 months, USD)", md)
        self.assertIn("45,360.00", md)
        self.assertIn("unverified: b-plugin", md)


class AddEvidenceTest(Sandbox):
    def test_appends_next_free_id(self):
        rep, eid = eval_calc.add_evidence(self.d, "opt-a", "A new finding", "https://x.example.org/p", "PROBABLE", "independent", requirement_id="F-01")
        self.assertEqual((rep.errors, eid), ([], "E-011"))
        self.assertEqual(read(self.d, "evidence.json")[-1]["requirement_id"], "F-01")
        self.assertEqual(eval_calc.validate(self.d).errors, [])

    def test_rejects_bad_input(self):
        rep, eid = eval_calc.add_evidence(self.d, "opt-zzz", "x", "u", "MAYBE", "blog", requirement_id=None)
        self.assertIsNone(eid)
        self.assertGreaterEqual(len(rep.errors), 4)


class StatusTest(Sandbox):
    def test_finished_evaluation(self):
        st = eval_calc.status_report(self.d)
        self.assertEqual((st["action"], st["next_step"], st["problems"]), ("done", None, []))
        self.assertEqual(st["summary"]["top_option"], "Beta Queue")
        self.assertEqual(st["summary"]["top_score"], 78.0)
        self.assertTrue(st["summary"]["near_tie"])

    def test_no_evaluation_starts_with_define(self):
        st = eval_calc.status_report(os.path.join(self.tmp, "nothing"))
        self.assertEqual((st["exists"], st["action"], st["skill"]), (False, "start", "eval-define"))

    def test_partial_evaluation_continues_at_first_missing_step(self):
        s = read(self.d, "status.json")
        s["completed_steps"] = ["define", "analyze"]
        write(self.d, "status.json", s)
        st = eval_calc.status_report(self.d)
        self.assertEqual((st["action"], st["skill"]), ("continue", "eval-discover"))

    def test_stale_steps_rerun_earliest_first(self):
        s = read(self.d, "status.json")
        s["stale_steps"] = ["report", "compare"]
        write(self.d, "status.json", s)
        st = eval_calc.status_report(self.d)
        self.assertEqual((st["action"], st["next_step"], st["stale_steps"]), ("rerun", "compare", ["compare", "report"]))

    def test_problems_are_surfaced(self):
        open(os.path.join(self.d, "evidence.json"), "w").write("{broken")
        st = eval_calc.status_report(self.d)
        self.assertTrue(any("evidence.json" in p for p in st["problems"]))

    def test_archived_evaluations_are_listed(self):
        os.makedirs(os.path.join(self.tmp, "eval-archive", "old-2026-01-01"))
        self.assertEqual(eval_calc.status_report(self.d)["archived"], ["old-2026-01-01"])


class CostModelV2Test(Sandbox):
    def edit_cost(self, fn):
        c = read(self.d, "cost.json")
        fn(c)
        write(self.d, "cost.json", c)

    def test_hourly_prices_convert_to_monthly(self):
        comp = {"kind": "fixed_monthly", "amount": 0.2, "per": "hour", "quantity": 3}
        self.assertAlmostEqual(eval_calc._component_cost(comp, {})[0], 0.2 * 730 * 3)
        self.assertAlmostEqual(eval_calc._component_cost({"kind": "fixed_monthly", "amount": 1200, "per": "year"}, {})[0], 100)

    def test_per_is_validated(self):
        self.edit_cost(lambda c: c["options"]["opt-a"]["components"][1].update(per="fortnight"))
        self.assertTrue(any("per must be one of" in e for e in eval_calc.validate(self.d).errors))
        self.edit_cost(lambda c: c["options"]["opt-a"]["components"][1].update(per="month"))
        self.edit_cost(lambda c: c["options"]["opt-a"]["components"][0].update(per="hour"))
        self.assertTrue(any("per applies to fixed_monthly" in e for e in eval_calc.validate(self.d).errors))

    def test_capacity_steps_follow_the_driver(self):
        comp = {"kind": "fixed_monthly", "amount": 100, "quantity_driver": "A-01",
                "quantity_steps": [{"up_to": 6000000, "quantity": 3}, {"up_to": None, "quantity": 6}]}
        self.assertEqual(eval_calc._component_cost(comp, {"A-01": 5000000})[0], 300)
        self.assertEqual(eval_calc._component_cost(comp, {"A-01": 6000000})[0], 300)
        self.assertEqual(eval_calc._component_cost(comp, {"A-01": 50000000})[0], 600)

    def test_capacity_steps_change_the_scenario_totals(self):
        def fn(c):
            c["options"]["opt-b"]["components"][0].update(quantity_driver="A-01", quantity_steps=[{"up_to": 6000000, "quantity": 2}, {"up_to": None, "quantity": 4}])
            c["options"]["opt-b"]["components"][0].pop("quantity")
        self.edit_cost(fn)
        rep, res = eval_calc.compute_cost(self.d)
        self.assertEqual(rep.errors, [])
        # at the base volume (5M) 2 units x 150 = 300; at 2x (10M) 4 units = 600
        self.assertEqual(res["options"]["opt-b"]["components"][0]["monthly"], 300)
        self.assertEqual(res["options"]["opt-b"]["scenarios"]["growth (10M jobs/month)"], 2000 + (600 + 80) * 36)

    def test_steps_must_end_with_null_and_need_a_driver(self):
        self.edit_cost(lambda c: c["options"]["opt-b"]["components"][0].update(quantity_steps=[{"up_to": 5, "quantity": 1}]))
        errs = eval_calc.validate(self.d).errors
        self.assertTrue(any("quantity_steps" in e for e in errs))

    def test_assumed_component_needs_a_note_and_is_flagged(self):
        def fn(c):
            c["options"]["opt-b"]["components"].append({"id": "b-ops", "name": "Operations time", "kind": "fixed_monthly", "amount": 500, "assumed": True})
        self.edit_cost(fn)
        self.assertTrue(any("assumption_note" in e for e in eval_calc.validate(self.d).errors))
        self.edit_cost(lambda c: c["options"]["opt-b"]["components"][-1].update(assumption_note="4 engineer hours a month at 125 per hour"))
        rep, res = eval_calc.compute_cost(self.d)
        self.assertEqual(rep.errors, [])
        self.assertEqual(res["options"]["opt-b"]["assumed"], ["b-ops"])
        self.assertIn("b-ops", res["options"]["opt-b"]["evidence_gaps"])
        self.assertFalse(res["options"]["opt-b"]["incomplete"])
        self.assertEqual(res["options"]["opt-b"]["monthly"], 880)
        rep, out = eval_calc.compute(self.d)
        with open(os.path.join(self.d, "features.md"), encoding="utf-8") as f:
            self.assertIn("assumed: b-ops", f.read())


class ConfidenceV2Test(Sandbox):
    def run_score(self):
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(rep.errors, [])
        return out["criterion_scores"]

    def test_official_documentation_is_one_source_for_a_feature(self):
        # Alpha crit-core rests on two independent sources already; Beta crit-cost on one independent source
        self.assertEqual(self.run_score()["opt-b"]["crit-cost"]["confidence"], "medium")
        ev = read(self.d, "evidence.json")
        for e in ev:
            if e["evidence_id"] == "E-009":
                e["source_kind"], e["confidence"], e["requirement_id"] = "vendor", "PRIMARY", "N-02"  # N-02 is a non-functional requirement
        write(self.d, "evidence.json", ev)
        self.assertEqual(self.run_score()["opt-b"]["crit-cost"]["confidence"], "low")

    def test_vendor_documentation_gives_medium_for_functional_requirements(self):
        ev = read(self.d, "evidence.json")
        for e in ev:
            if e["evidence_id"] == "E-009":
                e["source_kind"], e["confidence"], e["requirement_id"] = "vendor", "PRIMARY", "F-01"  # F-01 is functional
        write(self.d, "evidence.json", ev)
        s = read(self.d, "scores.json")
        s["cell_values"]["opt-b"]["F-01"]["evidence_ids"] = ["E-009"]
        write(self.d, "scores.json", s)
        c = self.run_score()["opt-b"]["crit-core"]
        self.assertIn(c["confidence"], ("medium", "high"))

    def test_official_documentation_plus_an_independent_source_is_high(self):
        ev = read(self.d, "evidence.json")
        ev.append({"evidence_id": "E-050", "option_id": "opt-a", "requirement_id": "F-02", "finding": "docs", "source_url": "https://alpha.example.com/docs",
                   "source_date": "unknown", "gathered_on": "2026-01-01", "confidence": "PRIMARY", "source_kind": "vendor"})
        # opt-a crit-ops: N-01 is cited with E-003 (one independent source); add vendor docs for a functional requirement in the same criterion
        reqs = read(self.d, "requirements.json")
        for r in reqs:
            if r["id"] == "N-01":
                r["evidence_class"] = "feature"
        write(self.d, "requirements.json", reqs)
        ev[-1]["requirement_id"] = "N-01"
        write(self.d, "evidence.json", ev)
        self.assertEqual(self.run_score()["opt-a"]["crit-ops"]["confidence"], "high")

    def test_evidence_class_is_validated(self):
        reqs = read(self.d, "requirements.json")
        reqs[0]["evidence_class"] = "vibes"
        write(self.d, "requirements.json", reqs)
        self.assertTrue(any("evidence_class" in e for e in eval_calc.validate(self.d).errors))


class UnknownBoundsTest(Sandbox):
    def test_bounds_and_overtaking(self):
        s = read(self.d, "scores.json")
        for rid in ("F-02", "N-01", "N-02", "C-02"):
            s["cell_values"]["opt-a"][rid]["value"] = "unknown"
        write(self.d, "scores.json", s)
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(out["unknown_bounds"]["opt-a"]["unknown_cells"], 4)
        self.assertGreater(out["unknown_bounds"]["opt-a"]["if_unknowns_provided"], out["unknown_bounds"]["opt-a"]["as_scored"])
        self.assertEqual(out["ranking"][0], "opt-b")
        self.assertEqual(out["could_overtake_leader"], ["opt-a"])
        self.assertTrue(any("unknown values could change the leader" in w for w in rep.warnings))

    def test_no_unknowns_means_no_overtaking(self):
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(out["could_overtake_leader"], [])
        self.assertEqual(out["unknown_bounds"]["opt-a"]["if_unknowns_provided"], out["unknown_bounds"]["opt-a"]["as_scored"])


class QualityWarningsTest(Sandbox):
    def test_copied_rationale_is_flagged(self):
        s = read(self.d, "scores.json")
        for o in s["rationales"].values():
            for k in o:
                o[k] = "See the evidence."
        write(self.d, "scores.json", s)
        rep, out = eval_calc.compute(self.d)
        self.assertTrue(any("same rationale is used for" in w for w in rep.warnings))

    def test_gate_pass_without_evidence_is_flagged(self):
        ev = read(self.d, "evidence.json")
        for e in ev:
            if e["evidence_id"] == "E-001":
                e["requirement_id"] = "F-02"
        write(self.d, "evidence.json", ev)
        self.assertTrue(any("gate F-01 is marked pass for Alpha Queue" in w for w in eval_calc.validate(self.d).warnings))

    def test_sample_has_no_gate_warnings(self):
        self.assertFalse(any("gate " in w for w in eval_calc.validate(self.d).warnings))


class MissingCellsWarningTest(Sandbox):
    def test_one_warning_per_option(self):
        s = read(self.d, "scores.json")
        for rid in ("F-02", "N-02", "C-02"):
            del s["cell_values"]["opt-a"][rid]
        write(self.d, "scores.json", s)
        rep, out = eval_calc.compute(self.d)
        lines = [w for w in rep.warnings if "no cell value" in w]
        self.assertEqual(lines, ["Alpha Queue has no cell value for F-02, N-02, C-02; counted as unknown"])


class ScopeTest(Sandbox):
    def mark_out_of_scope(self, evidence_id):
        ev = read(self.d, "evidence.json")
        for e in ev:
            if e["evidence_id"] == evidence_id:
                e["scope"] = "out_of_scope"
        write(self.d, "evidence.json", ev)

    def test_cell_credited_only_from_out_of_scope_evidence_is_refused(self):
        self.mark_out_of_scope("E-001")      # the only source behind Alpha F-01 (provided)
        rep, out = eval_calc.compute(self.d)
        self.assertIsNone(out)
        self.assertTrue(any("Alpha Queue / F-01 is marked provided but every source behind it is out of scope" in e for e in rep.errors), rep.errors)

    def test_not_provided_with_out_of_scope_evidence_is_accepted(self):
        self.mark_out_of_scope("E-001")
        s = read(self.d, "scores.json")
        s["cell_values"]["opt-a"]["F-01"]["value"] = "not provided"
        write(self.d, "scores.json", s)
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(rep.errors, [])
        self.assertIsNotNone(out)

    def test_one_in_scope_source_is_enough(self):
        self.mark_out_of_scope("E-001")
        s = read(self.d, "scores.json")
        s["cell_values"]["opt-a"]["F-01"]["evidence_ids"] = ["E-001", "E-002"]
        write(self.d, "scores.json", s)
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(rep.errors, [])

    def test_scope_value_is_validated(self):
        ev = read(self.d, "evidence.json")
        ev[0]["scope"] = "elsewhere"
        write(self.d, "evidence.json", ev)
        self.assertTrue(any("scope must be" in e for e in eval_calc.validate(self.d).errors))

    def test_add_evidence_can_mark_scope(self):
        rep, eid = eval_calc.add_evidence(self.d, "opt-a", "A hosted registry", "https://x.example.org/r", "PRIMARY", "vendor", requirement_id="F-01", scope="out_of_scope")
        self.assertEqual(rep.errors, [])
        self.assertEqual(read(self.d, "evidence.json")[-1]["scope"], "out_of_scope")
        rep, eid = eval_calc.add_evidence(self.d, "opt-a", "x", "u", "PRIMARY", "vendor", requirement_id="F-01", scope="nowhere")
        self.assertIsNone(eid)


class PackageTest(Sandbox):
    def test_package_is_optional_and_must_be_text(self):
        o = read(self.d, "options.json")
        o[0]["package"] = "Alpha Enterprise 2026.9 plus the registry add-on"
        write(self.d, "options.json", o)
        self.assertEqual(eval_calc.validate(self.d).errors, [])
        o[0]["package"] = ""
        write(self.d, "options.json", o)
        self.assertTrue(any("package must be a non-empty string" in e for e in eval_calc.validate(self.d).errors))


class MatrixTest(unittest.TestCase):
    def csv(self, text):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "m.csv")
        with open(p, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return p

    TABLE = ("Criterion,Weight,Alpha,Beta,Gamma,Rationale\n"
             "One,45,5,3,2,because\n"
             "Two,30,4,4,3,because\n"
             "Three,25,2,5,3,because\n")

    def test_totals_ranking_and_text_columns_are_ignored(self):
        r = eval_calc.matrix_report(self.csv(self.TABLE))
        self.assertEqual(r["options"], ["Alpha", "Beta", "Gamma"])
        # Alpha: (45*5 + 30*4 + 25*2) / 5 = 79 ; Beta: (135 + 120 + 125) / 5 = 76 ; Gamma: (90 + 90 + 75) / 5 = 51
        self.assertEqual(r["totals"], {"Alpha": 79.0, "Beta": 76.0, "Gamma": 51.0})
        self.assertEqual(r["ranking"], ["Alpha", "Beta", "Gamma"])

    def test_sensitivity_reports_flips_and_smallest_lead(self):
        r = eval_calc.matrix_report(self.csv(self.TABLE))
        self.assertEqual(r["single_weight_tests"], 6)
        # Alpha leads Beta by 3; raising "Three" by 5 (others rescaled) gives Beta 77.6 against Alpha 76.4
        self.assertTrue(any(f["criterion"] == "Three" and f["delta"] == 5 and f["leader"] == "Beta" for f in r["leader_changes"]), r["leader_changes"])
        # lowering "One" by 5 (others rescaled) gives Beta 77.5 against Alpha 77.1
        self.assertEqual(r["smallest_lead"], {"lead": 0.4, "criterion": "One", "delta": -5})

    def test_equal_weights_view(self):
        r = eval_calc.matrix_report(self.csv(self.TABLE))
        self.assertEqual(r["equal_weights_ranking"][0], "Beta")   # (3+4+5)/15 beats (5+4+2)/15

    def test_rejects_tables_without_the_expected_columns(self):
        with self.assertRaises(ValueError):
            eval_calc.matrix_report(self.csv("Name,Score\nx,1\n"))
        with self.assertRaises(ValueError):
            eval_calc.matrix_report(self.csv("Criterion,Weight,Alpha\nOne,100,5\n"))

    def test_cli(self):
        import subprocess
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "shared", "eval_calc.py"), "matrix", self.csv(self.TABLE)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["ranking"][0], "Alpha")
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "shared", "eval_calc.py"), "matrix", "no-such-file.csv"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)


class BiasChecksTest(unittest.TestCase):
    def opts(self, providers):
        return [{"option_id": "o%d" % i, "name": "Option %d" % i, "provider": p} for i, p in enumerate(providers)]

    def check(self, providers=("A", "B", "C"), reqs=(), vendor_rows=(), independent_rows=(), cost=None):
        opts = self.opts(providers)
        ids = [o["option_id"] for o in opts]
        ev = []
        for i, o in enumerate(ids):
            for _ in range(vendor_rows[i] if vendor_rows else 1):
                ev.append({"option_id": o, "source_kind": "vendor"})
            for _ in range(independent_rows[i] if independent_rows else 0):
                ev.append({"option_id": o, "source_kind": "independent"})
        rep = eval_calc.Report()
        out = eval_calc.bias_checks(list(reqs), opts, ev, ids, {o["option_id"]: o["name"] for o in opts}, cost, rep)
        return out, rep.warnings

    def test_provider_concentration_warns_when_most_options_share_a_provider(self):
        out, warns = self.check(("AWS", "AWS", "AWS", "Other"), independent_rows=(1, 1, 1, 1))
        self.assertEqual(out["provider_concentration"]["counts"], {"AWS": 3, "Other": 1})
        self.assertEqual(out["provider_concentration"]["largest_share"], 0.75)
        self.assertTrue(any("3 of 4 profiled options come from AWS" in w for w in warns), warns)

    def test_spread_of_providers_is_quiet(self):
        out, warns = self.check(("A", "B", "A", "C"), independent_rows=(1, 1, 1, 1))
        self.assertFalse(any("come from" in w for w in warns))

    def test_two_options_are_too_few_to_judge_concentration(self):
        out, warns = self.check(("AWS", "AWS"), independent_rows=(1, 1))
        self.assertFalse(any("come from" in w for w in warns))

    def test_missing_providers_are_reported_not_hidden(self):
        opts = [{"option_id": "o%d" % i, "name": "O%d" % i} for i in range(3)]
        rep = eval_calc.Report()
        out = eval_calc.bias_checks([], opts, [], [o["option_id"] for o in opts], {o["option_id"]: o["name"] for o in opts}, None, rep)
        self.assertEqual(out["provider_concentration"]["profiled_with_provider"], 0)

    def test_assumed_gate_warns_and_assumed_requirement_is_listed(self):
        reqs = [{"id": "G-01", "text": "Runs on AWS", "gate": True, "basis": "assumed"}, {"id": "X-01", "text": "Nice to have", "gate": False, "basis": "assumed"},
                {"id": "Y-01", "text": "Stated", "gate": True}]
        out, warns = self.check(reqs=reqs, independent_rows=(1, 1, 1))
        self.assertEqual([a["id"] for a in out["assumed_requirements"]], ["G-01", "X-01"])
        self.assertEqual([w for w in warns if "assumption" in w], ["gate G-01 is an assumption, not something the user stated; options excluded or ranked by it need the user's confirmation"])

    def test_all_vendor_evidence_is_called_out(self):
        out, warns = self.check()
        self.assertTrue(any("every finding comes from the options' own publications" in w for w in warns), warns)

    def test_unequal_independent_coverage_is_called_out(self):
        out, warns = self.check(independent_rows=(2, 0, 1))
        self.assertTrue(any("independent sources exist for some options but not for Option 1" in w for w in warns), warns)

    def test_equal_independent_coverage_is_quiet(self):
        out, warns = self.check(independent_rows=(1, 1, 1))
        self.assertFalse(any("independent" in w or "own publications" in w for w in warns))

    def test_cost_comparison_covering_some_options_only_is_called_out(self):
        cost = {"options": {"o0": {"incomplete": False}, "o1": {"incomplete": True}, "o2": {"incomplete": False}}}
        out, warns = self.check(independent_rows=(1, 1, 1), cost=cost)
        self.assertEqual(out["cost_comparable"], {"complete": 2, "total": 3})
        self.assertTrue(any("cost compares only 2 of 3 options" in w for w in warns))

    def test_fully_priced_or_fully_unpriced_cost_is_quiet(self):
        for flags in (False, True):
            cost = {"options": {"o%d" % i: {"incomplete": flags} for i in range(3)}}
            out, warns = self.check(independent_rows=(1, 1, 1), cost=cost)
            self.assertFalse(any("cost compares only" in w for w in warns))


class BiasFieldsTest(Sandbox):
    def test_basis_and_provider_are_validated(self):
        reqs = read(self.d, "requirements.json")
        reqs[0]["basis"] = "guessed"
        write(self.d, "requirements.json", reqs)
        self.assertTrue(any("basis must be stated or assumed" in e for e in eval_calc.validate(self.d).errors))
        reqs[0]["basis"] = "assumed"
        write(self.d, "requirements.json", reqs)
        self.assertEqual(eval_calc.validate(self.d).errors, [])
        o = read(self.d, "options.json")
        o[0]["provider"] = " "
        write(self.d, "options.json", o)
        self.assertTrue(any("provider must be a non-empty string" in e for e in eval_calc.validate(self.d).errors))

    def test_score_writes_bias_checks_and_an_assumed_gate_warning(self):
        reqs = read(self.d, "requirements.json")
        reqs[0]["basis"] = "assumed"       # F-01 is a gate
        write(self.d, "requirements.json", reqs)
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(rep.errors, [])
        self.assertEqual(out["bias_checks"]["assumed_requirements"][0]["id"], "F-01")
        self.assertTrue(any("gate F-01 is an assumption" in w for w in rep.warnings))
        self.assertEqual(out["bias_checks"]["cost_comparable"], {"complete": 2, "total": 2})
        self.assertIn("source_mix", out["bias_checks"])


class GapsTest(Sandbox):
    def test_lists_unknown_and_unsupported_most_important_first(self):
        s = read(self.d, "scores.json")
        s["cell_values"]["opt-b"]["N-01"]["value"] = "unknown"       # a must in the weight-30 criterion
        s["cell_values"]["opt-b"]["F-02"]["value"] = "unknown"       # a should in the weight-50 criterion
        write(self.d, "scores.json", s)
        rep, out = eval_calc.find_gaps(self.d)
        self.assertEqual(rep.errors, [])
        ids = [x["requirement_id"] for x in out["opt-b"]["research_first"]]
        self.assertLess(ids.index("N-01"), ids.index("F-02"))   # a must outranks a should
        states = {x["requirement_id"]: x["state"] for x in out["opt-a"]["research_first"]}
        self.assertEqual(states["N-02"], "unsupported")          # not provided, but no evidence behind it
        self.assertNotIn("F-01", states)                         # backed by non-weak evidence

    def test_excluded_options_and_limit(self):
        rep, out = eval_calc.find_gaps(self.d, limit=1)
        self.assertEqual(set(out), {"opt-a", "opt-b"})
        self.assertLessEqual(len(out["opt-a"]["research_first"]), 1)
        self.assertGreaterEqual(out["opt-a"]["total_gaps"], len(out["opt-a"]["research_first"]))

    def test_cli(self):
        import subprocess
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "shared", "eval_calc.py"), "gaps", self.d, "--limit", "2"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("opt-a", json.loads(r.stdout))


class StatusCommandsTest(Sandbox):
    def test_complete_creates_status_for_define_and_keeps_order(self):
        d = os.path.join(self.tmp, "fresh")
        rep, st = eval_calc.complete_step(d, "define", slug="my-case", today="2026-01-02")
        self.assertEqual((rep.errors, st["completed_steps"], st["solution_slug"], st["evaluation_date"]), ([], ["define"], "my-case", "2026-01-02"))
        rep, st = eval_calc.complete_step(d, "analyze", today="2026-01-03")
        self.assertEqual(st["completed_steps"], ["define", "analyze"])
        self.assertEqual(st["current_step"], "analyze")

    def test_complete_refuses_to_skip_a_step(self):
        d = os.path.join(self.tmp, "fresh")
        eval_calc.complete_step(d, "define")
        rep, st = eval_calc.complete_step(d, "compare")
        self.assertIsNone(st)
        self.assertTrue(any("step analyze is not complete" in e for e in rep.errors))

    def test_complete_without_define_is_refused(self):
        rep, st = eval_calc.complete_step(os.path.join(self.tmp, "none"), "analyze")
        self.assertIsNone(st)
        self.assertTrue(any("eval-define first" in e for e in rep.errors))

    def test_report_sets_the_report_date_and_clears_stale(self):
        s = read(self.d, "status.json")
        s["stale_steps"] = ["compare", "report"]
        write(self.d, "status.json", s)
        rep, st = eval_calc.complete_step(self.d, "report", today="2027-02-03")
        self.assertEqual((st["report_date"], st["stale_steps"]), ("2027-02-03", ["compare"]))

    def test_changed_marks_only_completed_dependents_in_order(self):
        rep, stale = eval_calc.mark_changed(self.d, "weights")
        self.assertEqual(stale, ["compare", "report"])
        s = read(self.d, "status.json")
        s["completed_steps"], s["stale_steps"] = ["define", "analyze", "discover"], []
        write(self.d, "status.json", s)
        rep, stale = eval_calc.mark_changed(self.d, "requirements")
        self.assertEqual(stale, ["analyze", "discover"])
        rep, stale = eval_calc.mark_changed(self.d, "scores")
        self.assertEqual(stale, ["analyze", "discover"])  # report is not complete, so it is not marked stale

    def test_changed_rejects_unknown_topics(self):
        rep, stale = eval_calc.mark_changed(self.d, "vibes")
        self.assertIsNone(stale)

    def test_apply_weights_writes_rank_sum_and_zeroes_the_rest(self):
        rep, wts = eval_calc.apply_weights(self.d, ["crit-ops", "crit-core"])
        self.assertEqual(wts, {"crit-ops": 67, "crit-core": 33})
        c = read(self.d, "criteria.json")
        self.assertEqual({x["id"]: x["weight"] for x in c["criteria"]}, {"crit-core": 33, "crit-ops": 67, "crit-cost": 0})
        self.assertEqual(eval_calc.validate(self.d).errors, [])

    def test_apply_weights_rejects_unknown_ids(self):
        rep, wts = eval_calc.apply_weights(self.d, ["crit-core", "crit-zzz"])
        self.assertIsNone(wts)
        self.assertTrue(any("crit-zzz" in e for e in rep.errors))

    def test_cli_commands(self):
        import subprocess
        script = os.path.join(ROOT, "shared", "eval_calc.py")
        r = subprocess.run([sys.executable, "-I", script, "changed", self.d, "weights"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), ["compare", "report"])
        r = subprocess.run([sys.executable, "-I", script, "complete", self.d, "compare"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["stale_steps"], ["report"])
        r = subprocess.run([sys.executable, "-I", script, "weights", "crit-core", "crit-ops", "--apply", self.d], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run([sys.executable, "-I", script, "weights", "nope", "--apply", self.d], capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)


class RankTest(unittest.TestCase):
    def test_gap_count_breaks_tie_first(self):
        cs = {"x": {"c": 3}, "y": {"c": 5}}
        ranking, ties = eval_calc._rank(["x", "y"], {"x": 80.0, "y": 79.0}, cs, {"x": 0, "y": 2}, {"c": 100})
        self.assertEqual(ranking, ["x", "y"])
        self.assertEqual(ties[0]["tie_break"], "fewer must-have gaps")

    def test_clear_margin_is_not_a_tie(self):
        cs = {"x": {"c": 3}, "y": {"c": 5}}
        ranking, ties = eval_calc._rank(["x", "y"], {"x": 80.0, "y": 70.0}, cs, {"x": 5, "y": 0}, {"c": 100})
        self.assertEqual((ranking, ties), (["x", "y"], []))


if __name__ == "__main__":
    unittest.main()
