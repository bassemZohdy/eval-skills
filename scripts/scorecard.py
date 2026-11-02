#!/usr/bin/env python3
"""Score the eval skills: how well do they catch a flawed evaluation, and are their instructions consistent?

Three parts, each scored 0 to 100, combined into one weighted total:

1. Defect detection (weight 50). Every case copies a complete sample evaluation, injects one
   known defect that the workspace contract or a skill's quality rules forbid, and runs the
   tooling a skill would run (validate, score, validate again, report check). A defect counts
   as caught when a step fails that passed on the clean copy, or a new error or warning
   appears that matches what the case expects. The clean copies must pass untouched.
2. Instruction lint (weight 30). Static checks on every eval skill's SKILL.md and the shared
   contract: frontmatter, step numbering, script commands that exist, files that exist,
   numbers that agree across skills and the scoring reference, no duplicated contract keys.
3. Test suite (weight 20). The repository's unit tests (pass rate).

    python scripts/scorecard.py [--skip-tests] [--json OUT.json] [--md OUT.md] [-v]

Python 3, standard library only. Exits 1 when the total is below --min (default 98).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CALC = os.path.join(ROOT, "shared", "eval_calc.py")
DRAFT = os.path.join(ROOT, "shared", "report_draft.py")
EXAMPLES = {"tq": os.path.join(ROOT, "examples", "task-queue", "eval"),
            "gw": os.path.join(ROOT, "examples", "gateway-like", "eval")}
STEP_SKILLS = ["eval-define", "eval-analyze", "eval-discover", "eval-compare", "eval-report", "eval-orchestrator"]
WEIGHTS = {"detection": 50, "lint": 30, "tests": 20}


# ---- helpers used by the cases ---------------------------------------------------------

def load(d, name):
    with open(os.path.join(d, name), encoding="utf-8") as f:
        return json.load(f)


def save(d, name, data):
    with open(os.path.join(d, name), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def edit(d, name, fn):
    data = load(d, name)
    fn(data)
    save(d, name, data)


def text_edit(d, name, fn):
    p = os.path.join(d, name)
    with open(p, encoding="utf-8") as f:
        s = f.read()
    s2 = fn(s)
    assert s2 != s, "text edit changed nothing in %s" % name
    with open(p, "w", encoding="utf-8") as f:
        f.write(s2)


def req(d, rid):
    return next(r for r in load(d, "requirements.json") if r["id"] == rid)


def set_req(d, rid, **kw):
    def fn(reqs):
        for r in reqs:
            if r["id"] == rid:
                r.update(kw)
    edit(d, "requirements.json", fn)


def set_ev(d, eid, **kw):
    def fn(ev):
        for e in ev:
            if e["evidence_id"] == eid:
                for k, v in kw.items():
                    if v is None:
                        e.pop(k, None)
                    else:
                        e[k] = v
    edit(d, "evidence.json", fn)


def set_score(d, oid, rid, **kw):
    def fn(s):
        s["requirement_scores"][oid][rid].update(kw)
    edit(d, "scores.json", fn)


def set_option(d, oid, **kw):
    def fn(opts):
        for o in opts:
            if o["option_id"] == oid:
                o.update(kw)
    edit(d, "options.json", fn)


def gate(d, gid):
    return next(g for g in load(d, "criteria.json")["gates"] if g["id"] == gid)


def set_verdict(d, gid, oid, fn):
    def outer(c):
        for g in c["gates"]:
            if g["id"] == gid:
                fn(g["verdicts"][oid])
    edit(d, "criteria.json", outer)


def add_ev(d, **row):
    ev = load(d, "evidence.json")
    base = {"evidence_id": "E-%03d" % (len(ev) + 900), "option_id": "opt-a", "requirement_id": "F-02",
            "finding": "Added by the scorecard", "source_url": "https://x.example.org/doc", "source_date": "2026-09-01",
            "gathered_on": "2026-10-01", "confidence": "PROBABLE", "source_kind": "independent",
            "pin": "snapshot 2026-10-01", "source_class": "secondary"}
    base.update(row)
    ev.append(base)
    save(d, "evidence.json", ev)
    return base["evidence_id"]


def cite(d, oid, rid, eid):
    def fn(s):
        s["requirement_scores"][oid][rid]["evidence_ids"].append(eid)
    edit(d, "scores.json", fn)


# ---- cases ---------------------------------------------------------------------------------
# (id, example, rule it enforces, mutate(d), regex the new message must match)

def _weights_off(d):
    edit(d, "criteria.json", lambda c: c["criteria"][0].update(weight=c["criteria"][0]["weight"] + 7))


def _weights_fraction(d):
    def fn(c):
        c["criteria"][0]["weight"] -= 0.5
        c["criteria"][1]["weight"] += 0.5
    edit(d, "criteria.json", fn)


def _dup_evidence(d):
    def fn(ev):
        ev[1]["evidence_id"] = ev[0]["evidence_id"]
    edit(d, "evidence.json", fn)


def _single_req_category(d):
    def fn(c):
        c["criteria"][0]["requirement_ids"] = c["criteria"][0]["requirement_ids"][:1]
        c["criteria"][1]["requirement_ids"] += ["F-02"]
    edit(d, "criteria.json", fn)


def _req_in_two_criteria(d):
    edit(d, "criteria.json", lambda c: c["criteria"][1]["requirement_ids"].append(c["criteria"][0]["requirement_ids"][0]))


def _option_named_in_requirement(d):
    name = load(d, "options.json")[0]["name"]
    set_req(d, "F-02", text="Delayed jobs as in %s" % name)


def _option_named_in_criterion(d):
    name = load(d, "options.json")[1]["name"]
    edit(d, "criteria.json", lambda c: c["criteria"][0].update(name="Core capabilities like %s" % name))


def _vague_requirement(d):
    set_req(d, "N-01", text="The system must be fast and scalable")


def _gate_scope_missing(d):
    def fn(reqs):
        for r in reqs:
            if r["id"] == "F-01":
                r.pop("gate_scope", None)
    edit(d, "requirements.json", fn)


def _no_cost_requirement(d):
    def fn(reqs):
        for r in reqs:
            if "cost" in r["category"].lower():
                r["category"] = "Commercial"
    edit(d, "requirements.json", fn)
    edit(d, "criteria.json", lambda c: [cr.update(category="Commercial") for cr in c["criteria"] if "cost" in cr["category"].lower()])


def _separate_cost_weighted(d):
    edit(d, "criteria.json", lambda c: c.update(cost_mode="separate"))


def _pass_with_unmet_clause(d):
    set_verdict(d, "G-1", "opt-a", lambda v: v["clauses"][0].update(met=False))


def _pass_unchecked_clause(d):
    set_verdict(d, "G-1", "opt-a", lambda v: v["clauses"][1].update(met=None))


def _gate_status_mismatch(d):
    def fn(opts):
        for o in opts:
            if o["option_id"] == "opt-a":
                o["gate_status"]["F-01"] = "fail"
    edit(d, "options.json", fn)


def _documented_pass_no_confirm(d):
    set_verdict(d, "G-1", "opt-b", lambda v: v.pop("confirm_by", None))


def _confirm_by_unknown_test(d):
    set_verdict(d, "G-1", "opt-b", lambda v: v.update(confirm_by="POC test P9: kill a worker mid-job"))


def _pass_without_evidence(d):
    def fn(v):
        for c in v["clauses"]:
            c["evidence_ids"] = []
    set_verdict(d, "G-1", "opt-a", fn)


def _unverified_gate_ranked(d):
    def fn(opts):
        for o in opts:
            if o["option_id"] == "opt-b":
                o["gate_status"]["F-01"] = "unverified"
    edit(d, "options.json", fn)

    def v(x):
        x["verdict"] = "UNVERIFIED"
        x.pop("basis", None)
        x["clauses"][0]["met"] = None
    set_verdict(d, "G-1", "opt-b", v)


def _excluded_no_reason(d):
    set_option(d, "opt-c", exclusion_reason="")


def _bad_label(d):
    set_ev(d, "E-002", confidence="LIKELY")


def _bad_kind(d):
    set_ev(d, "E-002", source_kind="blog")


def _evidence_unknown_option(d):
    set_ev(d, "E-002", option_id="opt-z")


def _evidence_future_date(d):
    set_ev(d, "E-002", gathered_on="2031-01-01")


def _evidence_bad_date(d):
    set_ev(d, "E-002", source_date="last spring")


def _evidence_gathered_before_source(d):
    set_ev(d, "E-002", source_date="2026-10-20", gathered_on="2026-10-01")


def _evidence_uncited(d):
    add_ev(d, requirement_id="F-02")


def _source_code_no_lines(d):
    eid = add_ev(d, source_kind="source_code", source_url="src/queue.py@abc123", confidence="PROBABLE")
    cite(d, "opt-a", "F-02", eid)


def _source_code_confirmed(d):
    eid = add_ev(d, source_kind="source_code", source_url="src/queue.py@abc123", lines="10-20", confidence="CONFIRMED")
    cite(d, "opt-a", "F-02", eid)


def _evidence_empty_url(d):
    set_ev(d, "E-002", source_url="")


def _evidence_empty_finding(d):
    set_ev(d, "E-002", finding="  ")


def _score_unknown_evidence(d):
    set_score(d, "opt-a", "F-02", evidence_ids=["E-999"])


def _score_out_of_range(d):
    set_score(d, "opt-a", "F-02", score=7)


def _score_without_evidence(d):
    set_score(d, "opt-a", "F-02", score=5, evidence_ids=[], confidence="high")


def _score_wrong_option_evidence(d):
    ev = load(d, "evidence.json")
    other = next(e["evidence_id"] for e in ev if e["option_id"] == "opt-b")
    set_score(d, "opt-a", "F-02", evidence_ids=[other])


def _score_wrong_requirement_evidence(d):
    ev = load(d, "evidence.json")
    other = next(e["evidence_id"] for e in ev if e["option_id"] == "opt-a" and e.get("requirement_id") == "C-01")
    set_score(d, "opt-a", "F-02", evidence_ids=[other])


def _score_out_of_scope(d):
    set_ev(d, "E-002", scope="out_of_scope")


def _score_disputed_high(d):
    set_ev(d, "E-002", confidence="DISPUTED")
    set_score(d, "opt-a", "F-02", score=5, confidence="high")


def _score_unverified_high(d):
    set_ev(d, "E-002", confidence="UNVERIFIED")
    set_score(d, "opt-a", "F-02", score=5, confidence="high")


def _score_vendor_only_measure(d):
    # a vendor statement about a quality or performance requirement is never enough for a full score
    ev = load(d, "evidence.json")
    rid = "N-01"
    for e in ev:
        if e["option_id"] == "opt-a" and e.get("requirement_id") == rid:
            e["source_kind"] = "vendor"
            e["confidence"] = "PRIMARY"
    save(d, "evidence.json", ev)
    set_req(d, rid, evidence_class="measure")
    set_score(d, "opt-a", rid, score=5, confidence="high")


def _score_inherited_high(d):
    ev = load(d, "evidence.json")
    ids = [e["evidence_id"] for e in ev if e["option_id"] == "opt-b" and e.get("requirement_id") == "F-02"]
    for e in ev:
        if e["evidence_id"] in ids:
            e["inherited_from_oss"] = True
    save(d, "evidence.json", ev)
    set_score(d, "opt-b", "F-02", confidence="high")


def _rationale_long(d):
    set_score(d, "opt-a", "F-02", rationale=" ".join(["word"] * 55))


def _rationale_empty(d):
    set_score(d, "opt-a", "F-02", rationale="")


def _score_missing(d):
    edit(d, "scores.json", lambda s: s["requirement_scores"]["opt-a"].pop("F-02"))


def _score_excluded_option(d):
    def fn(s):
        s["requirement_scores"]["opt-c"] = json.loads(json.dumps(s["requirement_scores"]["opt-a"]))
    edit(d, "scores.json", fn)


def _override_no_reason(d):
    edit(d, "scores.json", lambda s: s["overrides"].append({"option_id": "opt-a", "requirement_id": "F-02", "score": 5, "reason": ""}))


def _bad_confidence(d):
    set_score(d, "opt-a", "F-02", confidence="certain")


def _cost_no_evidence(d):
    def fn(c):
        comp = c["options"]["opt-a"]["components"][0]
        comp.pop("evidence_id", None)
        comp.pop("price_unknown", None)
        comp.pop("assumed", None)
    edit(d, "cost.json", fn)


def _cost_unknown_evidence(d):
    edit(d, "cost.json", lambda c: c["options"]["opt-a"]["components"][0].update(evidence_id="E-999"))


def _cost_missing_option(d):
    edit(d, "cost.json", lambda c: c["options"].pop("opt-b"))


def _cost_negative_price(d):
    def fn(c):
        comp = c["options"]["opt-a"]["components"][0]
        if "tiers" in comp:
            comp["tiers"][-1]["unit_price"] = -1
        else:
            comp["amount"] = -10
    edit(d, "cost.json", fn)


def _open_item_poc_no_test(d):
    edit(d, "open_items.json", lambda items: items[0].pop("test_id"))


def _open_item_bad_owner(d):
    edit(d, "open_items.json", lambda items: items[0].update(owner_type="someone"))


def _status_stale_compare(d):
    edit(d, "status.json", lambda s: s.update(stale_steps=["compare", "report"]))


def _status_late_weights(d):
    edit(d, "status.json", lambda s: s.update(post_scoring_weight_change=True, weight_change_reason=""))


def _status_completed_out_of_order(d):
    edit(d, "status.json", lambda s: s.update(completed_steps=["define", "analyze", "compare", "report"]))


def _features_unknown_option(d):
    def fn(fs):
        fs[0]["cells"]["opt-z"] = {"status": "included", "note": "", "evidence_ids": []}
    edit(d, "features.json", fn)


def _features_bad_status(d):
    def fn(fs):
        c = next(iter(fs[0]["cells"].values()))
        c["status"] = "maybe"
    edit(d, "features.json", fn)


def _candidate_scored(d):
    cand = load(d, "candidate_requirements.json")
    cid = cand[0]["id"]

    def fn(s):
        s["requirement_scores"]["opt-a"][cid] = {"score": 4, "confidence": "medium", "rationale": "found in research", "evidence_ids": []}
    edit(d, "scores.json", fn)


def _package_bad_lifecycle(d):
    def fn(opts):
        opts[0]["package"]["components"][0]["lifecycle"] = "beta"
    edit(d, "options.json", fn)


def _oss_partial(d):
    set_option(d, "opt-a", oss_base={"project": "x"})


# report cases: they edit eval/report.md after a clean score run
def _report_leader(d):
    text_edit(d, "report.md", lambda s: s.replace("Alpha Queue leads Beta Queue", "Beta Queue leads Alpha Queue", 1))


def _report_percent(d):
    text_edit(d, "report.md", lambda s: s.replace("**Confidence: medium.**", "**Confidence: 80%.**", 1))


def _report_high_on_near_tie(d):
    text_edit(d, "report.md", lambda s: s.replace("**Confidence: medium.**", "**Confidence: high.**", 1))


def _report_score_changed(d):
    text_edit(d, "report.md", lambda s: s.replace("| 1 | Alpha Queue | 71.6 |", "| 1 | Alpha Queue | 74.6 |", 1))


def _report_excluded_missing(d):
    def fn(s):
        return re.sub(r"## Excluded options\n.*?(?=\n## )", "## Excluded options\n\nNone.\n", s, count=1, flags=re.S).replace("- Gamma Queue: F-01 not met", "- F-01 not met")
    text_edit(d, "report.md", fn)


def _report_banned_wording(d):
    text_edit(d, "report.md", lambda s: s.replace("so the choice is not clear-cut", "so this round the choice is not clear-cut", 1))


def _report_missing_section(d):
    text_edit(d, "report.md", lambda s: re.sub(r"## Sensitivity\n.*?(?=\n## )", "", s, count=1, flags=re.S))


def _report_todo(d):
    text_edit(d, "report.md", lambda s: s.replace("**Confidence: medium.**", "**Confidence: medium.** TODO(prose): confidence_why", 1))


def _report_no_provenance(d):
    text_edit(d, "report.md", lambda s: s.replace("Evaluation date 2026-10-01. Scale 0 to 5. Cost mode: weighted.", "", 1))


def _report_decisive_near_tie(d):
    text_edit(d, "report.md", lambda s: s.replace("so the choice is not clear-cut and should be treated as a near-tie", "a decisive win", 1))


def _report_unknown_fact(d):
    # a percentage of the total weight or a total not in scores.json
    text_edit(d, "report.md", lambda s: s.replace("Alpha Queue leads Beta Queue by about one point", "Alpha Queue leads Beta Queue by 9.4 points", 1))


CASES = [
    # criteria and weights (eval-analyze)
    ("weights-sum", "tq", "criteria weights sum to 100", _weights_off, r"sum"),
    ("weights-whole", "tq", "category weights are whole numbers", _weights_fraction, r"whole"),
    ("category-one-req", "tq", "a scored category holds at least two requirements", _single_req_category, r"at least two"),
    ("req-two-criteria", "tq", "each requirement is in exactly one criterion", _req_in_two_criteria, r"exactly 1|covered"),
    ("criterion-names-option", "tq", "no criterion may mention a specific option", _option_named_in_criterion, r"names the option|mention"),
    ("separate-cost-weighted", "tq", "cost_mode separate means the cost criterion has weight 0", _separate_cost_weighted, r"weight 0"),
    # requirements (eval-define)
    ("req-names-option", "tq", "requirements never name a candidate option", _option_named_in_requirement, r"names the option|mention"),
    ("req-vague", "tq", "no vague words without a measurable threshold", _vague_requirement, r"vague|measurable|threshold"),
    ("gate-scope", "tq", "gate requirements state gate_scope", _gate_scope_missing, r"gate_scope"),
    ("no-cost-req", "tq", "every evaluation has a cost requirement", _no_cost_requirement, r"cost"),
    # gates (eval-discover)
    ("pass-unmet", "tq", "a PASS needs every clause met", _pass_with_unmet_clause, r"PASS"),
    ("pass-unchecked", "tq", "an unchecked clause makes the verdict UNVERIFIED", _pass_unchecked_clause, r"PASS|UNVERIFIED"),
    ("gate-status-mismatch", "tq", "verdicts agree with gate_status", _gate_status_mismatch, r"gate_status"),
    ("documented-no-confirm", "tq", "a documented PASS names confirm_by", _documented_pass_no_confirm, r"confirm_by"),
    ("confirm-unknown-test", "tq", "confirm_by names a POC test that exists in open_items.json", _confirm_by_unknown_test, r"P9|test"),
    ("pass-no-evidence", "tq", "a PASS clause cites evidence", _pass_without_evidence, r"evidence"),
    ("unverified-ranked", "tq", "an unverified, unwaived gate blocks ranking", _unverified_gate_ranked, r"unverified|waive"),
    ("excluded-no-reason", "tq", "excluded options need a reason", _excluded_no_reason, r"exclusion_reason"),
    # evidence (eval-discover)
    ("bad-label", "tq", "evidence uses the six labels", _bad_label, r"confidence"),
    ("bad-kind", "tq", "source_kind is one of the allowed kinds", _bad_kind, r"source_kind"),
    ("evidence-option", "tq", "evidence rows name a known option", _evidence_unknown_option, r"option"),
    ("evidence-future", "tq", "gathered_on is not in the future", _evidence_future_date, r"future|gathered_on"),
    ("evidence-date-format", "tq", "dates are YYYY-MM-DD or unknown", _evidence_bad_date, r"date"),
    ("evidence-date-order", "tq", "a source cannot be dated after it was gathered", _evidence_gathered_before_source, r"date|gathered"),
    ("evidence-uncited", "tq", "in a finished evaluation every evidence row is cited", _evidence_uncited, r"cited"),
    ("evidence-dup", "tq", "evidence ids are unique", _dup_evidence, r"duplicate"),
    ("evidence-no-url", "tq", "every finding has a source_url", _evidence_empty_url, r"source_url|url"),
    ("evidence-no-finding", "tq", "every evidence row states its finding", _evidence_empty_finding, r"finding"),
    ("source-code-lines", "tq", "source_code findings cite a line range", _source_code_no_lines, r"lines|line range"),
    ("source-code-confirmed", "tq", "source_code findings are PROBABLE at best unless tested", _source_code_confirmed, r"PROBABLE"),
    # scores (eval-compare)
    ("score-unknown-evidence", "tq", "scores cite existing evidence", _score_unknown_evidence, r"E-999"),
    ("score-range", "tq", "requirement scores are 0 to 5", _score_out_of_range, r"0 to 5"),
    ("score-no-evidence", "tq", "a score above the weak-evidence cap needs evidence", _score_without_evidence, r"evidence|cap|confidence"),
    ("score-other-option-evidence", "tq", "a score cites evidence about the same option", _score_wrong_option_evidence, r"option|opt-"),
    ("score-other-req-evidence", "tq", "a score cites evidence about the same requirement", _score_wrong_requirement_evidence, r"requirement|C-01"),
    ("score-out-of-scope", "tq", "out-of-scope evidence never earns credit", _score_out_of_scope, r"scope"),
    ("score-disputed-high", "tq", "DISPUTED evidence cannot carry a full, high-confidence score", _score_disputed_high, r"DISPUTED|weak|cap|confidence"),
    ("score-unverified-high", "tq", "UNVERIFIED evidence caps the score at 2", _score_unverified_high, r"cap|weak|UNVERIFIED|confidence"),
    ("score-vendor-measure", "tq", "vendor documentation never confirms performance or quality", _score_vendor_only_measure, r"vendor|confidence|cap|independent"),
    ("score-inherited-high", "tq", "a score on inherited evidence only cannot be high confidence", _score_inherited_high, r"inherit|confidence"),
    ("rationale-long", "tq", "rationales are at most 40 words", _rationale_long, r"40|words"),
    ("rationale-empty", "tq", "every score has a rationale", _rationale_empty, r"rationale"),
    ("score-missing", "tq", "every included option and requirement is scored", _score_missing, r"missing|no score|not scored|F-02"),
    ("score-excluded", "tq", "excluded options are not scored or ranked", _score_excluded_option, r"excluded|opt-c"),
    ("override-no-reason", "tq", "an override records its reason", _override_no_reason, r"reason"),
    ("bad-confidence", "tq", "score confidence is high, medium or low", _bad_confidence, r"confidence"),
    ("candidate-scored", "tq", "candidate requirements are never scored", _candidate_scored, r"candidate|unknown requirement"),
    # cost
    ("cost-no-evidence", "tq", "a priced component cites evidence, or is price_unknown or assumed", _cost_no_evidence, r"evidence"),
    ("cost-unknown-evidence", "tq", "cost evidence ids exist", _cost_unknown_evidence, r"E-999"),
    ("cost-missing-option", "tq", "every profiled option has a priced model", _cost_missing_option, r"cost|priced|opt-b"),
    ("cost-negative", "tq", "prices are not negative", _cost_negative_price, r"negative|price"),
    # open items, status, features, package
    ("poc-no-test-id", "tq", "a poc_test open item has a test_id", _open_item_poc_no_test, r"test_id"),
    ("open-item-owner", "tq", "open items have a valid owner_type", _open_item_bad_owner, r"owner_type"),
    ("status-stale", "tq", "a stale step blocks the report", _status_stale_compare, r"stale"),
    ("status-late-weights", "tq", "a late weight change records its reason", _status_late_weights, r"reason"),
    ("status-order", "tq", "steps complete in order", _status_completed_out_of_order, r"discover|order"),
    ("features-option", "tq", "feature cells name known options", _features_unknown_option, r"opt-z|option"),
    ("features-status", "tq", "feature cells are included, partial or missing", _features_bad_status, r"status"),
    ("package-lifecycle", "tq", "package lifecycle is supported, lts or outside_matrix", _package_bad_lifecycle, r"lifecycle"),
    ("oss-partial", "tq", "oss_base is null or complete", _oss_partial, r"oss_base"),
    # report (eval-report)
    ("report-leader", "tq", "the report names the scorer's leader", _report_leader, r"lead|ranked first"),
    ("report-percent", "tq", "confidence is high, medium or low, never a percentage", _report_percent, r"percent|%|confidence"),
    ("report-high-near-tie", "tq", "high confidence needs a lead of at least meaningful_gap", _report_high_on_near_tie, r"high|meaningful|gap"),
    ("report-score", "tq", "scores in the report match scores.json", _report_score_changed, r"74.6|score|total"),
    ("report-excluded", "tq", "every excluded option is named with its gate", _report_excluded_missing, r"excluded|Gamma"),
    ("report-wording", "tq", "no method-history wording in the report", _report_banned_wording, r"this round|wording"),
    ("report-section", "tq", "every required section is present", _report_missing_section, r"Sensitivity|section"),
    ("report-todo", "tq", "no unfinished prose", _report_todo, r"TODO"),
    ("report-provenance", "tq", "the report opens with the provenance line", _report_no_provenance, r"provenance|Evaluation date|first line"),
    ("report-decisive", "tq", "a near-tie is never presented as decisive", _report_decisive_near_tie, r"near-tie|decisive|clear-cut|tie"),
    ("report-lead-number", "tq", "numbers in the recommendation match the computed lead", _report_unknown_fact, r"lead|9.4|points"),
    # the larger, gated example
    ("gw-weights-sum", "gw", "criteria weights sum to 100 (gateway-like)", _weights_off, r"sum"),
    ("gw-dup-evidence", "gw", "evidence ids are unique (gateway-like)", _dup_evidence, r"duplicate"),
    ("gw-req-two-criteria", "gw", "each requirement is in exactly one criterion (gateway-like)", _req_in_two_criteria, r"exactly 1|covered"),
]


# ---- round 2: harder cases ----------------------------------------------------------------

def _failed_gate_not_excluded(d):
    set_option(d, "opt-c", excluded=False, exclusion_reason="")


def _weights_changed_silently(d):
    # weights edited after scoring without `changed eval weights`: scores.json and the report are stale
    def fn(c):
        c["criteria"][0]["weight"] -= 20
        c["criteria"][1]["weight"] += 20
    edit(d, "criteria.json", fn)


def _score_edited_not_rescored(d):
    # a score changed by hand in a finished evaluation, not rescored: the computed totals no longer follow
    set_score(d, "opt-b", "F-02", score=0)


def _retired_still_scored(d):
    set_req(d, "N-02", retired=True)


def _anchor_missing(d):
    edit(d, "criteria.json", lambda c: c["criteria"][0]["anchors"].pop("5"))


def _gate_without_rubric(d):
    edit(d, "criteria.json", lambda c: c.update(gates=[g for g in c["gates"] if g["requirement_id"] != "N-03"]))


def _gate_verdict_missing(d):
    set_verdict(d, "G-1", "opt-b", lambda v: None)

    def fn(c):
        for g in c["gates"]:
            if g["id"] == "G-1":
                g["verdicts"].pop("opt-b")
    edit(d, "criteria.json", fn)


def _gate_status_missing(d):
    def fn(opts):
        for o in opts:
            if o["option_id"] == "opt-a":
                o["gate_status"].pop("N-03")
    edit(d, "options.json", fn)


def _inherited_without_base(d):
    set_ev(d, "E-002", inherited_from_oss=True)


def _confirmed_single_vendor(d):
    set_ev(d, "E-004", confidence="CONFIRMED", source_kind="vendor")


def _primary_independent(d):
    set_ev(d, "E-002", confidence="PRIMARY", source_kind="independent")


def _zero_without_evidence(d):
    set_score(d, "opt-a", "F-02", score=0, evidence_ids=[], confidence="high", rationale="Not provided.")


def _duplicate_option_name(d):
    set_option(d, "opt-b", name="Alpha Queue")


def _status_dates(d):
    edit(d, "status.json", lambda s: s.update(report_date="2026-09-01"))


def _feature_other_option_evidence(d):
    ev = load(d, "evidence.json")
    other = next(e["evidence_id"] for e in ev if e["option_id"] == "opt-b")

    def fn(fs):
        fs[0]["cells"]["opt-a"]["evidence_ids"] = [other]
    edit(d, "features.json", fn)


def _report_recommends_excluded(d):
    text_edit(d, "report.md", lambda s: s.replace("Alpha's edge is operability", "We recommend Gamma Queue. Alpha's edge is operability", 1))


def _report_table_lists_excluded(d):
    text_edit(d, "report.md", lambda s: s.replace("\n\nNear-tie (within", "\n| 3 | Gamma Queue | 40.0 | F-01 fail |  |  |  |\n\nNear-tie (within", 1))


def _report_high_could_overtake(d):
    def fn(s):
        s["could_overtake_leader"] = ["opt-b"]
        s["lead"] = 9.0
    edit(d, "scores.json", fn)
    text_edit(d, "report.md", lambda s: s.replace("**Confidence: medium.**", "**Confidence: high.** Unknowns could let Beta overtake.", 1))


def _report_not_assessed(d):
    edit(d, "criteria.json", lambda c: c["not_assessed"].append("Roadmap commitments"))


def _report_eligibility_wrong(d):
    text_edit(d, "report.md", lambda s: s.replace("**Eligibility: 2 of 3 options pass every gate.**", "**Eligibility: 3 of 3 options pass every gate.**", 1))


CASES += [
    ("failed-gate-ranked", "tq", "an option that fails a gate is excluded, never ranked", _failed_gate_not_excluded, r"exclud|gate|fail"),
    ("weights-silent-change", "tq", "a weight change after scoring marks compare stale (scores.json is out of date)", _weights_changed_silently, r"out of date|stale|rescore|rerun|differ", "report"),
    ("score-not-rescored", "tq", "computed totals follow the requirement scores", _score_edited_not_rescored, r"out of date|stale|rescore|rerun|differ", "report"),
    ("retired-scored", "tq", "a retired requirement is removed from its criterion", _retired_still_scored, r"retired"),
    ("anchor-missing", "tq", "criterion anchors give 0, 3 and 5", _anchor_missing, r"anchors"),
    ("gate-no-rubric", "tq", "every gate requirement has a rubric in criteria.json gates", _gate_without_rubric, r"rubric|N-03"),
    ("gate-verdict-missing", "tq", "every profiled option is judged against every gate", _gate_verdict_missing, r"verdict|judged|opt-b"),
    ("gate-status-missing", "tq", "every profiled option has a gate_status for every gate", _gate_status_missing, r"gate_status|N-03"),
    ("inherited-no-base", "tq", "inherited_from_oss needs an option with an oss_base", _inherited_without_base, r"oss_base|inherit"),
    ("confirmed-one-vendor", "tq", "CONFIRMED needs two independent sources, never one vendor page", _confirmed_single_vendor, r"CONFIRMED"),
    ("primary-independent", "tq", "PRIMARY is the source itself, not an independent review", _primary_independent, r"PRIMARY"),
    ("zero-no-evidence", "tq", "'not provided' needs a source saying so; an unread page is unknown", _zero_without_evidence, r"unknown|absent|evidence|not provided"),
    ("dup-option-name", "tq", "option names are unique", _duplicate_option_name, r"duplicate|name"),
    ("status-dates", "tq", "the report date is not before the evaluation date", _status_dates, r"report_date|date"),
    ("feature-other-evidence", "tq", "feature cells cite evidence about their option", _feature_other_option_evidence, r"opt-b|option"),
    ("report-recommends-excluded", "tq", "the report never recommends an excluded option", _report_recommends_excluded, r"Gamma|excluded"),
    ("report-table-excluded", "tq", "the decision table ranks only eligible options", _report_table_lists_excluded, r"decision table|Gamma"),
    ("report-high-overtake", "tq", "confidence cannot be high while unknowns could change the leader", _report_high_could_overtake, r"overtake|unknown|high"),
    ("report-not-assessed", "tq", "factors not assessed are named on a 'Not assessed:' line", _report_not_assessed, r"Not assessed"),
    ("report-eligibility", "tq", "the eligibility count matches the gates", _report_eligibility_wrong, r"Eligibility"),
]


# ---- running the tooling ---------------------------------------------------------------------

def run(args):
    p = subprocess.run([sys.executable] + args, capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def messages(out):
    """Error and warning lines from a command's output, plus the scores.json warnings list."""
    lines = set()
    for ln in out.splitlines():
        s = ln.strip().strip('",').strip()
        if s and s not in ("{", "}", "[", "]", "ok"):
            lines.add(s)
    return lines


def pipeline(d, has_report, stage="compare"):
    """What a skill would run on the evaluation.

    compare: validate, score, validate again, report check (eval-compare then eval-report).
    report: validate and report check only, the way eval-report finds the files; nothing is rescored.
    """
    steps = []
    steps.append(("validate",) + run([CALC, "validate", d, "--before", "report"]))
    if stage == "report":
        if has_report:
            steps.append(("report-check",) + run([DRAFT, "check", d]))
        return steps
    rc, out = run([CALC, "score", d])
    warns = []
    try:
        warns = load(d, "scores.json").get("warnings", [])
    except (OSError, ValueError):
        pass
    if rc != 0:
        steps.append(("score", rc, out))
    else:
        steps.append(("score", 0, "\n".join("WARNING: " + w for w in warns)))
    steps.append(("validate-after", ) + run([CALC, "validate", d, "--before", "report"]))
    if has_report:
        steps.append(("report-check",) + run([DRAFT, "check", d]))
    return steps


def fresh_copy(example, tmp):
    src = EXAMPLES[example]
    dst = os.path.join(tmp, example, "eval")
    if os.path.exists(os.path.dirname(dst)):
        shutil.rmtree(os.path.dirname(dst))
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("export"))
    return dst


def detection(verbose=False, only=None):
    results, baseline = [], {}
    tmp = tempfile.mkdtemp()
    try:
        for ex in EXAMPLES:
            d = fresh_copy(ex, tmp)
            has_report = os.path.exists(os.path.join(d, "report.md"))
            steps = pipeline(d, has_report)
            baseline[ex] = {name: (rc, messages(out)) for name, rc, out in steps}
            bad = [(n, out.strip()[:300]) for n, rc, out in steps if rc != 0]
            if bad:
                results.append({"id": "clean-" + ex, "rule": "the clean sample passes every check", "caught": False,
                                "detail": "; ".join("%s: %s" % b for b in bad)})
            else:
                results.append({"id": "clean-" + ex, "rule": "the clean sample passes every check", "caught": True, "detail": "clean"})
        report_base = {}
        for case in CASES:
            cid, ex, rule, mutate, pattern = case[:5]
            stage = case[5] if len(case) > 5 else "compare"
            if only and cid not in only:
                continue
            d = fresh_copy(ex, tmp)
            has_report = os.path.exists(os.path.join(d, "report.md"))
            try:
                mutate(d)
            except Exception as e:  # a broken case is a harness bug, report it as not caught
                results.append({"id": cid, "rule": rule, "caught": False, "detail": "case failed to apply: %r" % e})
                continue
            steps = pipeline(d, has_report, stage)
            new = []
            for name, rc, out in steps:
                brc, bmsgs = baseline[ex].get(name, (0, set()))
                fresh = [m for m in messages(out) if m not in bmsgs]
                if rc != 0 and brc == 0:
                    new += ["%s failed: %s" % (name, m) for m in fresh] or ["%s failed" % name]
                else:
                    new += ["%s: %s" % (name, m) for m in fresh if re.search(r"warn|error|problem|must|need|cannot|not |no |unknown|invalid|missing|stale|cap", m, re.I)]
            hits = [m for m in new if re.search(pattern, m, re.I)]
            results.append({"id": cid, "rule": rule, "caught": bool(hits),
                            "detail": (hits or new or ["nothing reported"])[0][:240]})
            if verbose:
                print("%-28s %s  %s" % (cid, "CAUGHT" if hits else "MISSED", results[-1]["detail"][:150]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    caught = sum(r["caught"] for r in results)
    return {"score": round(100.0 * caught / len(results), 1), "caught": caught, "total": len(results), "cases": results}


# ---- instruction lint --------------------------------------------------------------------------

def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def _subcommands(script):
    if not os.path.exists(script):
        return set()
    m = re.search(r"\{([a-z,\-]+)\}", run([script, "--help"])[1])
    return set(m.group(1).split(",")) if m else set()


def lint():
    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    contract = _read(os.path.join(ROOT, "shared", "workspace-contract.md"))
    scoring = _read(os.path.join(ROOT, "skills", "eval-compare", "references", "scoring.md"))
    calc_cmds = _subcommands(CALC)
    draft_cmds = _subcommands(DRAFT)
    all_text = {}
    for sk in STEP_SKILLS:
        path = os.path.join(ROOT, "skills", sk, "SKILL.md")
        text = _read(path)
        all_text[sk] = text
        fm = re.match(r"---\nname: (.+)\ndescription: (.+)\n---\n", text)
        check("%s: frontmatter has name and description" % sk, fm and fm.group(1).strip() == sk)
        desc = fm.group(2) if fm else ""
        check("%s: description under 1024 characters" % sk, 0 < len(desc) <= 1024, "%d chars" % len(desc))
        check("%s: description says when to use it" % sk, re.search(r"\bUse (after|when)\b", desc))
        check("%s: description says when not to use it" % sk, re.search(r"\bDo not use\b", desc))
        body = text[fm.end():] if fm else text
        check("%s: body under 500 lines" % sk, body.count("\n") < 500)
        proc = re.search(r"## Process\n(.*?)(\n## |\Z)", body, re.S)
        if proc:
            nums = re.findall(r"^(\d+)([a-z]?)\. ", proc.group(1), re.M)
            seq = [int(n) for n, suffix in nums if not suffix]
            dup = sorted({n for n in seq if seq.count(n) > 1})
            check("%s: process steps are numbered once each" % sk, not dup, "repeated: %s" % dup if dup else "")
            check("%s: process steps run 1..n in order" % sk, seq == list(range(1, len(seq) + 1)), str(seq))
            subs = ["%s%s" % (n, s) for n, s in nums if s]
            orphan = [s for s in subs if int(re.match(r"\d+", s).group()) not in seq]
            check("%s: lettered sub-steps follow an existing step" % sk, not orphan, str(orphan))
        for script, cmd in re.findall(r"python scripts/(\w+\.py) ([a-z][a-z\-]+)", body):
            known = {"eval_calc.py": calc_cmds, "report_draft.py": draft_cmds}.get(script)
            if known is not None:
                check("%s: `%s %s` exists" % (sk, script, cmd), cmd in known)
        for script in set(re.findall(r"scripts/(\w+\.py)", body)):
            check("%s: bundles scripts/%s" % (sk, script), os.path.exists(os.path.join(ROOT, "skills", sk, "scripts", script)))
        for ref in set(re.findall(r"references/([\w\-]+\.md)", body)):
            check("%s: bundles references/%s" % (sk, ref), os.path.exists(os.path.join(ROOT, "skills", sk, "references", ref)))
        for other in re.findall(r"\b(eval-[a-z]+)\b", body):
            if other not in STEP_SKILLS and other != "eval-archive":
                check("%s: names only existing skills (%s)" % (sk, other), False)

    # numbers that must agree everywhere
    compare = all_text["eval-compare"]
    check("near-tie threshold agrees (compare SKILL.md vs meaningful_gap)",
          not re.search(r"within 3 points", compare), "compare says 'within 3 points' while meaningful_gap defaults to 5")
    check("near-tie threshold agrees (scoring.md vs meaningful_gap)",
          not re.search(r"within 3 points", scoring), "scoring.md says 'within 3 points' while meaningful_gap defaults to 5")
    check("compare describes requirement scoring, not per-criterion scoring",
          not re.search(r"Score each option per criterion", compare))
    check("compare's weighted-total formula matches the anchored model",
          not re.search(r"score divided by the scale maximum\) times the criterion weight", compare))
    check("confidence rule agrees with contract rule 13",
          not re.search(r"high with two independent sources, medium with one", compare))
    check("analyze does not ask for criterion-level 0/3/5 scoring under the anchored model",
          not re.search(r"For each criterion, write one sentence describing what a 0, a 3, and a 5 look like", all_text["eval-analyze"]))

    # contract table: no key listed twice for one file
    for line in contract.splitlines():
        m = re.match(r"\| `eval/([\w\.]+\.json)` \|.*Keys: (.*) \|$", line)
        if m:
            # top-level keys: the names before each comma, ignoring anything inside parentheses
            flat, depth = "", 0
            for ch in m.group(2):
                depth += ch == "("
                depth -= ch == ")"
                flat += ch if depth == 0 and ch not in "()" else ""
            top = [k.strip().replace("\\", "").split(" ")[0] for k in flat.split(",")]
            top = [k for k in top if re.fullmatch(r"[a-z_]+", k)]
            dup = sorted({k for k in top if top.count(k) > 1})
            check("contract: %s keys listed once each" % m.group(1), not dup, "repeated: %s" % dup if dup else "")

    # sync: the bundled copies match the shared sources
    rc, out = run([os.path.join(ROOT, "scripts", "sync_shared.py"), "--check"])
    check("bundled scripts and contract match shared/", rc == 0, out.strip()[:200])
    ok = sum(c["ok"] for c in checks)
    return {"score": round(100.0 * ok / len(checks), 1), "passed": ok, "total": len(checks), "checks": checks}


# ---- tests -----------------------------------------------------------------------------------

def tests():
    p = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=ROOT, capture_output=True, text=True)
    out = p.stderr + p.stdout
    m = re.search(r"Ran (\d+) tests?", out)
    ran = int(m.group(1)) if m else 0
    f = re.search(r"failures=(\d+)", out)
    e = re.search(r"errors=(\d+)", out)
    bad = (int(f.group(1)) if f else 0) + (int(e.group(1)) if e else 0)
    s = re.search(r"skipped=(\d+)", out)
    return {"score": round(100.0 * (ran - bad) / ran, 1) if ran else 0.0, "ran": ran, "failed": bad,
            "skipped": int(s.group(1)) if s else 0, "tail": "\n".join(out.strip().splitlines()[-15:]) if bad else ""}


# ---- report ------------------------------------------------------------------------------------

def to_markdown(card):
    lines = ["# Eval skills scorecard", "", "**Total: %.1f / 100** (detection %.1f x%d%%, lint %.1f x%d%%, tests %s x%d%%)" % (
        card["total"], card["detection"]["score"], WEIGHTS["detection"], card["lint"]["score"], WEIGHTS["lint"],
        "%.1f" % card["tests"]["score"] if card["tests"] else "skipped", WEIGHTS["tests"]), ""]
    det = card["detection"]
    lines += ["## Defect detection: %d of %d caught" % (det["caught"], det["total"]), "", "| Case | Rule | Result | Detail |", "| --- | --- | --- | --- |"]
    for c in det["cases"]:
        lines.append("| %s | %s | %s | %s |" % (c["id"], c["rule"], "caught" if c["caught"] else "**missed**", c["detail"].replace("|", "/")[:160]))
    li = card["lint"]
    lines += ["", "## Instruction lint: %d of %d pass" % (li["passed"], li["total"]), ""]
    fails = [c for c in li["checks"] if not c["ok"]]
    lines += ["- **fail** %s %s" % (c["check"], ("(%s)" % c["detail"]) if c["detail"] else "") for c in fails] or ["All checks pass."]
    if card["tests"]:
        t = card["tests"]
        lines += ["", "## Tests: %d run, %d failed, %d skipped" % (t["ran"], t["failed"], t["skipped"])]
        if t["tail"]:
            lines += ["", "```", t["tail"], "```"]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-tests", action="store_true", help="leave out the unit tests (their weight is spread over the other parts)")
    ap.add_argument("--json")
    ap.add_argument("--md")
    ap.add_argument("--min", type=float, default=98.0)
    ap.add_argument("--only", nargs="*", help="run only these detection cases")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    det = detection(a.verbose, a.only)
    li = lint()
    te = None if a.skip_tests else tests()
    w = dict(WEIGHTS)
    if te is None:
        w.pop("tests")
    parts = {"detection": det["score"], "lint": li["score"], "tests": te["score"] if te else 0}
    total = sum(parts[k] * v for k, v in w.items()) / sum(w.values())
    card = {"total": round(total, 1), "detection": det, "lint": li, "tests": te}
    md = to_markdown(card)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(card, f, indent=2)
    if a.md:
        with open(a.md, "w", encoding="utf-8") as f:
            f.write(md)
    print("total %.1f  detection %.1f (%d/%d)  lint %.1f (%d/%d)  tests %s" % (
        card["total"], det["score"], det["caught"], det["total"], li["score"], li["passed"], li["total"],
        ("%.1f (%d run, %d failed)" % (te["score"], te["ran"], te["failed"])) if te else "skipped"))
    for c in det["cases"]:
        if not c["caught"]:
            print("  missed  %-26s %s -- %s" % (c["id"], c["rule"], c["detail"][:120]))
    for c in li["checks"]:
        if not c["ok"]:
            print("  lint    %s %s" % (c["check"], c["detail"]))
    return 0 if card["total"] >= a.min else 1


if __name__ == "__main__":
    sys.exit(main())
