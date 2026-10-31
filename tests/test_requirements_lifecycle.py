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


class Retired(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(SAMPLE, self.d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reused_id_is_rejected(self):
        r = read(self.d, "requirements.json")
        r.append(dict(r[0]))
        write(self.d, "requirements.json", r)
        self.assertTrue(any("duplicate requirement id" in e for e in eval_calc.validate(self.d).errors))

    def test_scorer_ignores_a_retired_requirement(self):
        # F-02 is a "should"; retire it and take it out of its criterion, then add a replacement so the category keeps two
        reqs = read(self.d, "requirements.json")
        new = dict(next(r for r in reqs if r["id"] == "F-02"), id="F-03", text="Recurring schedules")
        for r in reqs:
            if r["id"] == "F-02":
                r["retired"] = True
        reqs.append(new)
        write(self.d, "requirements.json", reqs)
        c = read(self.d, "criteria.json")
        ids = c["criteria"][0]["requirement_ids"]
        ids[ids.index("F-02")] = "F-03"
        write(self.d, "criteria.json", c)
        s = read(self.d, "scores.json")
        for o in s["requirement_scores"].values():
            o["F-03"] = o["F-02"]  # F-02 stays in the file; it must not count
            o["F-02"] = {"score": 0, "confidence": "low", "rationale": "retired", "evidence_ids": []}
        write(self.d, "scores.json", s)
        base = eval_calc.compute(self.d)[1]["totals"]
        s["requirement_scores"]["opt-a"]["F-02"]["score"] = 5
        write(self.d, "scores.json", s)
        rep, out = eval_calc.compute(self.d)
        self.assertEqual(rep.errors, [])
        self.assertEqual(out["totals"], base)

    def test_a_retired_requirement_in_a_criterion_is_an_error(self):
        reqs = read(self.d, "requirements.json")
        reqs[1]["retired"] = True
        write(self.d, "requirements.json", reqs)
        self.assertTrue(any("is retired" in e for e in eval_calc.validate(self.d).errors))


if __name__ == "__main__":
    unittest.main()


class ReportAdditions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(SAMPLE, self.d)
        sys.path.insert(0, os.path.join(ROOT, "shared"))
        import report_draft
        self.rd = report_draft
        self.prose = {"recommendation": "Alpha Queue leads; near-tie.", "confidence": "low", "confidence_why": "x", "options": {"opt-a": ["a", "b"], "opt-b": ["a", "b"]},
                      "bias": "b", "cost": "c", "sensitivity": "s", "next_steps": ["n"], "risks": ["r"], "excluded": "e", "changes": "Beta shipped 2.5 after the evidence date."}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def text(self):
        self.rd.draft(self.d, self.prose)
        return open(os.path.join(self.d, "report.md"), encoding="utf-8").read()

    def test_report_lists_candidates_not_assessed_and_changes(self):
        t = self.text()
        self.assertIn("## Candidate requirements", t)
        self.assertIn("Not assessed: Operating effort and team skills", t)
        self.assertIn("### Changes since evidence was gathered", t)
        self.assertEqual(self.rd.check(self.d), [])

    def test_check_requires_the_not_assessed_line(self):
        t = self.text().replace("Not assessed:", "Skipped:")
        open(os.path.join(self.d, "report.md"), "w", encoding="utf-8").write(t)
        self.assertTrue(any("Not assessed" in p for p in self.rd.check(self.d)))

    def test_candidate_needs_its_fields(self):
        write(self.d, "candidate_requirements.json", [{"id": "CR-1", "text": "x"}])
        self.assertTrue(any("candidate_requirements.json" in e for e in eval_calc.validate(self.d).errors))

    def test_candidates_never_enter_the_scores(self):
        base = eval_calc.compute(self.d)[1]["totals"]
        c = read(self.d, "candidate_requirements.json")
        c.append(dict(c[0], id="CR-2"))
        write(self.d, "candidate_requirements.json", c)
        self.assertEqual(eval_calc.compute(self.d)[1]["totals"], base)


class SourceCodeAndQueues(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(SAMPLE, self.d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def code_row(self, **kw):
        ev = read(SAMPLE, "evidence.json")
        row = dict(ev[0], evidence_id="E-050", source_kind="source_code", source_url="https://github.com/x/y/blob/abc123/src/queue.go@abc123", confidence="PROBABLE", lines="120-148")
        row.update(kw)
        ev.append(row)
        write(self.d, "evidence.json", ev)
        return [e for e in eval_calc.validate(self.d).errors if "cited by no" not in e]

    def test_source_code_needs_commit_lines_and_probable(self):
        self.assertEqual(self.code_row(), [])
        self.assertTrue(any("line range" in e for e in self.code_row(lines="")))
        self.assertTrue(any("path@commit" in e for e in self.code_row(source_url="https://github.com/x/y", pin="v1")))
        self.assertTrue(any("PROBABLE at best" in e for e in self.code_row(confidence="CONFIRMED")))
        self.assertEqual(self.code_row(confidence="CONFIRMED", tested=True), [])

    def test_open_items_resolve_their_links(self):
        items = read(self.d, "open_items.json")
        items[0]["linked"] = "Z-99"
        write(self.d, "open_items.json", items)
        self.assertTrue(any("neither a requirement nor a gate" in e for e in eval_calc.validate(self.d).errors))

    def test_poc_test_needs_an_id_and_gate_tests_must_exist(self):
        items = read(self.d, "open_items.json")
        del items[0]["test_id"]
        write(self.d, "open_items.json", items)
        errs = eval_calc.validate(self.d).errors
        self.assertTrue(any("test_id" in e for e in errs))
        self.assertTrue(any("names test P1" in e for e in errs))

    def test_open_item_owner_type_is_checked(self):
        items = read(self.d, "open_items.json")
        items[2]["owner_type"] = "hope"
        write(self.d, "open_items.json", items)
        self.assertTrue(any("owner_type" in e for e in eval_calc.validate(self.d).errors))

    def test_verify_queue_lists_documented_gates_first(self):
        rep, q = eval_calc.verify_queue(self.d)
        self.assertEqual(rep.errors, [])
        self.assertEqual(q[0]["kind"], "gate")
        self.assertIn("documented only", q[0]["reasons"])
        pri = [x["priority"] for x in q]
        self.assertEqual(pri, sorted(pri, reverse=True))

    def test_verify_queue_flags_inherited_only_scores(self):
        ev = read(self.d, "evidence.json")
        for e in ev:
            if e["evidence_id"] == "E-007":
                e["inherited_from_oss"] = True
        write(self.d, "evidence.json", ev)
        rep, q = eval_calc.verify_queue(self.d)
        self.assertTrue(any("inherited from open source only" in x["reasons"] for x in q))

    def test_deciding_cells_hold_all_gates_and_the_must_haves_behind_the_lead(self):
        rep, out = eval_calc.compute(self.d)
        dc = out["deciding_cells"]
        self.assertEqual(len(dc["gates"]), 5)
        self.assertTrue(dc["requirements"])
        self.assertTrue(all(x["requirement_id"] in ("F-01", "N-01", "N-03", "C-01") for x in dc["requirements"]))


class Packages(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(SAMPLE, self.d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_lifecycle_is_required_per_component(self):
        o = read(self.d, "options.json")
        del o[0]["package"]["components"][0]["lifecycle"]
        write(self.d, "options.json", o)
        self.assertTrue(any("lifecycle" in e for e in eval_calc.validate(self.d).errors))

    def test_lifecycle_must_be_a_known_value(self):
        o = read(self.d, "options.json")
        o[0]["package"]["components"][0]["lifecycle"] = "fine"
        write(self.d, "options.json", o)
        self.assertTrue(any("lifecycle must be one of" in e for e in eval_calc.validate(self.d).errors))

    def test_outside_the_matrix_warns_and_text_packages_still_work(self):
        o = read(self.d, "options.json")
        o[0]["package"]["components"][0]["lifecycle"] = "outside_matrix"
        o[1]["package"] = "Beta Queue 2.4.0 community edition"
        write(self.d, "options.json", o)
        rep = eval_calc.validate(self.d)
        self.assertEqual(rep.errors, [])
        self.assertTrue(any("outside the vendor's support matrix" in w for w in rep.warnings))
        self.assertEqual(eval_calc.package_text(o[0]["package"]), "Alpha Queue server 4.2.1, Alpha Queue worker SDK 4.2.0")

    def test_report_has_a_packages_scored_table(self):
        import report_draft
        report_draft.draft(self.d, {})
        t = open(os.path.join(self.d, "report.md"), encoding="utf-8").read()
        self.assertIn("## Packages scored", t)
        self.assertIn("Alpha Queue worker SDK", t)


class Reconcile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(SAMPLE, self.d)
        eval_calc.compute(self.d)
        self.other = os.path.join(self.tmp, "other.csv")
        self.map = os.path.join(self.tmp, "map.csv")
        open(self.other, "w").write("Criterion,Weight,Alpha Queue,Beta Queue\nFeatures,60,4,3\nRunning it,40,2,4\n")
        open(self.map, "w").write("Criterion,Requirements\nFeatures,F-01;F-02\nRunning it,N-01;N-02;N-03\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_both_totals_and_per_criterion_differences(self):
        rep, out = eval_calc.reconcile(self.d, self.other, self.map)
        self.assertEqual(rep.errors, [])
        a = out["options"]["opt-a"]
        self.assertEqual(a["their_total"], round((60 * 4 + 40 * 2) / 100 / 5 * 100, 1))
        self.assertEqual(a["our_total"], read(self.d, "scores.json")["totals"]["opt-a"])
        self.assertEqual(len(out["criteria"]), 2)
        c = out["criteria"][0]["options"]["opt-a"]
        self.assertAlmostEqual(c["difference"], c["ours"] - c["theirs"], places=2)

    def test_hand_checked_rating_under_their_weights(self):
        rep, out = eval_calc.reconcile(self.d, self.other, self.map)
        s = read(self.d, "scores.json")["requirement_scores"]["opt-a"]
        want = (5 * s["F-01"]["score"] + 3 * s["F-02"]["score"]) / 8
        self.assertAlmostEqual(out["criteria"][0]["options"]["opt-a"]["ours"], round(want, 2), places=2)

    def test_unmapped_criteria_warn_and_unknown_ids_fail(self):
        open(self.map, "w").write("Criterion,Requirements\nFeatures,F-01;F-02\n")
        rep, out = eval_calc.reconcile(self.d, self.other, self.map)
        self.assertTrue(any("without a mapping" in w for w in rep.warnings))
        open(self.map, "w").write("Criterion,Requirements\nFeatures,Z-9\nRunning it,N-01\n")
        rep, out = eval_calc.reconcile(self.d, self.other, self.map)
        self.assertIsNone(out)
