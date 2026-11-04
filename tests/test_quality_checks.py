"""Checks added from the scorecard: evidence dates, citations, confidence the evidence supports, gate coverage and report consistency."""
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
GATEWAY = os.path.join(ROOT, "examples", "gateway-like", "eval")


def read(d, name):
    with open(os.path.join(d, name), encoding="utf-8") as f:
        return json.load(f)


def write(d, name, data):
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class Base(unittest.TestCase):
    src = SAMPLE

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(self.src, self.d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def evidence(self, eid, **kw):
        ev = read(self.d, "evidence.json")
        for e in ev:
            if e["evidence_id"] == eid:
                e.update(kw)
        write(self.d, "evidence.json", ev)

    def score(self, oid, rid, **kw):
        s = read(self.d, "scores.json")
        s["requirement_scores"][oid][rid].update(kw)
        write(self.d, "scores.json", s)

    def errors(self, before=None):
        return eval_calc.validate(self.d, before).errors

    def warnings(self):
        return eval_calc.validate(self.d).warnings


class EvidenceRows(Base):
    def test_samples_are_clean(self):
        for d in (SAMPLE, GATEWAY):
            self.assertEqual(eval_calc.validate(d, "report").errors, [], d)

    def test_dates(self):
        self.evidence("E-002", gathered_on="2999-01-01")
        self.assertTrue(any("in the future" in e for e in self.errors()))
        self.evidence("E-002", gathered_on="2026-10-01", source_date="spring")
        self.assertTrue(any("source_date must be" in e for e in self.errors()))
        self.evidence("E-002", source_date="2026-11")
        self.assertTrue(any("after gathered_on" in e for e in self.errors()))
        self.evidence("E-002", source_date="2026-10")
        self.assertFalse(any("E-002" in e for e in self.errors()))
        self.evidence("E-002", source_date="unknown")
        self.assertFalse(any("E-002" in e for e in self.errors()))

    def test_empty_finding_or_url(self):
        self.evidence("E-002", finding=" ")
        self.assertTrue(any("finding is empty" in e for e in self.errors()))

    def test_labels_that_do_not_fit_the_source(self):
        self.evidence("E-004", confidence="CONFIRMED")
        self.assertTrue(any("CONFIRMED means two" in w for w in self.warnings()))
        self.evidence("E-002", confidence="PRIMARY")
        self.assertTrue(any("PRIMARY is the source itself" in w for w in self.warnings()))

    def test_inherited_evidence_needs_a_base(self):
        self.evidence("E-002", inherited_from_oss=True)  # opt-a records oss_base null
        self.assertTrue(any("inherited_from_oss" in e for e in self.errors()))


class Citations(Base):
    def test_a_score_cites_its_own_option(self):
        self.score("opt-a", "F-02", evidence_ids=["E-006"])
        self.assertTrue(any("evidence about opt-b" in e for e in self.errors()))

    def test_a_score_citing_another_requirement_warns(self):
        self.score("opt-a", "F-02", evidence_ids=["E-004"])
        self.assertTrue(any("evidence for requirement C-01" in w for w in self.warnings()))

    def test_feature_cells_cite_their_own_option(self):
        f = read(self.d, "features.json")
        f[0]["cells"]["opt-a"]["evidence_ids"] = ["E-006"]
        write(self.d, "features.json", f)
        self.assertTrue(any("features.json" in e and "opt-b" in e for e in self.errors()))

    def test_options_are_never_named_in_criteria_or_requirements(self):
        c = read(self.d, "criteria.json")
        c["criteria"][0]["name"] = "Core like Beta Queue"
        write(self.d, "criteria.json", c)
        self.assertTrue(any("names the option Beta Queue" in e for e in self.errors()))

    def test_vague_requirement_warns_unless_pinned_down(self):
        r = read(self.d, "requirements.json")
        r[2]["text"] = "Fast job pickup"
        write(self.d, "requirements.json", r)
        self.assertTrue(any("is vague" in w for w in self.warnings()))
        r[2]["text"] = "Fast job pickup: p95 under 200 ms"
        write(self.d, "requirements.json", r)
        self.assertFalse(any("is vague" in w for w in self.warnings()))


class Confidence(Base):
    def compute(self):
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(rep.errors, [])
        return rep, out

    def test_overclaimed_confidence_is_lowered_with_a_warning(self):
        self.score("opt-a", "F-02", confidence="high")  # one independent source: medium at most
        rep, out = self.compute()
        self.assertEqual(out["requirement_scores"]["opt-a"]["F-02"]["confidence"], "medium")
        self.assertTrue(any("claims high confidence" in w for w in rep.warnings))

    def test_disputed_evidence_confirms_nothing(self):
        self.evidence("E-002", confidence="DISPUTED")
        rep, out = self.compute()
        self.assertEqual(out["requirement_scores"]["opt-a"]["F-02"]["confidence"], "low")

    def test_vendor_docs_count_for_features_not_measures(self):
        ev = [e for e in read(self.d, "evidence.json")]
        self.assertEqual(eval_calc.supported_confidence([{"confidence": "PRIMARY", "source_kind": "vendor", "source_url": "https://v.example.com"}],
                                                        {"type": "functional"}), "medium")
        self.assertEqual(eval_calc.supported_confidence([{"confidence": "PRIMARY", "source_kind": "vendor", "source_url": "https://v.example.com"}],
                                                        {"type": "non-functional"}), "low")
        self.assertTrue(ev)

    def test_a_cap_is_announced(self):
        self.score("opt-a", "F-02", score=5, evidence_ids=[])
        rep, out = self.compute()
        self.assertTrue(out["requirement_scores"]["opt-a"]["F-02"]["capped"])
        self.assertTrue(any("capped at 2" in w for w in rep.warnings))

    def test_zero_without_evidence_warns(self):
        self.score("opt-a", "F-02", score=0, evidence_ids=[])
        rep, out = self.compute()
        self.assertTrue(any("scored 0 with no evidence" in w for w in rep.warnings))


class GatesAndStatus(Base):
    def test_every_gate_has_a_rubric_and_every_option_in_play_a_verdict(self):
        c = read(self.d, "criteria.json")
        c["gates"][0]["verdicts"].pop("opt-b")
        write(self.d, "criteria.json", c)
        self.assertTrue(any("no verdict for opt-b" in e for e in self.errors()))
        c["gates"] = c["gates"][:1]
        write(self.d, "criteria.json", c)
        self.assertTrue(any("has no rubric" in e for e in self.errors()))

    def test_judged_clauses_cite_evidence(self):
        c = read(self.d, "criteria.json")
        c["gates"][0]["verdicts"]["opt-a"]["clauses"][0]["evidence_ids"] = []
        write(self.d, "criteria.json", c)
        self.assertTrue(any("cites no evidence" in e for e in self.errors()))

    def test_steps_complete_in_order_and_dates_agree(self):
        s = read(self.d, "status.json")
        s["completed_steps"] = ["define", "compare"]
        s["report_date"] = "2026-01-01"
        write(self.d, "status.json", s)
        errs = self.errors()
        self.assertTrue(any("steps complete in order" in e for e in errs))
        self.assertTrue(any("before evaluation_date" in e for e in errs))

    def test_scores_edited_after_scoring_are_out_of_date(self):
        self.assertEqual(self.errors("report"), [])
        c = read(self.d, "criteria.json")
        c["criteria"][0]["weight"] -= 20
        c["criteria"][1]["weight"] += 20
        write(self.d, "criteria.json", c)
        self.assertTrue(any("out of date" in e for e in self.errors("report")))
        self.assertFalse(any("out of date" in e for e in self.errors()))  # only the report step demands current scores


class OrchestratorStatus(Base):
    def test_an_edit_after_scoring_is_not_done(self):
        self.assertEqual(eval_calc.status_report(self.d)["action"], "done")
        c = read(self.d, "criteria.json")
        c["criteria"][0]["weight"] -= 20
        c["criteria"][1]["weight"] += 20
        write(self.d, "criteria.json", c)
        st = eval_calc.status_report(self.d)
        self.assertEqual((st["action"], st["next_step"]), ("rerun", "compare"))
        self.assertTrue(any("out of date" in p for p in st["problems"]))


class ReportCheck(Base):
    def edit(self, old, new):
        p = os.path.join(self.d, "report.md")
        text = open(p, encoding="utf-8").read()
        self.assertIn(old, text)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text.replace(old, new, 1))
        return report_draft.check(self.d)

    def test_sample_report_passes(self):
        self.assertEqual(report_draft.check(self.d), [])

    def test_provenance_line(self):
        self.assertTrue(any("provenance" in p for p in self.edit("Cost mode: weighted.", "Cost mode: separate.")))

    def test_decision_table_scores_and_order(self):
        self.assertTrue(any("decision table gives Alpha Queue" in p for p in self.edit("| 1 | Alpha Queue | 71.6 |", "| 1 | Alpha Queue | 72.6 |")))

    def test_the_leader_comes_first(self):
        probs = self.edit("Alpha Queue leads Beta Queue", "Beta Queue trails Alpha Queue")
        self.assertTrue(any("names Beta Queue first" in p for p in probs))

    def test_lead_quoted_in_points(self):
        self.assertTrue(any("lead is 6 points" in p for p in self.edit("by about one point", "by 6 points")))
        self.assertEqual(self.edit("by 6 points", "by 1.1 points"), [])

    def test_near_tie_is_not_decisive(self):
        probs = self.edit("so the choice is not clear-cut and should be treated as a near-tie", "a near-tie, yet Alpha is the clear winner")
        self.assertTrue(any("clear winner" in p for p in probs))

    def test_legend_does_not_count_as_the_confidence(self):
        probs = self.edit("**Confidence: medium.**", "")
        self.assertTrue(any("states no confidence level" in p for p in probs))
        self.assertFalse(any("confidence is high" in p for p in probs))

    def test_excluded_option_listed_and_never_recommended(self):
        probs = self.edit("Alpha's edge is operability", "Gamma Queue is cheaper. Alpha's edge is operability")
        self.assertTrue(any("mentions Gamma Queue" in p for p in probs))
        self.assertEqual(self.edit("Gamma Queue is cheaper.", "Gamma Queue failed the delivery gate."), [])

    def test_every_unassessed_factor_is_named(self):
        c = read(self.d, "criteria.json")
        c["not_assessed"].append("Roadmap commitments")
        write(self.d, "criteria.json", c)
        self.assertTrue(any("Roadmap commitments" in p for p in report_draft.check(self.d)))


if __name__ == "__main__":
    unittest.main()
