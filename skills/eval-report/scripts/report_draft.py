#!/usr/bin/env python3
"""Draft and check eval/report.md.

  report_draft.py draft eval [--prose prose.json]   write eval/report.md
  report_draft.py check eval                        check the report against the computed files

`draft` writes every computed section (decision table, criteria, matrix, bias, cost,
must-have summary, sensitivity, excluded, sources) from the evaluation files, so no
number is typed by hand. The judgment text comes from a prose JSON file with these keys:
recommendation, confidence (high, medium or low), confidence_why, options (option id to
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
from export_report import Data  # noqa: E402

KEYS = ("recommendation", "confidence", "confidence_why", "bias", "cost", "sensitivity", "next_steps", "risks", "excluded")
HEADINGS = ["Decision recommendation", "Decision table", "Context", "Criteria and weights", "Weighted score matrix", "Bias and assumptions", "Cost",
            "Feature-by-feature comparison", "Sensitivity", "Recommended next steps", "Risks and open questions", "Excluded options", "Sources"]


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    return out + ["| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in r) + " |" for r in rows]


def _prose(P, key):
    v = P.get(key)
    return v if v else "TODO(prose): %s" % key


def draft(d, prose=None):
    D = Data(d)
    P = prose or {}
    sc, cs, tot, rank = D.scores, D.scores["criterion_scores"], D.scores["totals"], D.ranking
    short = lambda o: D.name[o].split(" (")[0]
    cr = [c for c in D.criteria if c["weight"] > 0]
    gates = {o["option_id"]: o for o in D.opts}
    reruns = P.get("provenance", "")
    md = ["# Evaluation report: " + D.title, "",
          ("Evaluation date %s. Scale 0 to %s. Cost mode: %s%s. %s" % (
              D.status.get("evaluation_date", "n/a"), D.mx, D.crit["cost_mode"], " (cost is shown beside the score, not in it)" if D.crit["cost_mode"] == "separate" else "", reruns)).strip(), "",
          "## Decision recommendation", "", _prose(P, "recommendation"), "",
          "**Confidence: %s.** %s" % (P.get("confidence") or "TODO(prose): confidence", _prose(P, "confidence_why")), "", "## Decision table", ""]
    rows = []
    for i, o in enumerate(rank, 1):
        low = sum(1 for c in cr if cs[o][c["id"]]["confidence"] == "low")
        g = ", ".join("%s %s" % kv for kv in gates[o].get("gate_status", {}).items())
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
    rows = [[c["name"], c["weight"]] + ["%s%s (%s)" % (cs[o][c["id"]]["score"], "†" if cs[o][c["id"]]["capped"] else "", cs[o][c["id"]]["confidence"]) for o in rank] for c in cr]
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
    kinds = ["provided", "vendor-claimed", "partial", "not provided", "unknown"]
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
    md += ["", "## Excluded options", ""]
    failed = [x for x in sc["excluded"] if x["reason"] != "not profiled"]
    if failed:
        md += table(["Option", "Reason"], [[D.name[x["option_id"]], x["reason"]] for x in failed]) + [""]
    md += [P.get("excluded") or ("No profiled option failed a gate." if not failed else _prose(P, "excluded"))]
    skipped = [o["name"] for o in D.opts if o.get("not_profiled")]  # listed in scores.json as excluded with the reason "not profiled"
    if skipped:
        md += ["", "Listed but not profiled: " + ", ".join(skipped) + "."]
    md += ["", "## Sources", "", "Every finding, with its source, source date, gathered date and label.", ""]
    md += table(["ID", "Option", "Req", "Finding", "Source", "Source date", "Label", "Kind"],
                [[e["evidence_id"], short(e["option_id"]) if e["option_id"] in D.name else e["option_id"], e.get("requirement_id") or e.get("criterion_id") or "", e["finding"][:220],
                  e["source_url"], e["source_date"], e["confidence"], e["source_kind"] + (" (out of scope)" if e.get("scope") == "out_of_scope" else "")] for e in D.ev])
    path = os.path.join(d, "report.md")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md) + "\n")
    return path


def check(d):
    """Return a list of problems found in eval/report.md."""
    D = Data(d)
    if not D.report.strip():
        return ["eval/report.md is missing or empty"]
    text, problems = D.report, []
    for m in re.finditer(r"TODO\(prose\)[^\n|]*", text):
        problems.append("unfinished prose: " + m.group(0).strip())
    for h in HEADINGS:
        if not re.search(r"^##\s+" + re.escape(h), text, re.M):
            problems.append("missing section: " + h)
    sec = re.search(r"^##\s+Decision recommendation\s*\n(.*?)(?=^##\s)", text, re.M | re.S)
    rec = sec.group(1) if sec else ""
    lead = D.ranking[0]
    if lead and D.name[lead].split(" (")[0] not in rec:
        problems.append("the recommendation does not name the top-ranked option (%s)" % D.name[lead].split(" (")[0])
    if not re.search(r"\bConfidence:\s*\**\s*(high|medium|low)\b", text, re.I):
        problems.append("the recommendation states no confidence level (high, medium or low)")
    if re.search(r"[Cc]onfidence[^.\n]{0,40}\d+\s*%", text):
        problems.append("confidence is given as a percentage; use high, medium or low")
    for o in D.ranking:
        if "%.1f" % D.scores["totals"][o] not in text:
            problems.append("the score of %s (%.1f) is not in the report" % (D.name[o].split(" (")[0], D.scores["totals"][o]))
    for x in (x for x in D.scores["excluded"] if x["reason"] != "not profiled"):
        if D.name[x["option_id"]].split(" (")[0] not in text:
            problems.append("excluded option %s is not mentioned" % D.name[x["option_id"]])
    if D.scores["ties"] and not re.search(r"near-tie|tie|not clear-cut|undecided", rec + text, re.I):
        problems.append("the scores are a near-tie but the report does not say the choice is not clear-cut")
    if D.scores.get("could_overtake_leader") and not re.search(r"unknown|overtake|undecided", rec, re.I):
        problems.append("unknown requirements could change the leader but the recommendation does not say so")
    return problems


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
