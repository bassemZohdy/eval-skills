#!/usr/bin/env python3
"""Draft and check eval/report.md.

  report_draft.py draft eval [--prose prose.json]   write eval/report.md
  report_draft.py check eval                        check the report against the computed files

`draft` writes every computed section (decision table, criteria, matrix, bias, cost,
must-have summary, sensitivity, excluded, sources) from the evaluation files, so no
number is typed by hand. The judgment text comes from a prose JSON file with these keys:
recommendation, confidence (high, medium or low), confidence_why, profiles (optional; option id to a short text of strengths, blockers and risks), options (option id to
[main strength, main gap]), bias, cost, sensitivity, next_steps (list), risks (list),
excluded. A key left out is written as `TODO(prose): <key>` and `check` fails until it is
replaced; `excluded` is only required when an option was excluded. Python 3, standard library only.
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from export_report import Data, SECTION_ORDER, order_sections, section_rank  # noqa: E402

KEYS = ("recommendation", "confidence", "confidence_why", "bias", "cost", "sensitivity", "next_steps", "risks", "excluded")
HEADINGS = ["Decision recommendation", "Decision table", "Context", "Recommended next steps", "Criteria and weights", "Weighted score matrix", "Bias and assumptions", "Cost",
            "Sensitivity", "Feature", "Risks and open questions", "Sources"]
BANNED = re.compile(r"\b(this round|re-?checked|re-?validated|(previous|last|earlier|next) round|round \d)\b", re.I)
MAX_CAVEATS = 10


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    return out + ["| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in r) + " |" for r in rows]


def _prose(P, key):
    v = P.get(key)
    return v if v else "TODO(prose): %s" % key


def _load(d, name):
    with open(os.path.join(d, name), encoding="utf-8") as f:
        return json.load(f)


def eligibility(d):
    """Which profiled options pass every gate, and what blocks the rest."""
    opts = [o for o in _load(d, "options.json") if not o.get("not_profiled")]
    crit = _load(d, "criteria.json")
    gates = {g["requirement_id"]: g for g in crit.get("gates", [])}
    ok, blockers = [], {}
    for o in opts:
        bad = []
        for gid, st in (o.get("gate_status") or {}).items():
            if st in ("fail", "unverified"):
                v = ((gates.get(gid) or {}).get("verdicts") or {}).get(o["option_id"]) or {}
                notes = [c["note"] for c in v.get("clauses", []) if c.get("met") is not True]
                bad.append("%s %s%s" % (gid, "not met" if st == "fail" else "unverified", ": " + "; ".join(notes) if notes else ""))
        if bad:
            blockers[o["name"]] = bad
        else:
            ok.append(o["name"])
    return {"total": len(opts), "passing": ok, "blockers": blockers}


def _eligibility_md(e):
    if not e["blockers"]:
        return []
    md = ["## Eligibility", "", "**Eligibility: %d of %d options pass every gate.**" % (len(e["passing"]), e["total"]), ""]
    md += ["- %s: %s." % (n, "; ".join(b)) for n, b in e["blockers"].items()]
    return md + [""]


def _draft_shortlist(d, e, P):
    """No option passes every gate, so there is nothing to rank or recommend: shortlist and close the blockers."""
    title = _load(d, "status.json").get("solution_slug", "evaluation")
    md = ["# Evaluation report: " + title, ""] + _eligibility_md(e)
    md += ["## Decision recommendation", "", P.get("recommendation") or "No option passes every gate. Shortlist the options below and close their blockers before choosing.", "",
           "**Confidence: %s.** %s" % (P.get("confidence") or "low", P.get("confidence_why") or "No ranking is given because no option is eligible."), "",
           "## Recommended next steps", ""]
    md += ["%d. %s" % (i, x) for i, x in enumerate(P.get("next_steps") or ["TODO(prose): next_steps"], 1)]
    path = os.path.join(d, "report.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md) + "\n")
    return path


def draft(d, prose=None):
    e = eligibility(d)
    if e["total"] and not e["passing"]:
        return _draft_shortlist(d, e, prose or {})
    D = Data(d)
    P = prose or {}
    sc, cs, tot, rank = D.scores, D.scores["criterion_scores"], D.scores["totals"], D.ranking
    short = lambda o: D.name[o].split(" (")[0]
    cr = [c for c in D.criteria if c["weight"] > 0]
    gates = {o["option_id"]: o for o in D.opts}
    reruns = P.get("provenance", "")
    if D.status.get("post_scoring_weight_change"):
        reruns = (reruns + " Weights were changed after scoring: %s." % D.status.get("weight_change_reason", "").rstrip(".")).strip()
    basis = {(oid, g["requirement_id"]): v["basis"] for g in D.crit.get("gates", []) for oid, v in g["verdicts"].items() if v.get("basis")}
    md = ["# Evaluation report: " + D.title, "",
          ("Evaluation date %s. Scale 0 to %s. Cost mode: %s%s. %s" % (
              D.status.get("evaluation_date", "n/a"), D.mx, D.crit["cost_mode"], " (cost is shown beside the score, not in it)" if D.crit["cost_mode"] == "separate" else "", reruns)).strip(), "",
          *_eligibility_md(e), "## Decision recommendation", "", _prose(P, "recommendation"), "",
          "**Confidence: %s.** %s" % (P.get("confidence") or "TODO(prose): confidence", _prose(P, "confidence_why")), "", "## Decision table", ""]
    rows = []
    for i, o in enumerate(rank, 1):
        low = sum(1 for c in cr if cs[o][c["id"]]["confidence"] == "low")
        g = ", ".join("%s %s%s" % (k, v, (" (%s)" % basis[(o, k)]) if (o, k) in basis else "") for k, v in gates[o].get("gate_status", {}).items())
        s, gap = (P.get("options") or {}).get(o, ("TODO(prose): strength of " + o, "TODO(prose): gap of " + o))
        rows.append([i, short(o), "%.1f" % tot[o], g, low or "", s, gap])
    md += table(["Rank", "Option", "Score", "Gates", "Low-confidence criteria", "Main strength", "Main gap"], rows)
    for t in sc["ties"]:
        md += ["", "Near-tie (within %s points): %s; broken by %s." % (sc["mapping"]["tie_margin"], ", ".join(short(o) for o in t["options"]), t["tie_break"])]
    for o in sc.get("could_overtake_leader") or []:
        md += ["", "%s could overtake %s if its unknown requirements turned out to be provided." % (short(o), short(rank[0]))]
    md += ["", "## Context", "", re.sub(r"^#.*\n+", "", D.solution).strip(), "", "## Criteria and weights", ""]
    md += table(["Criterion", "Weight", "Requirements"], [[c["name"], c["weight"], ", ".join(c["requirement_ids"])] for c in D.criteria])
    md += ["", "## Weighted score matrix", ""]
    rows = [[c["name"], c["weight"]] + ["%s%s (%s)" % (("%.2f" % cs[o][c["id"]]["score"]).rstrip("0").rstrip(".") if isinstance(cs[o][c["id"]]["score"], float) else cs[o][c["id"]]["score"], "†" if cs[o][c["id"]]["capped"] else "", cs[o][c["id"]]["confidence"]) for o in rank] for c in cr]
    rows.append(["**Total**", 100] + ["**%.1f**" % tot[o] for o in rank])
    md += table(["Criterion", "Weight"] + [short(o) for o in rank], rows)
    md += ["", "Contribution of a criterion = score / %s × weight. † capped for weak evidence. Confidence: high = two sources, medium = one, low = none." % D.mx, "",
           "## Bias and assumptions", ""]
    b = sc.get("bias_checks") or {}
    pc = b.get("provider_concentration")
    items = []
    if pc and pc.get("counts"):
        items.append("Providers behind the profiled options: " + ", ".join("%s %d" % kv for kv in pc["counts"].items()) + " (largest share %d%%)." % round(pc["largest_share"] * 100))
    else:
        items.append("Providers were not recorded, so concentration could not be checked.")
    items.append("Requirements based on an assumption: " + (", ".join(a["id"] + (" (gate)" if a["gate"] else "") for a in b.get("assumed_requirements", [])) or "none") + ".")
    if b.get("source_mix"):
        items.append("Findings by source kind: " + "; ".join("%s %d vendor, %d independent or open-source docs" % (short(o), v["vendor"], v["independent_or_open_source"]) for o, v in b["source_mix"].items()) + ".")
    if b.get("cost_comparable"):
        items.append("Cost comparison covers %d of %d options with a complete price." % (b["cost_comparable"]["complete"], b["cost_comparable"]["total"]))
    md += ["- " + i for i in items] + ["", _prose(P, "bias"), "", "## Cost", ""]
    if D.cost and D.cost.get("results"):
        res = D.cost["results"]
        md += ["Currency %s, horizon %s months. Assumptions: " % (res["currency"], res["horizon_months"]) + "; ".join(
            "%s %s %s" % (a["name"], "{:,}".format(a["value"]), a["unit"]) for a in D.cost["assumptions"]) + ".", ""]
        rows = [[short(o), "{:,.0f}".format(r["monthly"]), "{:,.0f}".format(r["one_time"]), "{:,.0f}".format(r["tco"]) + (" + quote" if r.get("incomplete") else ""),
                 ", ".join(c["name"] for c in r.get("components", []) if c.get("price_unknown")) or "none"] for o, r in res["options"].items() if o in D.name]
        md += table(["Option", "Priced monthly", "One-time", "Total over horizon", "Not priced"], rows) + [""]
    md += [_prose(P, "cost"), "", "## Feature-by-feature comparison", "",
           "The full table, with notes and evidence ids in every cell, is in `eval/features.md` and in the exported report. Must-have summary:", ""]
    kinds = list(next(iter(sc["must_summary"].values())))
    md += table(["Option"] + kinds, [[short(o)] + [sc["must_summary"][o].get(k, 0) for k in kinds] for o in rank])
    flips = [x for x in sc["sensitivity"] if x["changed"]]
    cflips = [x for x in sc["confidence_tests"] if x["changed"]]
    md += ["", "## Sensitivity", "",
           "Moving each of the highest weights by 5 points %s. Lowering low-confidence scores %s." % (
               "never changes the top option" if not flips else "changes the top option in %d of %d tests" % (len(flips), len(sc["sensitivity"])),
               "never changes the top option" if not cflips else "changes the top option in %d test(s)" % len(cflips)), "", _prose(P, "sensitivity"), "",
           "## Recommended next steps", ""]
    steps = P.get("next_steps") or ["TODO(prose): next_steps"]
    md += ["%d. %s" % (i, s) for i, s in enumerate(steps, 1)]
    md += ["", "## Risks and open questions", ""] + ["- " + r for r in (P.get("risks") or ["TODO(prose): risks"])]
    na = D.crit.get("not_assessed") or []
    if na:
        md += ["", "Not assessed: " + "; ".join(na) + ". These can decide a close call.", ""]
    if P.get("changes"):
        md += ["", "### Changes since evidence was gathered", "", P["changes"], ""]
    md += ["", "## Excluded options", ""]
    failed = [x for x in sc["excluded"] if x["reason"] != "not profiled"]
    if failed:
        md += table(["Option", "Reason"], [[D.name[x["option_id"]], x["reason"]] for x in failed]) + [""]
    md += [P.get("excluded") or ("No profiled option failed a gate." if not failed else _prose(P, "excluded"))]
    skipped = [o["name"] for o in D.opts if o.get("not_profiled")]  # listed in scores.json as excluded with the reason "not profiled"
    if skipped:
        md += ["", "Listed but not profiled: " + ", ".join(skipped) + "."]
    dc = D.scores.get("deciding_cells") or {}
    if dc.get("requirements") or dc.get("gates"):
        md += ["", "## Verify before deciding", "", "The cells that decide the result; check them by hand before relying on it.", ""]
        md += ["- Gate %s for %s: %s%s." % (g["gate"], D.name.get(g["option_id"], g["option_id"]).split(" (")[0], g["verdict"], " (" + g["basis"] + ")" if g["basis"] else "") for g in dc.get("gates", [])]
        md += ["- %s: %s scores %s against %s for %s (%+.1f points)." % (x["requirement_id"], short(x["leader"]), x["leader_score"], x["runner_up_score"], short(x["runner_up"]), x["points"]) for x in dc.get("requirements", [])]
    md += ["", "## Gates", ""] + _gates_md(D)
    oi = _load(d, "open_items.json") if os.path.exists(os.path.join(d, "open_items.json")) else []
    pocs = [x for x in oi if x["owner_type"] == "poc_test"]
    if pocs:
        md += ["", "## POC tests", ""] + table(["Test", "Option", "Linked to", "What it must show", "Owner", "Status"],
                                              [[x["test_id"], short(x["option"]) if x["option"] in D.name else x["option"], x["linked"], x["question"], x.get("owner", ""), x["status"]] for x in pocs])
    rest = [x for x in oi if x["owner_type"] != "poc_test"]
    if rest:
        md += ["", "## Open verification items", ""] + table(["ID", "Option", "Linked to", "Question", "Type", "Owner", "Status"],
                                                            [[x["id"], short(x["option"]) if x["option"] in D.name else x["option"], x["linked"], x["question"], x["owner_type"], x.get("owner", ""), x["status"]] for x in rest])
    comps = [(o, c) for o in D.opts if isinstance(o.get("package"), dict) and o["option_id"] in D.name for c in o["package"]["components"]]
    if comps:
        md += ["", "## Packages scored", ""] + table(["Option", "Component", "Version", "Released", "Lifecycle", "Newest release on the evaluation date", "Compatibility"],
                                                    [[short(o["option_id"]), c["name"], c["version"], c["release_date"], c["lifecycle"], c.get("newest_release", ""), c.get("compatibility", "")] for o, c in comps])
    cpath = os.path.join(d, "candidate_requirements.json")
    if os.path.exists(cpath):
        cands = _load(d, "candidate_requirements.json")
        if cands:
            md += ["", "## Candidate requirements", "", "Found while researching and not scored. Accepting one goes back to eval-define.", ""]
            md += table(["ID", "Requirement", "Suggested priority", "Category", "Why", "Source"], [[c["id"], c["text"], c["suggested_priority"], c["suggested_category"], c["why"], c["source"]] for c in cands])
    if P.get("profiles"):
        md += ["", "## Option profiles", ""]
        for o in rank:
            if P["profiles"].get(o):
                md += ["**%s.** %s" % (short(o), P["profiles"][o]), ""]
    md += ["", "## Sources", "", "Every finding, with its source, source date, gathered date and label.", ""]
    md += table(["ID", "Option", "Req", "Finding", "Source", "Source date", "Label", "Kind"],
                [[e["evidence_id"], short(e["option_id"]) if e["option_id"] in D.name else e["option_id"], e.get("requirement_id") or e.get("criterion_id") or "", e["finding"][:220],
                  e["source_url"], e["source_date"], e["confidence"], e["source_kind"] + (" (from source code, POC candidate)" if e["source_kind"] == "source_code" and not e.get("tested") else "") + (" (out of scope)" if e.get("scope") == "out_of_scope" else "")] for e in D.ev])
    path = os.path.join(d, "report.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(_in_order(md))
    return path


def _in_order(md):
    """Put the sections into decision order (see SECTION_ORDER in export_report.py)."""
    text = "\n".join(md) + "\n"
    parts = re.split(r"(?m)^(?=## )", text)
    head, secs = parts[0], parts[1:]
    secs = order_sections(secs, lambda s: s[3:].split("\n", 1)[0].strip())
    return head + "".join(s.rstrip("\n") + "\n\n" for s in secs).rstrip("\n") + "\n"


def _gates_md(D):
    gates = D.crit.get("gates") or []
    if not gates:
        return ["No gate rubric was recorded."]
    md = []
    for g in gates:
        md += ["**%s** (%s). Passes only if all hold: %s. Package rule: %s" % (g["id"], g["requirement_id"], "; ".join(g["pass_clauses"]), g["package_rule"]), ""]
        rows = []
        for oid, v in g["verdicts"].items():
            if oid in D.name:
                rows.append([D.name[oid].split(" (")[0], v["verdict"], v.get("basis", ""), v.get("confirm_by", ""),
                             "; ".join("%d. %s" % (i, c["note"]) for i, c in enumerate(v["clauses"], 1))])
        md += table(["Option", "Verdict", "Basis", "Confirm by", "Clause notes"], rows) + [""]
    return md


def _words(t):
    return set(re.findall(r"[a-z0-9]{3,}", t.lower()))


def _caveat_problems(text, D):
    sec = re.search(r"(?ms)^##\s+(?:Risks and open questions|Caveats)\s*\n(.*?)(?=^##\s|\Z)", text)
    if not sec:
        return []
    items = [ln[2:].strip() for ln in sec.group(1).splitlines() if ln.startswith("- ")]
    out = []
    if len(items) > MAX_CAVEATS:
        out.append("%d caveats; keep at most %d" % (len(items), MAX_CAVEATS))
    oi = os.path.join(D.dir, "open_items.json")
    extra = [x["question"] for x in _load(D.dir, "open_items.json")] if os.path.exists(oi) else []
    known = extra + [t for g in D.crit.get("gates", []) for v in g["verdicts"].values() for t in [c["note"] for c in v["clauses"]] + g["pass_clauses"]]
    for it in items:
        w = _words(it)
        for k in known:
            kw = _words(k)
            if w and kw and len(w & kw) / len(w | kw) >= 0.6:
                out.append("caveat repeats gate text: " + it[:60])
                break
    return out


def check(d):
    """Return a list of problems found in eval/report.md."""
    e = eligibility(d)
    path = os.path.join(d, "report.md")
    if not os.path.exists(path) or not open(path, encoding="utf-8").read().strip():
        return ["eval/report.md is missing or empty"]
    text, problems = open(path, encoding="utf-8").read(), []
    if e["blockers"] and not re.search(r"Eligibility:\s*\**\s*%d of %d options pass every gate" % (len(e["passing"]), e["total"]), text):
        problems.append("the report does not open with 'Eligibility: %d of %d options pass every gate' and the blockers" % (len(e["passing"]), e["total"]))
    if e["total"] and not e["passing"]:
        for m in re.finditer(r"recommended option|[Cc]hoose [A-Z]", text):
            problems.append("no option passes every gate, but the report recommends one: " + m.group(0))
        for m in re.finditer(r"TODO\(prose\)[^\n|]*", text):
            problems.append("unfinished prose: " + m.group(0).strip())
        return problems
    D = Data(d)
    for m in re.finditer(r"TODO\(prose\)[^\n|]*", text):
        problems.append("unfinished prose: " + m.group(0).strip())
    for h in HEADINGS:
        if not re.search(r"^##\s+" + re.escape(h), text, re.M):
            problems.append("missing section: " + h)
    ranks = [section_rank(t) for t in re.findall(r"(?m)^##\s+(.+)$", text)]
    ranks = [r for r in ranks if r is not None]
    if ranks != sorted(ranks):
        problems.append("sections are out of decision order; expected: " + ", ".join(SECTION_ORDER))
    for m in BANNED.finditer(text):
        problems.append("process wording in the report: '%s'; the method history belongs in status.json" % m.group(0))
    problems += _caveat_problems(text, D)
    na = D.crit.get("not_assessed") or []
    if na and "Not assessed:" not in text:
        problems.append("criteria.json lists decision factors that are not assessed (%s) but the report has no 'Not assessed:' line" % "; ".join(na))
    elif na:
        line = next(ln for ln in text.splitlines() if "Not assessed:" in ln).lower()
        left = [f for f in na if f.lower() not in line]
        if left:
            problems.append("the 'Not assessed:' line leaves out %s, which criteria.json lists as not assessed" % "; ".join(left))
    sec = re.search(r"^##\s+Decision recommendation\s*\n(.*?)(?=^##\s)", text, re.M | re.S)
    rec = sec.group(1) if sec else ""
    lead = D.ranking[0]
    if lead and D.name[lead].split(" (")[0] not in rec:
        problems.append("the recommendation does not name the top-ranked option (%s)" % D.name[lead].split(" (")[0])
    # the confidence statement lives in the recommendation; the matrix legend also says "Confidence: high = ..." and must not count
    if not re.search(r"\bConfidence:\s*\**\s*(high|medium|low)\b", rec, re.I):
        problems.append("the recommendation states no confidence level (high, medium or low)")
    if re.search(r"[Cc]onfidence[^.\n]{0,40}\d+\s*%", text):
        problems.append("confidence is given as a percentage; use high, medium or low")
    m = re.search(r"\bConfidence:\s*\**\s*(high|medium|low)\b", rec, re.I)
    if m and m.group(1).lower() == "high":
        changed = D.scores.get("order_changes", "0 of 0")
        gap, need = D.scores.get("lead"), D.scores.get("meaningful_gap")
        if not changed.startswith("0 of"):
            problems.append("confidence is high but the leader changes in %s" % changed)
        if gap is not None and need is not None and gap < need:
            problems.append("confidence is high but the lead (%s points) is under the meaningful gap (%s)" % (gap, need))
    for o in D.ranking:
        if "%.1f" % D.scores["totals"][o] not in text:
            problems.append("the score of %s (%.1f) is not in the report" % (D.name[o].split(" (")[0], D.scores["totals"][o]))
    problems += _provenance_problems(text, D)
    problems += _decision_table_problems(text, D)
    problems += _recommendation_problems(rec, D)
    for x in (x for x in D.scores["excluded"] if x["reason"] != "not profiled"):
        short = D.name[x["option_id"]].split(" (")[0]
        for sent in re.split(r"(?<=[.!?])\s+", rec):
            if short in sent and not re.search(r"exclud|fail|not eligible|ineligible|gate|not met|ruled out", sent, re.I):
                problems.append("the recommendation mentions %s, which is excluded, without saying it failed a gate: '%s'" % (short, sent.strip()[:120]))
    exc = re.search(r"^##\s+Excluded options\s*\n(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    for x in (x for x in D.scores["excluded"] if x["reason"] != "not profiled"):
        short = D.name[x["option_id"]].split(" (")[0]
        if short not in text:
            problems.append("excluded option %s is not mentioned" % D.name[x["option_id"]])
        elif exc is None or short not in exc.group(1):
            problems.append("excluded option %s is not listed under 'Excluded options' with the gate it failed" % short)
    if D.scores["ties"] and not re.search(r"near-tie|\btie\b|not clear-cut|undecided", rec, re.I):
        problems.append("the scores are a near-tie but the recommendation does not say the choice is not clear-cut")
    if D.scores.get("could_overtake_leader") and not re.search(r"unknown|overtake|undecided", rec, re.I):
        problems.append("unknown requirements could change the leader but the recommendation does not say so")
    return problems


DECISIVE = re.compile(r"\b(decisive(ly)?|clear(ly)? (winner|best|ahead|better)|by a wide margin|comfortably|undisputed|outright)\b", re.I)


def _provenance_problems(text, D):
    """The first line under the title is `Evaluation date <date>. Scale 0 to <n>. Cost mode: <mode>.` and agrees with the files."""
    body = [ln for ln in text.splitlines()[1:] if ln.strip()]
    first = body[0] if body else ""
    want = "Evaluation date %s. Scale 0 to %s. Cost mode: %s" % (D.status.get("evaluation_date", "n/a"), D.mx, D.crit["cost_mode"])
    if not first.startswith(want):
        return ["the report does not open with the provenance line '%s.'" % want]
    return []


def _decision_table_problems(text, D):
    """The decision table lists the ranked options in the scorer's order with the scorer's totals."""
    sec = re.search(r"^##\s+Decision table\s*\n(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    if not sec:
        return []
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in sec.group(1).splitlines() if re.match(r"^\|\s*\d+\s*\|", ln)]
    out = []
    names = [D.name[o].split(" (")[0] for o in D.ranking]
    if [r[1] for r in rows] != names:
        out.append("the decision table order (%s) is not the scorer's ranking (%s)" % (", ".join(r[1] for r in rows), ", ".join(names)))
    for r, o in zip(rows, D.ranking):
        want = "%.1f" % D.scores["totals"][o]
        if len(r) > 2 and r[2] != want:
            out.append("the decision table gives %s a score of %s; scores.json has %s" % (r[1], r[2], want))
    return out


def _recommendation_problems(rec, D):
    """The recommendation leads with the top-ranked option, never calls a near-tie decisive, and quotes the lead correctly."""
    out = []
    if not D.ranking or not rec.strip():
        return out
    names = {o: D.name[o].split(" (")[0] for o in D.ranking}
    first = min(((rec.find(n), o) for o, n in names.items() if rec.find(n) >= 0), default=None)
    if first and first[1] != D.ranking[0]:
        out.append("the recommendation names %s first, but %s is ranked first" % (names[first[1]], names[D.ranking[0]]))
    lead, gap = D.scores.get("lead"), D.scores.get("meaningful_gap")
    close = bool(D.scores.get("ties")) or (lead is not None and gap is not None and lead < gap) or not str(D.scores.get("order_changes", "0 of")).startswith("0 of")
    m = DECISIVE.search(rec)
    if close and m:
        out.append("the lead is %s points (meaningful gap %s) or the order changes under sensitivity, but the recommendation calls it '%s'" % (lead, gap, m.group(0)))
    if lead is not None:
        for m in re.finditer(r"\bby (?:about |around |roughly )?(\d+(?:\.\d+)?) points?\b", rec):
            if abs(float(m.group(1)) - lead) > 0.55:
                out.append("the recommendation says the lead is %s points; scores.json has %s" % (m.group(1), lead))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="report_draft.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a1 = sub.add_parser("draft")
    a1.add_argument("dir")
    a1.add_argument("--prose", help="JSON file with the judgment text")
    a2 = sub.add_parser("check")
    a2.add_argument("dir")
    a = ap.parse_args(argv)
    if a.cmd == "draft":
        prose = json.load(open(a.prose, encoding="utf-8")) if a.prose else {}
        print("wrote " + draft(a.dir, prose))
        return 0
    problems = check(a.dir)
    for p in problems:
        print("PROBLEM: " + p, file=sys.stderr)
    print("ok" if not problems else "%d problem(s)" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
