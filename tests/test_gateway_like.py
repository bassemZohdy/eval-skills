"""The gateway-like fixture: a gated, multi-component, three-option evaluation that exercises sections A to E together."""
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
import report_draft  # noqa: E402

FIXTURE = os.path.join(ROOT, "examples", "gateway-like", "eval")
PROSE = {"recommendation": "Gateway One and Gateway Two are a near-tie; shortlist both and run the POC tests.", "confidence": "low", "confidence_why": "The lead is under the meaningful gap.",
         "options": {"opt-1": ["Broad support", "Package component unconfirmed on the platform"], "opt-2": ["Open core", "Local support is weak"]}, "bias": "Two options share one open-source core.",
         "cost": "Cost was not modelled.", "sensitivity": "The order holds in every scenario.", "next_steps": ["Run POC test P1."], "risks": ["Gateway Two's support in the customer's country is unclear."],
         "excluded": "Gateway Three needs a vendor-hosted licence service."}


def read(d, n):
    with open(os.path.join(d, n), encoding="utf-8") as f:
        return json.load(f)


def write(d, n, data):
    with open(os.path.join(d, n), "w", encoding="utf-8") as f:
        json.dump(data, f)


class GatewayLike(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(FIXTURE, self.d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_validates_and_scores(self):
        self.assertEqual(eval_calc.validate(self.d).errors, [])
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(rep.errors, [])
        self.assertEqual(out["ranking"], ["opt-1", "opt-2"])
        self.assertEqual([x["option_id"] for x in out["excluded"]], ["opt-3"])

    def test_six_gates_with_a_documented_pass_and_a_not_met(self):
        gates = read(self.d, "criteria.json")["gates"]
        self.assertEqual(len(gates), 6)
        verdicts = [v for g in gates for v in g["verdicts"].values()]
        self.assertTrue(any(v["verdict"] == "PASS" and v["basis"] == "documented" and v["confirm_by"] for v in verdicts))
        self.assertTrue(any(v["verdict"] == "NOT MET" for v in verdicts))

    def test_a_package_has_two_components_with_lifecycle(self):
        for o in read(self.d, "options.json"):
            self.assertEqual(len(o["package"]["components"]), 2)
            self.assertTrue(all(c["lifecycle"] for c in o["package"]["components"]))

    def test_oss_inheritance_is_checked_for_every_option(self):
        rep, out = eval_calc.compute(self.d)
        self.assertFalse(any("oss_base" in w for w in rep.warnings))
        o = read(self.d, "options.json")
        del o[1]["oss_base"]
        write(self.d, "options.json", o)
        rep, out = eval_calc.compute(self.d)
        self.assertTrue(any("oss_base is set for" in w for w in rep.warnings))

    def test_inherited_only_scores_are_capped_and_queued(self):
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(out["requirement_scores"]["opt-1"]["F-02"]["confidence"], "medium")
        rep, q = eval_calc.verify_queue(self.d)
        self.assertTrue(any("inherited from open source only" in x["reasons"] for x in q))

    def test_source_code_evidence_and_candidates_and_open_items(self):
        ev = read(self.d, "evidence.json")
        self.assertTrue(any(e["source_kind"] == "source_code" for e in ev))
        self.assertEqual(len(read(self.d, "candidate_requirements.json")), 1)
        items = read(self.d, "open_items.json")
        self.assertTrue({"poc_test", "vendor_question", "contract_term"} <= {i["owner_type"] for i in items})

    def test_scope_tags_never_change_the_scores(self):
        totals = eval_calc.compute(self.d)[1]["totals"]
        f = read(self.d, "features.json")
        for row in f:
            for c in row["cells"].values():
                c["scope_tags"] = ["saas"]
        write(self.d, "features.json", f)
        self.assertEqual(eval_calc.compute(self.d)[1]["totals"], totals)

    def test_incumbent_role_is_recorded(self):
        self.assertIn("Incumbent role: extend", open(os.path.join(self.d, "solution.md"), encoding="utf-8").read())

    def test_report_draft_check_and_export(self):
        eval_calc.compute(self.d)
        report_draft.draft(self.d, PROSE)
        text = open(os.path.join(self.d, "report.md"), encoding="utf-8").read()
        self.assertIn("Eligibility: 2 of 3 options pass every gate", text)
        self.assertIn("## Packages scored", text)
        self.assertEqual(report_draft.check(self.d), [])
        D = export_report.Data(self.d)
        self.assertEqual(export_report.static_problems(D, export_report.build_html(D)), [])


if __name__ == "__main__":
    unittest.main()
