#!/usr/bin/env python3
"""Deterministic helpers for the eval skill suite. Python 3, standard library only.

Commands:
  weights ID [ID ...]         rank-sum weights for criteria listed most to least important
  validate DIR [--before S]   check the eval/ files against the workspace contract
  score DIR                   compute scores, ranking, ties, sensitivity and features.md
  cost DIR                    total cost of ownership and volume scenarios from cost.json
  status DIR                  where the evaluation stands and which skill runs next
  complete DIR STEP [--slug]  mark a step complete in status.json (creates it for define)
  changed DIR WHAT            mark the steps that depend on WHAT stale (requirements, weights, gates, options, evidence, cost, scores)
  weights ... --apply DIR     also write the weights into DIR/criteria.json
  gaps DIR [--limit N]        per option, the unknown and unsupported requirements to research first
  matrix FILE.csv             stress-test an external score table (Criterion, Weight, one numeric column per option)
  add-evidence DIR --option ... --finding ... --url ... --confidence ... --kind ...
                              append one evidence row with the next free id and print the id
"""
import argparse
import datetime
import json
import math
import os
import re
import sys
from urllib.parse import urlparse

STEPS = ["define", "analyze", "discover", "compare", "report"]
STEP_FILES = {
    "define": ["solution.md", "requirements.md", "requirements.json"],
    "analyze": ["criteria.md", "criteria.json"],
    "discover": ["options.md", "options.json", "evidence.json", "cost.json"],
    "compare": ["scores.json", "features.md"],
    "report": ["report.md"],
}
WRITERS = {"status.json": "every eval skill"}
for _step, _files in STEP_FILES.items():
    for _f in _files:
        WRITERS[_f] = "eval-" + _step

LABELS = {"PRIMARY", "CONFIRMED", "PROBABLE", "UNVERIFIED", "COULD NOT VERIFY", "DISPUTED"}
WEAK = {"UNVERIFIED", "COULD NOT VERIFY"}
SOURCE_KINDS = {"vendor", "independent", "oss_project_docs", "source_code"}
CELL_VALUES = ["provided", "vendor-claimed", "partial", "not provided", "unknown"]
GAP_VALUES = {"vendor-claimed", "partial", "not provided", "unknown"}
GATE_STATUS = {"pass", "fail", "unverified", "waived_by_user"}
PRIORITY = {"must": 3, "should": 2, "could": 1}
RANGES = {"not provided": [0, 1], "vendor-claimed": [2, 2], "partial": [2, 3], "provided": [4, 5], "unknown": [1, 1]}
MIDPOINTS = {"not provided": 0.5, "vendor-claimed": 2, "partial": 2.5, "provided": 4.5, "unknown": 1}
SCORING_MODELS = ("cell_midpoint", "anchored")
ANCHOR_POINTS = {"must": 5, "should": 3, "could": 1}  # default priority points under the anchored model
DEFAULT_ANCHORS = {"5": "exceeds the requirement", "4": "fully meets it, generally available", "3": "core is met, with limits",
                   "2": "partial, preview or beta", "1": "only via a custom build, a third-party add-on or a component outside the package", "0": "not met"}
FEATURE_STATUS = ("included", "partial", "missing")
SCOPE_TAGS = ("saas", "separate_product", "unassessed_release", "third_party", "external_service", "latest_only", "preview")
CONFIDENCE_LEVELS = ("high", "medium", "low")
RATIONALE_WORDS = 40
BANDS = (("meets (4-5)", 4), ("limits (3)", 3), ("partial (2)", 2), ("workaround (1)", 1), ("not met (0)", 0))
VERDICTS = ("PASS", "NOT MET", "UNVERIFIED")
VERDICT_STATUS = {"PASS": "pass", "NOT MET": "fail", "UNVERIFIED": "unverified"}
BASES = ("documented", "vendor_confirmed", "tested")
SOURCE_CLASSES = ("primary", "company", "secondary")
MOVING_REF = __import__("re").compile(r"/(main|master)/")
COST_KINDS = {"fixed_monthly", "one_time", "usage", "tiered"}
PER = {"hour": 730.0, "day": 365.0 / 12, "month": 1.0, "year": 1.0 / 12}  # fixed_monthly amounts quoted per hour, day, month or year
STALE_MAP = {  # what changed -> steps that depend on it (contract rule 8)
    "requirements": ["analyze", "discover", "compare", "report"],
    "weights": ["compare", "report"],
    "gates": ["discover", "compare", "report"],
    "options": ["compare", "report"],
    "evidence": ["compare", "report"],
    "cost": ["compare", "report"],
    "scores": ["report"],
}
CAP = 2
TIE_MARGIN = 3.0
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_DATE_OR_MONTH = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
# words that make a requirement untestable unless a number or an explicit placeholder pins them down (eval-define quality rule)
VAGUE = re.compile(r"\b(fast|quick(ly)?|secure|scalable|robust|performant|user[- ]friendly|easy to use|intuitive|high[- ]performance|reliable|efficient|flexible|modern|seamless(ly)?)\b", re.I)
THRESHOLD = re.compile(r"\d|TBD|\bto be (set|agreed|confirmed)\b|<[^>]+>|\[[^\]]+\]", re.I)
CONF_RANK = {"low": 0, "medium": 1, "high": 2}
REQ_KEYS = ["id", "type", "category", "text", "priority", "gate", "verification_note"]
OPT_KEYS = ["option_id", "name", "source_links", "excluded", "exclusion_reason", "not_profiled", "gate_status"]
EV_KEYS = ["evidence_id", "option_id", "finding", "source_url", "source_date", "gathered_on", "confidence", "source_kind"]
STATUS_KEYS = ["current_step", "completed_steps", "stale_steps", "stale_evidence", "evaluation_date", "report_date", "solution_slug"]


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.retired = set()  # requirement ids marked retired: kept for their history, ignored by the scorer

    def err(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)


def half_up(x):
    return int(math.floor(x + 0.5 + 1e-9))


def rank_sum_weights(ids):
    """Rank-sum weights, largest-remainder rounding, summing to 100."""
    n = len(ids)
    if n == 0:
        return {}
    points = [n - i for i in range(n)]
    total = sum(points)
    raw = [p * 100.0 / total for p in points]
    floor = [int(math.floor(r + 1e-9)) for r in raw]
    order = sorted(range(n), key=lambda i: (-(raw[i] - floor[i]), i))
    for i in order[: 100 - sum(floor)]:
        floor[i] += 1
    return dict(zip(ids, floor))


def _read_json(d, name, rep, required=False):
    path = os.path.join(d, name)
    if not os.path.exists(path):
        if required:
            rep.err("%s is missing; it is written by %s" % (name, WRITERS.get(name, "an eval skill")))
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        rep.err("%s cannot be read as JSON (%s); rerun %s" % (name, e, WRITERS.get(name, "its skill")))
        return None


def _need_keys(row, keys, where, rep):
    if not isinstance(row, dict):
        rep.err("%s must be an object" % where)
        return False
    missing = [k for k in keys if k not in row]
    if missing:
        rep.err("%s is missing keys: %s" % (where, ", ".join(missing)))
        return False
    return True


def _check_status(status, rep):
    if not _need_keys(status, STATUS_KEYS, "status.json", rep):
        return
    if status.get("post_scoring_weight_change") and not str(status.get("weight_change_reason", "")).strip():
        rep.err("status.json: weights changed after scoring, so weight_change_reason is required")
    for key in ("completed_steps", "stale_steps"):
        if not isinstance(status[key], list) or any(s not in STEPS for s in status[key]):
            rep.err("status.json %s must be a list of step names (%s)" % (key, ", ".join(STEPS)))
            return
    ev_date, rp_date = str(status.get("evaluation_date") or ""), str(status.get("report_date") or "")
    for key, val in (("evaluation_date", ev_date), ("report_date", rp_date)):
        if val and not ISO_DATE.match(val):
            rep.err("status.json %s must be a date (YYYY-MM-DD), not '%s'" % (key, val))
    if ISO_DATE.match(ev_date) and ISO_DATE.match(rp_date) and rp_date < ev_date:
        rep.err("status.json report_date %s is before evaluation_date %s" % (rp_date, ev_date))
    done = status["completed_steps"]
    for i, step in enumerate(STEPS):
        if step in done:
            missing = [p for p in STEPS[:i] if p not in done]
            if missing:
                rep.err("status.json: %s is complete but earlier step(s) %s are not; steps complete in order (run eval-%s)" % (step, ", ".join(missing), missing[0]))
                break


def _check_requirements(reqs, rep):
    ids = set()
    if not isinstance(reqs, list) or not reqs:
        rep.err("requirements.json must be a non-empty list")
        return ids
    for i, r in enumerate(reqs):
        where = "requirements.json[%d]" % i
        if not _need_keys(r, REQ_KEYS, where, rep):
            continue
        if r["id"] in ids:
            rep.err("%s: duplicate requirement id %s" % (where, r["id"]))
        ids.add(r["id"])
        if r.get("retired") is True:
            rep.retired.add(r["id"])
        elif "retired" in r and r["retired"] is not False:
            rep.err("%s: retired must be true or false" % where)
        if r["type"] not in ("functional", "non-functional"):
            rep.err("%s: type must be functional or non-functional" % where)
        if r["priority"] not in PRIORITY:
            rep.err("%s: priority must be must, should, or could" % where)
        if r.get("evidence_class") not in (None, "feature", "measure"):
            rep.err("%s: evidence_class must be feature or measure" % where)
        if r.get("basis") not in (None, "stated", "assumed"):
            rep.err("%s: basis must be stated or assumed" % where)
        if VAGUE.search(str(r["text"])) and not THRESHOLD.search(str(r["text"])):
            rep.warn("%s (%s): '%s' is vague; give a measurable threshold or an explicit placeholder such as TBD" % (where, r["id"], VAGUE.search(str(r["text"])).group(0)))
        if not str(r["text"]).strip():
            rep.err("%s: text is empty" % where)
        if not isinstance(r["gate"], bool):
            rep.err("%s: gate must be true or false" % where)
        elif r["gate"] and not str(r.get("gate_scope", "")).strip():
            rep.err("%s: gate_scope is required when gate is true" % where)
    if not any("cost" in str(r.get("category", "")).lower() for r in reqs if isinstance(r, dict)):
        rep.err("requirements.json has no cost requirement (a category containing 'cost')")
    return ids


def _check_criteria(c, req_ids, rep, strict=False):
    crit_ids = set()
    if not _need_keys(c, ["cost_mode", "scale", "criteria"], "criteria.json", rep):
        return crit_ids
    if c["cost_mode"] not in ("weighted", "separate"):
        rep.err("criteria.json cost_mode must be weighted or separate")
    sc = c["scale"]
    if not (isinstance(sc, dict) and "min" in sc and "max" in sc and sc["max"] > sc["min"]):
        rep.err("criteria.json scale needs min and max with max above min")
    elif sc["min"] != 0:
        rep.err("criteria.json scale min must be 0 (the scripts support scales starting at 0)")
    total = 0
    covered = {}
    for i, cr in enumerate(c["criteria"]):
        where = "criteria.json criterion %d" % i
        if not _need_keys(cr, ["id", "name", "category", "weight", "requirement_ids", "anchors"], where, rep):
            continue
        if cr["id"] in crit_ids:
            rep.err("%s: duplicate criterion id %s" % (where, cr["id"]))
        crit_ids.add(cr["id"])
        total += cr["weight"]
        if strict and cr["weight"] != int(cr["weight"]):
            rep.err("%s: category weight %s must be a whole number" % (where, cr["weight"]))
        if strict and cr["weight"] > 0 and len(cr["requirement_ids"]) < 2:
            rep.err("%s: category %s holds %d requirement(s); a scored category needs at least two" % (where, cr["name"], len(cr["requirement_ids"])))
        if not isinstance(cr["anchors"], dict) or any(k not in cr["anchors"] for k in ("0", "3", "5")):
            rep.err("%s: anchors need keys 0, 3 and 5" % where)
        if c.get("cost_mode") == "separate" and "cost" in str(cr["category"]).lower() and cr["weight"] != 0:
            rep.err("%s: cost criterion must have weight 0 when cost_mode is separate" % where)
        for rid in cr["requirement_ids"]:
            if rid in rep.retired:
                rep.err("%s: requirement %s is retired; remove it from the criterion" % (where, rid))
            elif req_ids and rid not in req_ids:
                rep.err("%s: unknown requirement id %s" % (where, rid))
            covered[rid] = covered.get(rid, 0) + 1
    if abs(total - 100) > 1e-9:
        rep.err("criteria weights sum to %s, not 100" % total)
    for rid in sorted(req_ids):
        if covered.get(rid, 0) != 1:
            rep.err("requirement %s is covered by %d criteria (must be exactly 1)" % (rid, covered.get(rid, 0)))
    return crit_ids


def _check_gates(crit, gate_ids, opt_ids, ev_ids, opts, rep):
    """The gate rubric: every clause judged for every option, a basis for each PASS."""
    gates = crit.get("gates") if isinstance(crit, dict) else None
    if gates is None:
        return
    if not isinstance(gates, list):
        rep.err("criteria.json gates must be a list")
        return
    status = {o["option_id"]: (o.get("gate_status") or {}) for o in opts or [] if isinstance(o, dict) and "option_id" in o}
    # an option excluded by one gate gets no further research (eval-discover step 4), so only the options still in play are judged on every gate
    profiled = [o["option_id"] for o in opts or [] if isinstance(o, dict) and "option_id" in o and not o.get("not_profiled") and not o.get("excluded")]
    rubric_for = {g.get("requirement_id") for g in gates if isinstance(g, dict)}
    for rid in sorted(gate_ids - rubric_for - rep.retired):
        rep.err("gate requirement %s has no rubric in criteria.json gates; eval-analyze writes one for every gate" % rid)
    for g in gates:
        if not isinstance(g, dict) or not isinstance(g.get("verdicts"), dict):
            continue
        for oid in profiled:
            if oid not in g["verdicts"]:
                rep.err("criteria.json gate %s has no verdict for %s; every option still in play is judged against every gate" % (g.get("id"), oid))
            if g.get("requirement_id") not in status.get(oid, {}):
                rep.err("options.json %s has no gate_status for %s; record pass, fail, unverified or waived_by_user" % (oid, g.get("requirement_id")))
    seen = set()
    for i, g in enumerate(gates):
        where = "criteria.json gate %d" % i
        if not _need_keys(g, ["id", "requirement_id", "pass_clauses", "evidence_needed", "package_rule", "verdicts"], where, rep):
            continue
        if g["id"] in seen:
            rep.err("%s: duplicate gate id %s" % (where, g["id"]))
        seen.add(g["id"])
        if gate_ids and g["requirement_id"] not in gate_ids:
            rep.err("%s: requirement %s is not a gate requirement" % (where, g["requirement_id"]))
        clauses = g["pass_clauses"]
        if not isinstance(clauses, list) or not clauses:
            rep.err("%s: pass_clauses must be a non-empty list" % where)
            continue
        for oid, v in (g["verdicts"] or {}).items():
            w = "%s verdict %s" % (where, oid)
            if opt_ids and oid not in opt_ids:
                rep.err("%s: unknown option" % w)
            verdict = v.get("verdict") if isinstance(v, dict) else None
            if verdict not in VERDICTS:
                rep.err("%s: verdict must be one of %s" % (w, ", ".join(VERDICTS)))
                continue
            cl = v.get("clauses")
            if not isinstance(cl, list) or len(cl) != len(clauses):
                rep.err("%s: needs one clause note for each of the %d pass clauses" % (w, len(clauses)))
                continue
            met = []
            for j, c in enumerate(cl):
                if not isinstance(c, dict) or c.get("met") not in (True, False, None) or not str(c.get("note", "")).strip():
                    rep.err("%s: clause %d needs met (true, false or null) and a note" % (w, j + 1))
                    continue
                met.append(c["met"])
                if c["met"] is not None and not c.get("evidence_ids"):
                    rep.err("%s: clause %d is judged %s but cites no evidence; a clause is judged only from evidence rows" % (w, j + 1, "met" if c["met"] else "not met"))
                for eid in c.get("evidence_ids", []):
                    if ev_ids and eid not in ev_ids:
                        rep.err("%s: clause %d cites unknown evidence id %s" % (w, j + 1, eid))
            if len(met) != len(cl):
                continue
            if verdict == "PASS" and not all(m is True for m in met):
                rep.err("%s: PASS needs every clause met; a clause that is not met or not checked makes the verdict UNVERIFIED or NOT MET" % w)
            if verdict == "NOT MET" and False not in met:
                rep.err("%s: NOT MET needs at least one clause marked not met" % w)
            if verdict == "UNVERIFIED" and False in met:
                rep.err("%s: a clause is marked not met, so the verdict is NOT MET" % w)
            if verdict == "PASS":
                if v.get("basis") not in BASES:
                    rep.err("%s: a PASS needs a basis of %s" % (w, ", ".join(BASES)))
                elif v["basis"] == "documented" and not str(v.get("confirm_by", "")).strip():
                    rep.err("%s: a documented PASS must name the POC test or vendor question that would confirm it (confirm_by)" % w)
            have = status.get(oid, {}).get(g["requirement_id"])
            if have and have != "waived_by_user" and have != VERDICT_STATUS[verdict]:
                rep.err("%s: options.json gate_status says %s but the rubric verdict is %s" % (w, have, verdict))


def cited_evidence(scores, crit, feats):
    """Evidence ids in order of first citation: gates, then requirement scores, then the feature table."""
    order = []

    def add(ids):
        for i in ids or []:
            if i not in order:
                order.append(i)
    for g in (crit or {}).get("gates", []) if isinstance(crit, dict) else []:
        for v in g.get("verdicts", {}).values():
            for c in v.get("clauses", []):
                add(c.get("evidence_ids"))
    for rows in (scores or {}).get("requirement_scores", {}).values():
        for r in rows.values():
            add(r.get("evidence_ids"))
    for cells in (scores or {}).get("cell_values", {}).values():
        for c in cells.values():
            add(c.get("evidence_ids"))
    for f in feats or []:
        for c in f.get("cells", {}).values():
            add(c.get("evidence_ids"))
    return order


def _doc_key(url):
    return str(url).split("#")[0].rstrip("/")


def _check_pins(ev, cited, finished, rep):
    pins, unpinned = {}, []
    for i, e in enumerate(ev):
        where = "evidence.json[%d]" % i
        if not isinstance(e, dict) or "evidence_id" not in e:
            continue
        pin = e.get("pin")
        if not str(pin or "").strip():
            unpinned.append(e["evidence_id"])
        elif str(pin).lower() == "latest" and str(e.get("source_date", "unknown")).lower() in ("", "unknown"):
            rep.err("%s (%s): pin 'latest' is only allowed with a source_date" % (where, e["evidence_id"]))
        if e.get("source_class") is not None and e["source_class"] not in SOURCE_CLASSES:
            rep.err("%s: source_class must be one of %s" % (where, ", ".join(SOURCE_CLASSES)))
        if MOVING_REF.search(str(e.get("source_url", ""))):
            rep.warn("%s (%s): the URL points at a moving branch (/main/ or /master/); cite a tag or commit" % (where, e["evidence_id"]))
        if pin:
            pins.setdefault(_doc_key(e.get("source_url")), set()).add(str(pin))
    if unpinned:
        rep.warn("%d evidence row(s) have no pin (%s); name the release, tag, commit or dated snapshot each source was read at" % (len(unpinned), ", ".join(unpinned[:6]) + (", ..." if len(unpinned) > 6 else "")))
    for url, ps in pins.items():
        if len(ps) > 1:
            rep.warn("%s is cited at different pins (%s); use one pin per document" % (url, ", ".join(sorted(ps))))
    if finished:
        for e in ev:
            if isinstance(e, dict) and e.get("evidence_id") and e["evidence_id"] not in cited:
                rep.err("evidence %s is cited by no score, gate or feature; cite it or remove it" % e["evidence_id"])


LIFECYCLES = ("supported", "lts", "outside_matrix")


def package_text(pkg):
    """One line naming what was evaluated, from the structured package or the older free text."""
    if isinstance(pkg, dict):
        return ", ".join("%s %s" % (c["name"], c["version"]) for c in pkg.get("components", []))
    return pkg or ""


def _check_package(pkg, where, rep):
    if isinstance(pkg, str):
        if not pkg.strip():
            rep.err("%s: package must name the editions and versions evaluated" % where)
        return
    comps = pkg.get("components") if isinstance(pkg, dict) else None
    if not isinstance(comps, list) or not comps:
        rep.err("%s: package needs a non-empty components list (or a text naming the editions and versions)" % where)
        return
    for j, c in enumerate(comps):
        w = "%s package component %d" % (where, j + 1)
        if not _need_keys(c, ["name", "version", "release_date", "lifecycle"], w, rep):
            continue
        if c["lifecycle"] not in LIFECYCLES:
            rep.err("%s: lifecycle must be one of %s" % (w, ", ".join(LIFECYCLES)))
        elif c["lifecycle"] == "outside_matrix":
            rep.warn("%s (%s %s) is outside the vendor's support matrix" % (w, c["name"], c["version"]))
    if len(comps) > 1 and not any(str(c.get("compatibility", "")).strip() for c in comps):
        rep.warn("%s: record compatibility between the package's components" % where)


def _check_options(opts, gate_ids, rep):
    ids, names = set(), set()
    if not isinstance(opts, list):
        rep.err("options.json must be a list")
        return ids
    for i, o in enumerate(opts):
        where = "options.json[%d]" % i
        if not _need_keys(o, OPT_KEYS, where, rep):
            continue
        if o["option_id"] in ids:
            rep.err("%s: duplicate option_id %s" % (where, o["option_id"]))
        ids.add(o["option_id"])
        nm = str(o["name"]).strip().lower()
        if nm in names:
            rep.err("%s: duplicate option name %s; every option needs a distinct name for the report" % (where, o["name"]))
        names.add(nm)
        if "provider" in o and not (isinstance(o["provider"], str) and o["provider"].strip()):
            rep.err("%s: provider must be a non-empty string naming the company or foundation behind the option" % where)
        if "package" in o:
            _check_package(o["package"], where, rep)
        ob = o.get("oss_base")
        if ob is not None and not (isinstance(ob, dict) and all(str(ob.get(k, "")).strip() for k in ("project", "ref", "source"))):
            rep.err("%s: oss_base must be null (checked, none) or give project, ref and source" % where)
        if o["excluded"] and not str(o["exclusion_reason"]).strip():
            rep.err("%s: excluded options need an exclusion_reason" % where)
        for gid, st in (o["gate_status"] or {}).items():
            if st not in GATE_STATUS:
                rep.err("%s: gate_status %s has invalid value %s" % (where, gid, st))
            if gate_ids and gid not in gate_ids:
                rep.err("%s: gate_status refers to %s, which is not a gate" % (where, gid))
    return ids


def _check_evidence(ev, opt_ids, req_ids, crit_ids, rep):
    ids = set()
    if not isinstance(ev, list):
        rep.err("evidence.json must be a list")
        return ids
    for i, e in enumerate(ev):
        where = "evidence.json[%d]" % i
        if not _need_keys(e, EV_KEYS, where, rep):
            continue
        if e["evidence_id"] in ids:
            rep.err("%s: duplicate evidence_id %s" % (where, e["evidence_id"]))
        ids.add(e["evidence_id"])
        if not e.get("requirement_id") and not e.get("criterion_id"):
            rep.err("%s: needs requirement_id and/or criterion_id" % where)
        if e["confidence"] not in LABELS:
            rep.err("%s: confidence must be one of %s" % (where, ", ".join(sorted(LABELS))))
        if e["confidence"] == "CONFIRMED" and e["source_kind"] == "vendor":
            rep.warn("%s (%s): CONFIRMED means two or more independent sources agree; a vendor statement on its own is PRIMARY (as an attributed statement)" % (where, e["evidence_id"]))
        if e["confidence"] == "PRIMARY" and e["source_kind"] == "independent":
            rep.warn("%s (%s): PRIMARY is the source itself (official documentation, a filing); one independent source is PROBABLE, two that agree are CONFIRMED" % (where, e["evidence_id"]))
        for key in ("finding", "source_url"):
            if not str(e[key]).strip():
                rep.err("%s (%s): %s is empty; every row states what was found and where" % (where, e["evidence_id"], key))
        _check_evidence_dates(e, where, rep)
        if e["source_kind"] not in SOURCE_KINDS:
            rep.err("%s: source_kind must be vendor, independent, oss_project_docs or source_code" % where)
        if e["source_kind"] == "source_code":
            if "@" not in str(e["source_url"]) and "@" not in str(e.get("pin", "")):
                rep.err("%s: a source_code finding cites path@commit (in source_url or pin)" % where)
            if not str(e.get("lines", "")).strip():
                rep.err("%s: a source_code finding needs a line range in `lines`, such as 120-148" % where)
            if e["confidence"] in ("PRIMARY", "CONFIRMED") and not e.get("tested"):
                rep.err("%s: reading code is PROBABLE at best unless a test proves it (set tested: true)" % where)
        if e.get("scope") not in (None, "in_scope", "out_of_scope"):
            rep.err("%s: scope must be in_scope or out_of_scope" % where)
        if opt_ids and e["option_id"] not in opt_ids:
            rep.err("%s: unknown option_id %s" % (where, e["option_id"]))
        if e.get("requirement_id") and req_ids and e["requirement_id"] not in req_ids:
            rep.err("%s: unknown requirement_id %s" % (where, e["requirement_id"]))
        if e.get("criterion_id") and crit_ids and e["criterion_id"] not in crit_ids:
            rep.err("%s: unknown criterion_id %s" % (where, e["criterion_id"]))
    return ids


def _check_evidence_dates(e, where, rep, today=None):
    """gathered_on is a real date that is not in the future; source_date is a date, a month or unknown, and not after gathered_on."""
    today = today or datetime.date.today().isoformat()
    g, sd = str(e.get("gathered_on", "")), str(e.get("source_date", ""))
    if not ISO_DATE.match(g):
        rep.err("%s (%s): gathered_on must be a date (YYYY-MM-DD), not '%s'" % (where, e.get("evidence_id"), g))
        g = None
    elif g > today:
        rep.err("%s (%s): gathered_on %s is in the future" % (where, e.get("evidence_id"), g))
    if sd.lower() == "unknown":
        return
    if not ISO_DATE_OR_MONTH.match(sd):
        rep.err("%s (%s): source_date must be YYYY-MM-DD, YYYY-MM or unknown, not '%s'" % (where, e.get("evidence_id"), sd))
    elif g and sd[:len(g)] > g[:len(sd)]:
        rep.err("%s (%s): source_date %s is after gathered_on %s; a source cannot be read before it exists" % (where, e.get("evidence_id"), sd, g))


def model_of(scores):
    return scores.get("scoring_model", "cell_midpoint") if isinstance(scores, dict) else "cell_midpoint"


def _check_anchored(scores, opt_ids, req_ids, ev_ids, rep):
    if not isinstance(scores.get("requirement_scores"), dict):
        rep.err("scores.json needs a requirement_scores object when scoring_model is anchored")
        return
    for oid, rows in scores["requirement_scores"].items():
        if opt_ids and oid not in opt_ids:
            rep.err("scores.json requirement_scores: unknown option %s" % oid)
        for rid, row in (rows or {}).items():
            where = "scores.json requirement_scores %s/%s" % (oid, rid)
            if req_ids and rid not in req_ids:
                rep.err("%s: unknown requirement" % where)
            if not isinstance(row, dict) or not _num(row.get("score")) or not 0 <= row["score"] <= 5:
                rep.err("%s: score must be a number from 0 to 5" % where)
                continue
            if row.get("confidence") not in CONFIDENCE_LEVELS:
                rep.err("%s: confidence must be high, medium or low" % where)
            words = len(str(row.get("rationale", "")).split())
            if not words:
                rep.warn("%s: no rationale" % where)
            elif words > RATIONALE_WORDS:
                rep.warn("%s: rationale has %d words; keep it to %d" % (where, words, RATIONALE_WORDS))
            for eid in row.get("evidence_ids", []):
                if ev_ids and eid not in ev_ids:
                    rep.err("%s: unknown evidence id %s" % (where, eid))
    pp = scores.get("priority_points")
    if pp is not None and (not isinstance(pp, dict) or set(pp) != set(ANCHOR_POINTS) or not all(_num(v) and v > 0 for v in pp.values())):
        rep.err("scores.json priority_points needs positive numbers for must, should and could")
    for x in scores.get("overrides", []):
        if not x.get("requirement_id") or (req_ids and x["requirement_id"] not in req_ids):
            rep.err("scores.json override under the anchored model needs a known requirement_id")


OWNER_TYPES = ("vendor_question", "poc_test", "contract_term")


def _check_open_items(d, opt_ids, req_ids, crit, rep):
    items = _read_json(d, "open_items.json", rep)
    if items is None:
        return
    if not isinstance(items, list):
        rep.err("open_items.json must be a list")
        return
    gate_ids = {g["id"] for g in (crit or {}).get("gates", [])} | {g["requirement_id"] for g in (crit or {}).get("gates", [])}
    seen, tests = set(), set()
    for i, it in enumerate(items):
        where = "open_items.json[%d]" % i
        if not _need_keys(it, ["id", "option", "linked", "question", "owner_type", "status"], where, rep):
            continue
        if it["id"] in seen:
            rep.err("%s: duplicate id %s" % (where, it["id"]))
        seen.add(it["id"])
        if it["owner_type"] not in OWNER_TYPES:
            rep.err("%s: owner_type must be one of %s" % (where, ", ".join(OWNER_TYPES)))
        if it["status"] not in ("open", "closed"):
            rep.err("%s: status must be open or closed" % where)
        if opt_ids and it["option"] not in opt_ids:
            rep.err("%s: unknown option %s" % (where, it["option"]))
        if it["linked"] not in req_ids and it["linked"] not in gate_ids:
            rep.err("%s: linked id %s is neither a requirement nor a gate" % (where, it["linked"]))
        if it["owner_type"] == "poc_test":
            tid = str(it.get("test_id", ""))
            if not re.fullmatch(r"P\d+", tid):
                rep.err("%s: a poc_test needs a test_id such as P1" % where)
            elif tid in tests:
                rep.err("%s: duplicate test_id %s" % (where, tid))
            tests.add(tid)
    for g in (crit or {}).get("gates", []):
        for oid, v in g["verdicts"].items():
            for t in re.findall(r"\bP\d+\b", str(v.get("confirm_by", ""))):
                if t not in tests:
                    rep.err("gate %s verdict %s names test %s, which is not in open_items.json" % (g["id"], oid, t))


def verify_queue(d):
    """What to re-check first: weak or inherited scores and documented gate passes, ordered by weight times the gap between options."""
    rep = validate(d)
    reqs = _read_json(d, "requirements.json", rep, True)
    crit = _read_json(d, "criteria.json", rep, True)
    scores = _read_json(d, "scores.json", rep, True)
    ev = _read_json(d, "evidence.json", rep, True)
    if rep.errors:
        return rep, None
    req = {r["id"]: r for r in reqs if not r.get("retired")}
    pts = scores.get("priority_points") or ANCHOR_POINTS
    ev_by = {e["evidence_id"]: e for e in ev}
    queue = []
    for g in crit.get("gates", []):
        for oid, v in g["verdicts"].items():
            why = []
            if v["verdict"] == "UNVERIFIED":
                why.append("unverified")
            if v.get("basis") == "documented":
                why.append("documented only")
            if why:
                queue.append({"kind": "gate", "id": g["id"], "option_id": oid, "reasons": why, "priority": 1000.0})
    rs = scores.get("requirement_scores", {})
    for c in crit["criteria"]:
        den = sum(pts[req[r]["priority"]] for r in c["requirement_ids"]) or 1
        for r in c["requirement_ids"]:
            vals = [rs[o][r]["score"] for o in rs if r in rs[o]]
            spread = (max(vals) - min(vals)) if vals else 0
            worth = c["weight"] * pts[req[r]["priority"]] / den
            for o, rows in rs.items():
                row = rows.get(r)
                if row is None:
                    continue
                why = []
                if row["confidence"] in ("low", "medium"):
                    why.append(row["confidence"] + " confidence")
                if "not read" in str(row.get("rationale", "")).lower():
                    why.append("page not read")
                cited = row.get("evidence_ids", [])
                if cited and all(ev_by.get(i, {}).get("inherited_from_oss") for i in cited):
                    why.append("inherited from open source only")
                if why:
                    queue.append({"kind": "requirement", "id": r, "option_id": o, "reasons": why, "score": row["score"], "priority": round(worth * (spread + 1), 2)})
    queue.sort(key=lambda x: (-x["priority"], x["id"], x["option_id"]))
    return rep, queue


def _check_features(d, opt_ids, req_ids, ev_ids, rep):
    feats = _read_json(d, "features.json", rep)
    if feats is None:
        return
    if not isinstance(feats, list):
        rep.err("features.json must be a list")
        return
    seen = set()
    for i, f in enumerate(feats):
        where = "features.json[%d]" % i
        if not _need_keys(f, ["id", "category", "name", "cells"], where, rep):
            continue
        if f["id"] in seen:
            rep.err("%s: duplicate feature id %s" % (where, f["id"]))
        seen.add(f["id"])
        for oid, cell in (f["cells"] or {}).items():
            if opt_ids and oid not in opt_ids:
                rep.err("%s: unknown option %s" % (where, oid))
            if not isinstance(cell, dict) or cell.get("status") not in FEATURE_STATUS:
                rep.err("%s/%s: status must be one of %s" % (where, oid, ", ".join(FEATURE_STATUS)))
                continue
            for eid in cell.get("evidence_ids", []):
                if ev_ids and eid not in ev_ids:
                    rep.err("%s/%s: unknown evidence id %s" % (where, oid, eid))
            bad = [t for t in cell.get("scope_tags", []) if t not in SCOPE_TAGS]
            if bad:
                rep.err("%s/%s: unknown scope tag %s; use %s" % (where, oid, ", ".join(bad), ", ".join(SCOPE_TAGS)))


def _check_scores(scores, opt_ids, req_ids, ev_ids, rep):
    if not isinstance(scores, dict):
        rep.err("scores.json must be an object")
        return
    model = model_of(scores)
    if model not in SCORING_MODELS:
        rep.err("scores.json scoring_model must be one of %s" % ", ".join(SCORING_MODELS))
        return
    for k in ("features", "feature_cells"):
        if k in scores:
            rep.err("scores.json must not hold %s: the feature table lives in features.json and never feeds the score" % k)
    if model == "anchored":
        _check_anchored(scores, opt_ids, req_ids, ev_ids, rep)
        if "cell_values" not in scores:
            return
    if not isinstance(scores.get("cell_values"), dict):
        rep.err("scores.json needs a cell_values object")
        return
    for oid, cells in scores["cell_values"].items():
        if opt_ids and oid not in opt_ids:
            rep.err("scores.json cell_values: unknown option %s" % oid)
        for rid, cell in cells.items():
            where = "scores.json cell_values %s/%s" % (oid, rid)
            if req_ids and rid not in req_ids:
                rep.err("%s: unknown requirement" % where)
            if not isinstance(cell, dict) or cell.get("value") not in CELL_VALUES:
                rep.err("%s: value must be one of %s" % (where, ", ".join(CELL_VALUES)))
                continue
            for eid in cell.get("evidence_ids", []):
                if ev_ids and eid not in ev_ids:
                    rep.err("%s: unknown evidence id %s" % (where, eid))


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_component(comp, where, aids, ev_ids, rep):
    if not _need_keys(comp, ["id", "name", "kind"], where, rep):
        return
    kind = comp["kind"]
    if kind not in COST_KINDS:
        rep.err("%s: kind must be one of %s" % (where, ", ".join(sorted(COST_KINDS))))
        return
    unknown = comp.get("price_unknown") is True
    eid = comp.get("evidence_id")
    if comp.get("assumed") is True:
        if not str(comp.get("assumption_note", "")).strip():
            rep.err("%s: an assumed component needs an assumption_note saying where the number comes from" % where)
    elif not unknown and not eid:
        rep.err("%s: a priced component needs an evidence_id (or assumed: true with an assumption_note, or price_unknown: true)" % where)
    if eid and ev_ids and eid not in ev_ids:
        rep.err("%s: unknown evidence_id %s" % (where, eid))
    if unknown:
        return
    need = {"fixed_monthly": ["amount"], "one_time": ["amount"], "usage": ["unit_price", "driver"], "tiered": ["tiers", "driver"]}[kind]
    if not _need_keys(comp, need, where, rep):
        return
    for key in ("amount", "unit_price", "included_free", "quantity"):
        if key in comp and (not _num(comp[key]) or comp[key] < 0):
            rep.err("%s: %s must be a non-negative number" % (where, key))
    for key in ("driver", "quantity_driver"):
        if comp.get(key) and comp[key] not in aids:
            rep.err("%s: %s refers to unknown assumption %s" % (where, key, comp[key]))
    if comp.get("per", "month") not in PER:
        rep.err("%s: per must be one of %s" % (where, ", ".join(sorted(PER))))
    if comp.get("per", "month") != "month" and kind != "fixed_monthly":
        rep.err("%s: per applies to fixed_monthly components only" % where)
    steps = comp.get("quantity_steps")
    if steps is not None:
        if kind != "fixed_monthly" or not comp.get("quantity_driver"):
            rep.err("%s: quantity_steps needs a fixed_monthly component with a quantity_driver" % where)
        ok = isinstance(steps, list) and steps and all(isinstance(s, dict) and _num(s.get("quantity")) and "up_to" in s for s in steps)
        if not ok:
            rep.err("%s: quantity_steps need up_to and quantity" % where)
        else:
            ups = [s["up_to"] for s in steps]
            if ups[-1] is not None or any(u is None for u in ups[:-1]) or ups[:-1] != sorted(ups[:-1]):
                rep.err("%s: quantity_steps must have ascending up_to and end with up_to null" % where)
    if kind == "tiered":
        tiers = comp["tiers"]
        if not isinstance(tiers, list) or not tiers or any(not isinstance(t, dict) or "unit_price" not in t or "up_to" not in t for t in tiers):
            rep.err("%s: tiers need up_to and unit_price" % where)
        else:
            ups = [t["up_to"] for t in tiers]
            if ups[-1] is not None or any(u is None for u in ups[:-1]) or ups[:-1] != sorted(ups[:-1]):
                rep.err("%s: tiers must have ascending up_to and end with up_to null" % where)
            if any(not _num(t["unit_price"]) or t["unit_price"] < 0 for t in tiers):
                rep.err("%s: tier unit_price must be a non-negative number" % where)
        if comp.get("tier_mode", "graduated") not in ("graduated", "volume"):
            rep.err("%s: tier_mode must be graduated or volume" % where)


def _check_cost(cost, opts, ev_ids, rep):
    if not _need_keys(cost, ["currency", "horizon_months", "assumptions", "options"], "cost.json", rep):
        return
    if not _num(cost["horizon_months"]) or cost["horizon_months"] <= 0:
        rep.err("cost.json horizon_months must be a positive number")
    aids = set()
    for i, a in enumerate(cost["assumptions"]):
        where = "cost.json assumption %d" % i
        if _need_keys(a, ["id", "name", "value", "unit"], where, rep):
            if a["id"] in aids:
                rep.err("%s: duplicate assumption id %s" % (where, a["id"]))
            aids.add(a["id"])
            if not _num(a["value"]) or a["value"] < 0:
                rep.err("%s: value must be a non-negative number" % where)
    for sc in cost.get("scenarios", []):
        if not (isinstance(sc, dict) and sc.get("name") and _num(sc.get("multiplier")) and sc["multiplier"] >= 0):
            rep.err("cost.json scenarios need a name and a non-negative multiplier")
    opt_by_id = {o["option_id"]: o for o in (opts or []) if isinstance(o, dict) and "option_id" in o}
    for oid, entry in cost["options"].items():
        if opt_by_id and oid not in opt_by_id:
            rep.err("cost.json: unknown option %s" % oid)
        comps = entry.get("components") if isinstance(entry, dict) else None
        if not isinstance(comps, list) or not comps:
            rep.err("cost.json option %s needs a non-empty components list" % oid)
            continue
        seen = set()
        for j, comp in enumerate(comps):
            where = "cost.json %s component %d" % (oid, j)
            if isinstance(comp, dict) and comp.get("id") in seen:
                rep.err("%s: duplicate component id %s" % (where, comp["id"]))
            if isinstance(comp, dict):
                seen.add(comp.get("id"))
            _check_component(comp, where, aids, ev_ids, rep)
    for oid, o in opt_by_id.items():
        if not o.get("excluded") and not o.get("not_profiled") and oid not in cost["options"]:
            rep.err("cost.json has no cost model for %s; eval-discover must price every profiled option" % o.get("name", oid))


def validate(d, before=None):
    rep = Report()
    if not os.path.isdir(d):
        rep.err("%s is not a folder" % d)
        return rep
    needs_prior = bool(before) and before != "define"
    status = _read_json(d, "status.json", rep, required=needs_prior)
    if needs_prior:
        for step in STEPS[: STEPS.index(before)]:
            for fn in STEP_FILES[step]:
                if not os.path.exists(os.path.join(d, fn)):
                    rep.err("%s is missing; it is written by eval-%s" % (fn, step))
            if isinstance(status, dict) and step not in status.get("completed_steps", []):
                rep.err("step %s is not complete; run eval-%s" % (step, step))
        if isinstance(status, dict) and status.get("stale_steps"):
            rep.err("stale steps: %s; rerun the earliest one first" % ", ".join(status["stale_steps"]))
    if status is not None:
        _check_status(status, rep)
    reqs = _read_json(d, "requirements.json", rep)
    crit = _read_json(d, "criteria.json", rep)
    opts = _read_json(d, "options.json", rep)
    ev = _read_json(d, "evidence.json", rep)
    scores = _read_json(d, "scores.json", rep)
    cost = _read_json(d, "cost.json", rep)
    req_ids = _check_requirements(reqs, rep) if reqs is not None else set()
    gate_ids = {r["id"] for r in reqs if isinstance(r, dict) and r.get("gate") is True} if isinstance(reqs, list) else set()
    crit_ids = _check_criteria(crit, req_ids - rep.retired, rep, strict=model_of(scores) == "anchored") if crit is not None else set()
    opt_ids = _check_options(opts, gate_ids, rep) if opts is not None else set()
    ev_ids = _check_evidence(ev, opt_ids, req_ids, crit_ids, rep) if ev is not None else set()
    if crit is not None:
        _check_gates(crit, gate_ids, opt_ids, ev_ids, opts if isinstance(opts, list) else None, rep)
    if scores is not None:
        _check_scores(scores, opt_ids, req_ids, ev_ids, rep)
    if os.path.exists(os.path.join(d, "candidate_requirements.json")):
        cands = _read_json(d, "candidate_requirements.json", rep)
        for i, c in enumerate(cands if isinstance(cands, list) else []):
            if not _need_keys(c, ["id", "text", "suggested_priority", "suggested_category", "why", "source"], "candidate_requirements.json[%d]" % i, rep):
                continue
            if c["suggested_priority"] not in PRIORITY:
                rep.err("candidate_requirements.json[%d]: suggested_priority must be must, should or could" % i)
        if not isinstance(cands, list):
            rep.err("candidate_requirements.json must be a list")
    if os.path.exists(os.path.join(d, "open_items.json")):
        _check_open_items(d, opt_ids, req_ids, crit if isinstance(crit, dict) else None, rep)
    if os.path.exists(os.path.join(d, "features.json")):
        _check_features(d, opt_ids, req_ids, ev_ids, rep)
    if isinstance(ev, list):
        feats = _read_json(d, "features.json", Report()) if os.path.exists(os.path.join(d, "features.json")) else None
        done = isinstance(status, dict) and "compare" in status.get("completed_steps", [])
        _check_pins(ev, set(cited_evidence(scores if isinstance(scores, dict) else None, crit, feats if isinstance(feats, list) else None)),
                    done and model_of(scores) == "anchored", rep)
    if isinstance(opts, list) and isinstance(ev, list):
        have = {(e.get("option_id"), e.get("requirement_id")) for e in ev if isinstance(e, dict)}
        for o in opts:
            for gid, st in ((o.get("gate_status") or {}) if isinstance(o, dict) else {}).items():
                if st in ("pass", "fail") and (o.get("option_id"), gid) not in have:
                    rep.warn("gate %s is marked %s for %s without an evidence row for that requirement" % (gid, st, o.get("name", o.get("option_id"))))
    if cost is not None:
        _check_cost(cost, opts if isinstance(opts, list) else None, ev_ids, rep)
    if isinstance(opts, list):
        _check_option_names(opts, reqs if isinstance(reqs, list) else [], crit if isinstance(crit, dict) else {}, rep)
    if isinstance(scores, dict) and isinstance(ev, list) and isinstance(opts, list):
        _check_score_citations(scores, ev, opts, reqs if isinstance(reqs, list) else [], crit if isinstance(crit, dict) else {}, rep)
    if isinstance(opts, list) and isinstance(ev, list):
        # oss_base null means "checked, none"; a missing key means "not checked", which bias_checks reports
        none = {o.get("option_id") for o in opts if isinstance(o, dict) and "oss_base" in o and not o["oss_base"]}
        for e in ev:
            if isinstance(e, dict) and e.get("inherited_from_oss") and e.get("option_id") in none:
                rep.err("evidence %s is marked inherited_from_oss but option %s records oss_base null (no open-source base to inherit from)" % (e.get("evidence_id"), e.get("option_id")))
        feats = _read_json(d, "features.json", Report()) if os.path.exists(os.path.join(d, "features.json")) else None
        owner = {e.get("evidence_id"): e.get("option_id") for e in ev if isinstance(e, dict)}
        for f in feats if isinstance(feats, list) else []:
            for oid, cell in ((f.get("cells") or {}).items() if isinstance(f, dict) else []):
                for eid in (cell or {}).get("evidence_ids", []) if isinstance(cell, dict) else []:
                    if eid in owner and owner[eid] != oid:
                        rep.err("features.json %s/%s cites %s, which is evidence about %s" % (f.get("id"), oid, eid, owner[eid]))
    if before == "report" and not rep.errors and isinstance(scores, dict) and isinstance(scores.get("totals"), dict):
        _check_scores_current(d, scores, rep)
    return rep


def _check_scores_current(d, scores, rep):
    """The computed part of scores.json still follows from the inputs: nothing was edited after the last `score` run."""
    crep, fresh = compute(d, write=False)
    if fresh is None:
        rep.err("scores.json cannot be recomputed (%s); rerun eval-compare" % "; ".join(crep.errors[:2]))
        return
    old, new = scores.get("totals", {}), fresh.get("totals", {})
    diff = sorted(o for o in set(old) | set(new) if o not in old or o not in new or abs(old[o] - new[o]) > 0.05)
    if diff or scores.get("ranking") != fresh.get("ranking"):
        rep.err("scores.json is out of date: recomputing gives %s instead of %s; weights, scores or evidence changed after scoring. "
                "Run `eval_calc.py changed eval <topic>` and rerun eval-compare" % (
                    ", ".join("%s %.1f" % (o, new[o]) for o in fresh.get("ranking", [])), ", ".join("%s %.1f" % (o, old[o]) for o in scores.get("ranking", []) if o in old)))


def _name_pattern(o):
    names = [str(o.get("name", "")).strip()]
    return [re.compile(r"(?<![\w-])%s(?![\w-])" % re.escape(n), re.I) for n in names if len(n) >= 3]


def _check_option_names(opts, reqs, crit, rep):
    """Requirements and criteria describe needs, never a candidate (eval-define and eval-analyze quality rules)."""
    pats = [(o.get("name"), p) for o in opts if isinstance(o, dict) for p in _name_pattern(o)]
    for r in reqs:
        if isinstance(r, dict):
            for n, p in pats:
                if p.search(str(r.get("text", ""))):
                    rep.warn("requirement %s names the option %s; a requirement describes the need, not a product" % (r.get("id"), n))
    for c in crit.get("criteria", []) if isinstance(crit.get("criteria"), list) else []:
        if not isinstance(c, dict):
            continue
        text = " ".join([str(c.get("name", ""))] + [str(v) for v in (c.get("anchors") or {}).values()])
        for n, p in pats:
            if p.search(text):
                rep.err("criterion %s names the option %s; no criterion may mention a specific option" % (c.get("id"), n))


def _check_score_citations(scores, ev, opts, reqs, crit, rep):
    """A score cites evidence about the same option and, when the row names one, the same requirement or its criterion."""
    by_id = {e["evidence_id"]: e for e in ev if isinstance(e, dict) and "evidence_id" in e}
    crit_of = {}
    for c in crit.get("criteria", []) if isinstance(crit.get("criteria"), list) else []:
        for rid in c.get("requirement_ids", []) if isinstance(c, dict) else []:
            crit_of[rid] = c.get("id")
    excluded = {o["option_id"] for o in opts if isinstance(o, dict) and (o.get("excluded") or o.get("not_profiled"))}
    for oid, rows in (scores.get("requirement_scores") or {}).items():
        if oid in excluded:
            rep.warn("scores.json scores %s, which is excluded or not profiled; its scores are ignored and it is never ranked" % oid)
        for rid, row in (rows or {}).items():
            for eid in (row or {}).get("evidence_ids", []) if isinstance(row, dict) else []:
                e = by_id.get(eid)
                if not e:
                    continue
                if e.get("option_id") != oid:
                    rep.err("scores.json %s/%s cites %s, which is evidence about %s; cite evidence about the option scored" % (oid, rid, eid, e.get("option_id")))
                elif e.get("requirement_id") and e["requirement_id"] != rid and e.get("criterion_id") != crit_of.get(rid):
                    rep.warn("scores.json %s/%s cites %s, which is evidence for requirement %s" % (oid, rid, eid, e["requirement_id"]))


# ---- cost model ----------------------------------------------------------

def _tiered_monthly(comp, units):
    tiers = comp["tiers"]
    if comp.get("tier_mode", "graduated") == "volume":
        for t in tiers:
            if t["up_to"] is None or units <= t["up_to"]:
                return units * t["unit_price"]
    total, prev = 0.0, 0.0
    for t in tiers:
        top = units if t["up_to"] is None else min(units, t["up_to"])
        if top > prev:
            total += (top - prev) * t["unit_price"]
            prev = top
    return total


def _component_cost(comp, vals):
    """Return (monthly, one_time, price_unknown) for one priced component."""
    if comp.get("price_unknown"):
        return 0.0, 0.0, True
    qty = vals[comp["quantity_driver"]] if comp.get("quantity_driver") else comp.get("quantity", 1)
    if comp.get("quantity_steps"):
        v = vals[comp["quantity_driver"]]
        qty = next(s["quantity"] for s in comp["quantity_steps"] if s["up_to"] is None or v <= s["up_to"])
    kind = comp["kind"]
    if kind == "fixed_monthly":
        return comp["amount"] * PER[comp.get("per", "month")] * qty, 0.0, False
    if kind == "one_time":
        return 0.0, comp["amount"] * qty, False
    units = vals[comp["driver"]]
    if kind == "usage":
        return comp["unit_price"] * max(0.0, units - comp.get("included_free", 0)), 0.0, False
    return _tiered_monthly(comp, units), 0.0, False


def _scenario_vals(cost, multiplier):
    return {a["id"]: a["value"] * (multiplier if a.get("scales") else 1) for a in cost["assumptions"]}


def compute_cost(d, write=True):
    """Total cost of ownership per option over the horizon, plus volume scenarios."""
    rep = Report()
    cost = _read_json(d, "cost.json", rep, True)
    opts = _read_json(d, "options.json", rep, True)
    ev = _read_json(d, "evidence.json", rep, True)
    if cost is not None:
        _check_cost(cost, opts, {e["evidence_id"] for e in ev or [] if isinstance(e, dict) and "evidence_id" in e}, rep)
    if rep.errors:
        return rep, None
    weak = {e["evidence_id"] for e in ev if e["confidence"] in WEAK}
    horizon = cost["horizon_months"]
    scenarios = cost.get("scenarios") or [{"name": "low", "multiplier": 0.5}, {"name": "high", "multiplier": 2}]
    result = {"currency": cost["currency"], "horizon_months": horizon, "options": {}, "scenarios": [s["name"] for s in scenarios]}
    for oid, entry in cost["options"].items():
        comps = entry["components"]
        base = _scenario_vals(cost, 1)
        rows, monthly, once, incomplete, gaps, assumed = [], 0.0, 0.0, False, [], []
        for comp in comps:
            m, o, unknown = _component_cost(comp, base)
            monthly, once, incomplete = monthly + m, once + o, incomplete or unknown
            if comp.get("assumed"):
                assumed.append(comp["id"])
            if unknown or not comp.get("evidence_id") or comp["evidence_id"] in weak:
                gaps.append(comp["id"])
            rows.append({"id": comp["id"], "name": comp["name"], "monthly": round(m, 2), "one_time": round(o, 2)})
        by_scenario = {}
        for sc in scenarios:
            vals = _scenario_vals(cost, sc["multiplier"])
            tot_m = sum(_component_cost(c, vals)[0] for c in comps)
            tot_o = sum(_component_cost(c, vals)[1] for c in comps)
            by_scenario[sc["name"]] = round(tot_o + tot_m * horizon, 2)
        result["options"][oid] = {
            "monthly": round(monthly, 2), "one_time": round(once, 2), "tco": round(once + monthly * horizon, 2),
            "incomplete": incomplete, "evidence_gaps": gaps, "assumed": assumed, "components": rows, "scenarios": by_scenario,
        }
    ids = list(result["options"])
    # an option with an unknown price is never compared: its total is only a lower bound
    complete = [o for o in ids if not result["options"][o]["incomplete"]]
    result["ranking"] = sorted(complete, key=lambda o: result["options"][o]["tco"]) + [o for o in ids if o not in complete]
    result["cheapest"] = result["ranking"][0] if complete else None
    cheapest = result["options"][result["cheapest"]]["tco"] if complete else None
    for o in ids:
        opt = result["options"][o]
        opt["index_vs_cheapest"] = round(opt["tco"] / cheapest, 2) if cheapest and not opt["incomplete"] else None
    result["cheapest_by_scenario"] = {n: (min(complete, key=lambda o: result["options"][o]["scenarios"][n]) if complete else None) for n in result["scenarios"]}
    if write:
        cost["results"] = result
        with open(os.path.join(d, "cost.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(cost, f, indent=2, ensure_ascii=False)
            f.write("\n")
    return rep, result


def add_evidence(d, option_id, finding, url, confidence, kind, requirement_id=None, criterion_id=None, source_date="unknown", gathered_on=None, scope=None, pin=None, source_class=None):
    """Append one evidence row with the next free id and return the id."""
    import datetime
    rep = Report()
    ev = _read_json(d, "evidence.json", rep) or []
    opts = _read_json(d, "options.json", rep) or []
    if not (requirement_id or criterion_id):
        rep.err("give --requirement and/or --criterion")
    if confidence not in LABELS:
        rep.err("confidence must be one of %s" % ", ".join(sorted(LABELS)))
    if kind not in SOURCE_KINDS:
        rep.err("kind must be vendor, independent, oss_project_docs or source_code")
    if opts and option_id not in {o["option_id"] for o in opts}:
        rep.err("unknown option %s" % option_id)
    if scope not in (None, "in_scope", "out_of_scope"):
        rep.err("scope must be in_scope or out_of_scope")
    if rep.errors:
        return rep, None
    nums = [int(e["evidence_id"][2:]) for e in ev if str(e.get("evidence_id", "")).startswith("E-") and e["evidence_id"][2:].isdigit()]
    eid = "E-%03d" % (max(nums, default=0) + 1)
    row = {"evidence_id": eid, "option_id": option_id, "finding": finding, "source_url": url, "source_date": source_date,
           "gathered_on": gathered_on or datetime.date.today().isoformat(), "confidence": confidence, "source_kind": kind}
    if requirement_id:
        row["requirement_id"] = requirement_id
    if criterion_id:
        row["criterion_id"] = criterion_id
    if scope == "out_of_scope":
        row["scope"] = scope
    if pin:
        row["pin"] = pin
    if source_class:
        row["source_class"] = source_class
    ev.append(row)
    with open(os.path.join(d, "evidence.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(ev, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return rep, eid


def find_gaps(d, limit=8):
    """Where each option's evidence is thin, most important first: unknown values and values no non-weak evidence supports."""
    rep = validate(d)
    reqs = _read_json(d, "requirements.json", rep, True)
    crit = _read_json(d, "criteria.json", rep, True)
    opts = _read_json(d, "options.json", rep, True)
    ev = _read_json(d, "evidence.json", rep, True)
    scores = _read_json(d, "scores.json", rep, True)
    if rep.errors:
        return rep, None
    weak = {e["evidence_id"] for e in ev if e["confidence"] in WEAK}
    weight = {rid: c["weight"] for c in crit["criteria"] for rid in c["requirement_ids"]}
    crit_of = {rid: c["id"] for c in crit["criteria"] for rid in c["requirement_ids"]}
    order = {"must": 0, "should": 1, "could": 2}
    out = {}
    for o in opts:
        if o["excluded"] or o["not_profiled"]:
            continue
        rows = []
        for r in reqs:
            if r.get("retired"):
                continue
            if model_of(scores) == "anchored":
                row = scores.get("requirement_scores", {}).get(o["option_id"], {}).get(r["id"])
                cell = {"value": "unknown" if row is None else "scored", "note": (row or {}).get("rationale", ""), "evidence_ids": (row or {}).get("evidence_ids", [])}
            else:
                cell = scores["cell_values"].get(o["option_id"], {}).get(r["id"]) or {"value": "unknown", "note": "", "evidence_ids": []}
            if cell["value"] == "unknown":
                state = "unknown"
            elif not any(eid not in weak for eid in cell.get("evidence_ids", [])):
                state = "unsupported"
            else:
                continue
            rows.append({"requirement_id": r["id"], "text": r["text"], "priority": r["priority"], "criterion_id": crit_of[r["id"]],
                         "criterion_weight": weight[r["id"]], "state": state, "note": cell.get("note", "")})
        rows.sort(key=lambda x: (order[x["priority"]], -x["criterion_weight"], x["requirement_id"]))
        out[o["option_id"]] = {"name": o["name"], "total_gaps": len(rows), "research_first": rows[:limit]}
    return rep, out


def apply_weights(d, ids):
    """Write rank-sum weights for the ranked criterion ids into criteria.json; criteria not listed get weight 0."""
    rep = Report()
    crit = _read_json(d, "criteria.json", rep, True)
    if rep.errors:
        return rep, None
    known = {c["id"] for c in crit["criteria"]}
    unknown = [i for i in ids if i not in known]
    if unknown:
        rep.err("unknown criterion id(s): %s" % ", ".join(unknown))
        return rep, None
    wts = rank_sum_weights(ids)
    for c in crit["criteria"]:
        c["weight"] = wts.get(c["id"], 0)
    with open(os.path.join(d, "criteria.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(crit, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return rep, wts


def _write_status(d, status):
    with open(os.path.join(d, "status.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(status, f, indent=2, ensure_ascii=False)
        f.write("\n")


def complete_step(d, step, slug=None, today=None):
    """Mark a step complete in status.json (creating it for define) and clear its stale flag."""
    import datetime
    rep = Report()
    today = today or datetime.date.today().isoformat()
    path = os.path.join(d, "status.json")
    if os.path.exists(path):
        status = _read_json(d, "status.json", rep) or {}
    elif step == "define":
        os.makedirs(d, exist_ok=True)
        status = {"current_step": "", "completed_steps": [], "stale_steps": [], "stale_evidence": [], "evaluation_date": today, "report_date": "", "solution_slug": slug or ""}
    else:
        rep.err("status.json is missing; run eval-define first")
        return rep, None
    for earlier in STEPS[: STEPS.index(step)]:
        if earlier not in status.get("completed_steps", []):
            rep.err("step %s is not complete; complete it before %s" % (earlier, step))
    if rep.errors:
        return rep, None
    status["completed_steps"] = [s for s in STEPS if s in set(status.get("completed_steps", [])) | {step}]
    status["stale_steps"] = [s for s in status.get("stale_steps", []) if s != step]
    status["current_step"] = step
    if step == "analyze":
        status["weights_locked_on"] = today
    if slug:
        status["solution_slug"] = slug
    if step == "define" and not status.get("evaluation_date"):
        status["evaluation_date"] = today
    if step == "report":
        status["report_date"] = today
    _write_status(d, status)
    return rep, status


def mark_changed(d, what, reason=None):
    """Mark the completed steps that depend on `what` as stale (contract rule 8)."""
    rep = Report()
    if what not in STALE_MAP:
        rep.err("what must be one of %s" % ", ".join(sorted(STALE_MAP)))
        return rep, None
    status = _read_json(d, "status.json", rep, True)
    if rep.errors:
        return rep, None
    done = set(status.get("completed_steps", []))
    if what == "weights" and "compare" in done:  # weights moved after scores existed: say why, keep only the latest reason
        if not str(reason or "").strip():
            rep.err("weights changed after eval-compare ran; give a one-line --reason (only the latest reason is kept)")
            return rep, None
        status["post_scoring_weight_change"] = True
        status["weight_change_reason"] = reason.strip()
    stale = set(status.get("stale_steps", [])) | {s for s in STALE_MAP[what] if s in done}
    status["stale_steps"] = [s for s in STEPS if s in stale]
    _write_status(d, status)
    return rep, status["stale_steps"]


def _age_months(date_text, today):
    """Whole months between an ISO date and today, or None when the date is missing or unknown."""
    import datetime
    try:
        y, m, dd = (int(x) for x in str(date_text)[:10].split("-"))
        d0 = datetime.date(y, m, dd)
    except (ValueError, TypeError):
        return None
    return (today.year - d0.year) * 12 + today.month - d0.month - (1 if today.day < d0.day else 0)


def find_stale_evidence(d, today=None, fast=(), write=False):
    """Evidence whose gathered_on or source_date is older than 3 months (options in `fast`) or 12 months.

    With write=True the ids go into status.json as stale_evidence and compare and report
    are marked stale when there are any. Unknown source dates are never counted.
    """
    import datetime
    rep = Report()
    today = today or datetime.date.today()
    ev = _read_json(d, "evidence.json", rep, True)
    status = _read_json(d, "status.json", rep, True) if write else None
    if rep.errors:
        return rep, None
    stale = []
    for e in ev:
        limit = 3 if e.get("option_id") in set(fast) else 12
        ages = [a for a in (_age_months(e.get("gathered_on"), today), _age_months(e.get("source_date"), today)) if a is not None]
        if ages and max(ages) > limit:
            stale.append({"evidence_id": e["evidence_id"], "option_id": e.get("option_id"), "age_months": max(ages), "limit_months": limit})
    if write:
        status["stale_evidence"] = [x["evidence_id"] for x in stale]
        if stale:
            done = set(status.get("completed_steps", []))
            marked = set(status.get("stale_steps", [])) | {x for x in STALE_MAP["evidence"] if x in done}
            status["stale_steps"] = [x for x in STEPS if x in marked]
        _write_status(d, status)
    return rep, stale


# ---- status --------------------------------------------------------------

def status_report(d):
    """Where an evaluation stands and which skill should run next."""
    path = os.path.join(d, "status.json")
    base = os.path.dirname(os.path.abspath(d))
    arch = os.path.join(base, "eval-archive")
    archived = sorted(os.listdir(arch)) if os.path.isdir(arch) else []
    if not os.path.exists(path):
        return {"exists": False, "action": "start", "next_step": "define", "skill": "eval-define", "completed_steps": [],
                "stale_steps": [], "problems": [], "archived": archived}
    rep = validate(d)
    status = _read_json(d, "status.json", rep) or {}
    done = [s for s in STEPS if s in status.get("completed_steps", [])]
    stale = [s for s in STEPS if s in status.get("stale_steps", [])]
    if stale:
        action, step = "rerun", stale[0]
    else:
        todo = [s for s in STEPS if s not in done]
        action, step = ("continue", todo[0]) if todo else ("done", None)
    out = {"exists": True, "action": action, "next_step": step, "skill": "eval-" + step if step else None, "completed_steps": done,
           "stale_steps": stale, "problems": rep.errors, "archived": archived, "solution_slug": status.get("solution_slug"),
           "evaluation_date": status.get("evaluation_date"), "report_date": status.get("report_date")}
    summary = {}
    for name, key in (("requirements.json", "requirements"), ("criteria.json", "criteria"), ("options.json", "options"), ("evidence.json", "evidence_rows")):
        data = _read_json(d, name, Report())
        data = data["criteria"] if name == "criteria.json" and isinstance(data, dict) else data
        if isinstance(data, list):
            summary[key] = len(data)
    scores = _read_json(d, "scores.json", Report())
    if isinstance(scores, dict) and scores.get("ranking"):
        top = scores["ranking"][0]
        names = {o["option_id"]: o["name"] for o in (_read_json(d, "options.json", Report()) or []) if isinstance(o, dict)}
        summary["top_option"] = names.get(top, top)
        summary["top_score"] = scores["totals"][top]
        summary["near_tie"] = bool(scores.get("ties"))
    out["summary"] = summary
    return out


# ---- scoring -------------------------------------------------------------

def _totals(opt_ids, cscores, weights, mx):
    return {o: round(sum(cscores[o][c] / mx * w for c, w in weights.items()) + 1e-9, 1) for o in opt_ids}


def _rank(opt_ids, totals, cscores, gaps, weights, margin=None):
    margin = TIE_MARGIN if margin is None else margin
    top_c = max(weights, key=lambda c: weights[c])
    ordered = sorted(opt_ids, key=lambda o: -totals[o])
    groups = []
    for o in ordered:
        if groups and totals[groups[-1][0]] - totals[o] <= margin + 1e-9:
            groups[-1].append(o)
        else:
            groups.append([o])
    ranking, ties = [], []
    for g in groups:
        if len(g) > 1:
            g2 = sorted(g, key=lambda o: (gaps[o], -cscores[o][top_c], -totals[o]))
            if len({gaps[o] for o in g}) > 1:
                used = "fewer must-have gaps"
            elif len({cscores[o][top_c] for o in g}) > 1:
                used = "higher score on highest-weight criterion"
            else:
                used = "total score"
            ties.append({"options": g2, "tie_break": used})
            ranking += g2
        else:
            ranking += g
    return ranking, ties


def _independent_sources(rows):
    keys = set()
    for r in rows:
        if r["confidence"] in WEAK:
            continue
        if r["source_kind"] in ("independent", "oss_project_docs", "source_code"):
            keys.add(r["source_kind"] + ":" + urlparse(r["source_url"]).netloc.lower())
    return len(keys)


def supported_confidence(rows, requirement):
    """The highest confidence the cited evidence supports (contract rule 13).

    Independent organisations count one each; the vendor's own documentation counts once more, and only for what a
    product provides. Weak and DISPUTED rows count for nothing: conflicting sources confirm nothing.
    """
    usable = [r for r in rows if r.get("confidence") not in WEAK and r.get("confidence") != "DISPUTED" and r.get("scope") != "out_of_scope"]
    n = _independent_sources(usable)
    if _is_feature(requirement) and any(r.get("source_kind") == "vendor" for r in usable):
        n += 1
    return "high" if n >= 2 else "medium" if n == 1 else "low"


def _is_feature(r):
    """A requirement about what a product provides, as opposed to how well it performs."""
    return bool(r) and (r.get("evidence_class") == "feature" or (r.get("evidence_class") is None and r["type"] == "functional"))


def bias_checks(reqs, opts, ev, included, name, cost_summary, rep):
    """Checks that the candidate set, the constraints and the evidence were not narrowed or tilted without anyone deciding so."""
    bias = {}
    inc = [o for o in opts if o["option_id"] in included]
    provs = [o["provider"] for o in inc if o.get("provider")]
    if provs:
        counts = {p: provs.count(p) for p in sorted(set(provs))}
        share = round(max(counts.values()) / len(provs), 2)
        bias["provider_concentration"] = {"counts": counts, "largest_share": share, "profiled_with_provider": len(provs), "profiled": len(inc)}
        if len(provs) >= 3 and share > 0.5:
            top = max(counts, key=counts.get)
            rep.warn("%d of %d profiled options come from %s; confirm that a stated requirement, not an assumption, narrowed the candidates to one provider, "
                     "and add alternatives from other providers or open source" % (counts[top], len(provs), top))
    elif len(inc) >= 3:
        bias["provider_concentration"] = {"counts": {}, "largest_share": None, "profiled_with_provider": 0, "profiled": len(inc)}
    checked = [o for o in inc if "oss_base" in o]
    with_base = [o for o in inc if o.get("oss_base")]
    bias["oss_base"] = {"with_base": [o["option_id"] for o in with_base], "unchecked": [o["option_id"] for o in inc if "oss_base" not in o]}
    if with_base and len(checked) < len(inc):
        rep.warn("oss_base is set for %s but not checked for %s; apply the open-source inheritance rule to every option or to none" % (
            ", ".join(o["name"] for o in with_base), ", ".join(o["name"] for o in inc if "oss_base" not in o)))
    assumed = [{"id": r["id"], "text": r["text"], "gate": bool(r["gate"])} for r in reqs if r.get("basis") == "assumed"]
    bias["assumed_requirements"] = assumed
    for a in assumed:
        if a["gate"]:
            rep.warn("gate %s is an assumption, not something the user stated; options excluded or ranked by it need the user's confirmation" % a["id"])
    mix = {}
    for o in inc:
        rows = [e for e in ev if e["option_id"] == o["option_id"]]
        mix[o["option_id"]] = {"vendor": sum(1 for e in rows if e["source_kind"] == "vendor"), "independent_or_open_source": sum(1 for e in rows if e["source_kind"] != "vendor")}
    bias["source_mix"] = mix
    if mix and all(v["independent_or_open_source"] == 0 for v in mix.values()):
        rep.warn("every finding comes from the options' own publications; scores reflect what each vendor documents, not independent confirmation")
    elif mix and any(v["independent_or_open_source"] == 0 for v in mix.values()) and any(v["independent_or_open_source"] > 0 for v in mix.values()):
        rep.warn("independent sources exist for some options but not for %s; unequal scrutiny favours the options that were checked less" %
                 ", ".join(name[k] for k, v in mix.items() if v["independent_or_open_source"] == 0))
    if cost_summary:
        total = len(cost_summary["options"])
        complete = sum(1 for v in cost_summary["options"].values() if not v["incomplete"])
        bias["cost_comparable"] = {"complete": complete, "total": total}
        if 0 < complete < total:
            rep.warn("cost compares only %d of %d options: the others have no published price. The cheapest option is the cheapest among those, not overall" % (complete, total))
    return bias


def largest_remainder(shares, total):
    """Round non-negative shares that sum to `total` to whole numbers that still sum to `total`."""
    s = sum(shares.values()) or 1.0
    raw = {k: v * total / s for k, v in shares.items()}
    out = {k: int(math.floor(v + 1e-9)) for k, v in raw.items()}
    left = int(round(total)) - sum(out.values())
    for k in sorted(raw, key=lambda k: (-(raw[k] - out[k]), k))[:max(left, 0)]:
        out[k] += 1
    return out


def _anchored_option(o, name, req, criteria, scores, ev_by_id, mx, rep):
    """Score one option under the anchored model: every requirement 0 to 5, then priority-weighted means per criterion."""
    pts = scores.get("priority_points") or ANCHOR_POINTS
    ovr = {(x["option_id"], x["requirement_id"]): x for x in scores.get("overrides", []) if x.get("requirement_id")}
    given = scores.get("requirement_scores", {}).get(o, {})
    rows, missing = {}, []
    for rid in req:
        row = dict(given.get(rid) or {})
        if not row:
            missing.append(rid)
            row = {"score": 0, "confidence": "low", "rationale": "", "evidence_ids": [], "missing": True}
        cited = row.get("evidence_ids", [])
        if row["score"] >= 1 and cited and all(ev_by_id.get(i, {}).get("scope") == "out_of_scope" for i in cited):
            rep.err("%s / %s is scored %s but every source behind it is out of scope (a component the gate excludes); score it 0" % (name[o], rid, row["score"]))
        weak = not any(i in ev_by_id and ev_by_id[i]["confidence"] not in WEAK for i in cited)
        if not row.get("missing"):
            supported = supported_confidence([ev_by_id[i] for i in cited if i in ev_by_id], req.get(rid))
            claimed = row.get("confidence")
            if claimed in CONF_RANK and CONF_RANK[claimed] > CONF_RANK[supported]:
                rep.warn("%s / %s claims %s confidence but its evidence supports %s (contract rule 13: two sources high, one medium, none low); lowered to %s" % (name[o], rid, claimed, supported, supported))
                row["confidence"] = supported
        if cited and all(ev_by_id.get(i, {}).get("inherited_from_oss") for i in cited) and row.get("confidence") == "high":
            rep.warn("%s / %s rests only on inherited open-source evidence, which never gives high confidence; lowered to medium" % (name[o], rid))
            row["confidence"] = "medium"
        if row["score"] == 0 and not cited and not row.get("missing"):
            rep.warn("%s / %s is scored 0 with no evidence; 'not met' needs a source saying the capability is absent. "
                     "If nothing could be read, leave it unscored (unknown) and research it" % (name[o], rid))
        row["capped"] = False
        if weak and row["score"] > CAP and not row.get("missing"):
            rep.warn("%s / %s is scored %s but rests on no evidence above UNVERIFIED; capped at %d" % (name[o], rid, row["score"], CAP))
            row["score"], row["capped"] = CAP, True
        x = ovr.get((o, rid))
        row["overridden"] = bool(x)
        if x:
            if not str(x.get("reason", "")).strip():
                rep.err("override for %s / %s needs a reason" % (name[o], rid))
            if abs(x["score"] - row["score"]) > 1:
                rep.warn("override for %s / %s moves the score by more than one point" % (name[o], rid))
            row["score"] = x["score"]
        rows[rid] = row
    if missing:
        rep.warn("%s has no requirement score for %s; counted as 0 (and as 4 in the best case)" % (name[o], ", ".join(missing)))
    detail, cs, cs_ub = {}, {}, {}
    for c in criteria:
        den = sum(pts[req[rid]["priority"]] for rid in c["requirement_ids"])
        num = sum(pts[req[rid]["priority"]] * rows[rid]["score"] for rid in c["requirement_ids"])
        num_ub = sum(pts[req[rid]["priority"]] * (4 if rows[rid].get("missing") else rows[rid]["score"]) for rid in c["requirement_ids"])
        low_share = sum(pts[req[rid]["priority"]] for rid in c["requirement_ids"] if rows[rid]["confidence"] == "low") / den
        conf = "low" if low_share >= 0.5 else "high" if all(rows[rid]["confidence"] == "high" for rid in c["requirement_ids"]) else "medium"
        cs[c["id"]] = num / den / 5 * mx
        cs_ub[c["id"]] = num_ub / den / 5 * mx
        cited = sorted({i for rid in c["requirement_ids"] for i in rows[rid].get("evidence_ids", [])})
        detail[c["id"]] = {"score": round(cs[c["id"]], 3), "confidence": conf, "capped": any(rows[rid]["capped"] for rid in c["requirement_ids"]),
                           "overridden": any(rows[rid]["overridden"] for rid in c["requirement_ids"]), "evidence_ids": cited, "rationale": ""}
    musts = [rid for rid in req if req[rid]["priority"] == "must"]
    summary = {b: sum(1 for rid in musts if rows[rid]["score"] >= lo and (b == BANDS[0][0] or rows[rid]["score"] < hi))
               for (b, lo), hi in zip(BANDS, [None] + [lo for _, lo in BANDS])}
    return {"cs": cs, "cs_ub": cs_ub, "detail": detail, "rows": rows, "missing": missing, "gaps": sum(1 for rid in musts if rows[rid]["score"] <= 2), "summary": summary}


def _scenarios(included, criteria, weights, cscores, rscores, req, scores, gaps, mx, margin, base_top, conf_tests):
    """The ways people challenge a ranking: equal weights, must-haves only, the two largest weights traded, low-confidence scores lowered."""
    live = [c for c in weights if weights[c] > 0]
    out = []

    def add(name, w, cs):
        t = _totals(included, cs, w, mx)
        r, _ = _rank(included, t, cs, gaps, w, margin)
        out.append({"name": name, "totals": t, "leader": r[0], "changed": r[0] != base_top})
    add("base weights", weights, cscores)
    add("equal category weights", {c: 100.0 / len(live) if c in live else 0 for c in weights}, cscores)
    if rscores:
        pts = scores.get("priority_points") or ANCHOR_POINTS
        cs = {}
        for o in included:
            cs[o] = {}
            for c in criteria:
                ids = [r for r in c["requirement_ids"] if req[r]["priority"] == "must"] or c["requirement_ids"]
                cs[o][c["id"]] = sum(pts["must"] * rscores[o][r]["score"] for r in ids) / (pts["must"] * len(ids)) / 5 * mx if ids and all(req[r]["priority"] == "must" for r in ids) \
                    else sum(pts[req[r]["priority"]] * rscores[o][r]["score"] for r in ids) / sum(pts[req[r]["priority"]] for r in ids) / 5 * mx
        add("must-have requirements only", weights, cs)
    top2 = sorted(live, key=lambda c: -weights[c])[:2]
    if len(top2) == 2:
        a, b = top2
        for x, y in ((a, b), (b, a)):
            if weights[y] >= 5:
                w2 = dict(weights)
                w2[x], w2[y] = weights[x] + 5, weights[y] - 5
                add("5 points moved from %s to %s" % (y, x), w2, cscores)
    for t in conf_tests[:1]:
        out.append({"name": t["test"], "totals": t["totals"], "leader": t["top"], "changed": t["changed"]})
    ranked = sorted(included, key=lambda o: -out[0]["totals"][o])
    lead = round(out[0]["totals"][ranked[0]] - out[0]["totals"][ranked[1]], 1) if len(ranked) > 1 else None
    n = sum(1 for x in out if x["changed"])
    return {"scenarios": out, "order_changes": "%d of %d scenarios" % (n, len(out)), "lead": lead}


def _deciding_cells(ranking, rscores, criteria, req, scores, crit, share=0.8):
    """What a person should check by hand: every gate verdict, plus the must-have scores that explain 80% of the lead."""
    out = {"gates": [], "requirements": []}
    for g in (crit.get("gates") or []):
        for oid, v in g["verdicts"].items():
            out["gates"].append({"gate": g["id"], "option_id": oid, "verdict": v["verdict"], "basis": v.get("basis", "")})
    if not rscores or len(ranking) < 2:
        return out
    a, b = ranking[0], ranking[1]
    pts = scores.get("priority_points") or ANCHOR_POINTS
    rows = []
    for c in criteria:
        den = sum(pts[req[r]["priority"]] for r in c["requirement_ids"])
        for r in c["requirement_ids"]:
            if req[r]["priority"] == "must":
                worth = c["weight"] * pts["must"] / den / 5
                rows.append({"requirement_id": r, "leader": a, "runner_up": b, "leader_score": rscores[a][r]["score"], "runner_up_score": rscores[b][r]["score"],
                             "points": round((rscores[a][r]["score"] - rscores[b][r]["score"]) * worth, 2)})
    rows.sort(key=lambda x: -abs(x["points"]))
    gap = sum(x["points"] for x in rows)
    run = 0.0
    for x in rows:
        if x["points"] == 0 or (gap > 0 and run >= share * gap):
            break
        out["requirements"].append(x)
        run += x["points"]
    return out


def compute(d, write=True):
    """Score the evaluation. With write=False nothing is written: used to check that scores.json is current."""
    rep = validate(d)
    reqs = _read_json(d, "requirements.json", rep, True)
    crit = _read_json(d, "criteria.json", rep, True)
    opts = _read_json(d, "options.json", rep, True)
    ev = _read_json(d, "evidence.json", rep, True)
    scores = _read_json(d, "scores.json", rep, True)
    if rep.errors:
        return rep, None
    cost_summary = None
    if os.path.exists(os.path.join(d, "cost.json")):
        crep, cres = compute_cost(d, write=write)
        rep.errors += crep.errors
        if cres:
            cost_summary = {"currency": cres["currency"], "horizon_months": cres["horizon_months"], "cheapest": cres["cheapest"],
                            "options": {o: {k: v[k] for k in ("tco", "monthly", "one_time", "incomplete", "evidence_gaps", "assumed")} for o, v in cres["options"].items()}}
    else:
        rep.warn("no cost.json; cost is not modelled")
    if rep.errors:
        return rep, None
    req = {r["id"]: r for r in reqs if not r.get("retired")}
    criteria = crit["criteria"]
    mx = crit["scale"]["max"]
    factor = mx / 5.0
    cap = half_up(CAP * factor)
    weights = {c["id"]: c["weight"] for c in criteria}
    name = {o["option_id"]: o["name"] for o in opts}
    included, excluded = [], []
    for o in opts:
        statuses = (o["gate_status"] or {}).values()
        if "fail" in statuses and not o["excluded"]:
            rep.warn("%s fails a gate but is not marked excluded; treated as excluded" % o["name"])
            excluded.append(o)
        elif o["excluded"] or o["not_profiled"]:
            excluded.append(o)
        else:
            if "unverified" in statuses:
                rep.err("%s has an unverified gate; resolve or waive it in eval-discover before ranking" % o["name"])
            included.append(o["option_id"])
    if rep.errors:
        return rep, None
    anchored = model_of(scores) == "anchored"
    cells_in = scores.get("cell_values", {})
    rscores = {}
    overrides = {(x["option_id"], x["criterion_id"]): x for x in scores.get("overrides", []) if x.get("criterion_id")}
    rationales = scores.get("rationales", {})
    cscores = {o: {} for o in included}
    cscores_ub = {o: {} for o in included}  # the same scores if every unknown cell turned out to be provided
    unknown_n = {}
    all_rationales = []
    detail = {o: {} for o in included}
    cells = {o: {} for o in included}
    gaps, must_summary = {}, {}
    ev_by_id = {e["evidence_id"]: e for e in ev}
    for o in included:
        if anchored:
            r = _anchored_option(o, name, req, criteria, scores, ev_by_id, mx, rep)
            cscores[o], cscores_ub[o], detail[o], rscores[o] = r["cs"], r["cs_ub"], r["detail"], r["rows"]
            gaps[o], must_summary[o], unknown_n[o] = r["gaps"], r["summary"], len(r["missing"])
            all_rationales += [x["rationale"] for x in r["rows"].values() if x["rationale"]]
            continue
        missing = []
        for rid in req:
            cell = cells_in.get(o, {}).get(rid)
            if cell is None:
                missing.append(rid)
                cell = {"value": "unknown", "note": "", "evidence_ids": []}
            cells[o][rid] = cell
            cited = cell.get("evidence_ids", [])
            if cell["value"] in ("provided", "partial", "vendor-claimed") and cited and all(ev_by_id.get(i, {}).get("scope") == "out_of_scope" for i in cited):
                rep.err("%s / %s is marked %s but every source behind it is out of scope (a component the gate excludes, such as a vendor-hosted service); mark it not provided"
                        % (name[o], rid, cell["value"]))
        if missing:
            rep.warn("%s has no cell value for %s; counted as unknown" % (name[o], ", ".join(missing)))
        for c in criteria:
            num = den = 0.0
            for rid in c["requirement_ids"]:
                p = PRIORITY[req[rid]["priority"]]
                num += p * MIDPOINTS[cells[o][rid]["value"]] * factor
                den += p
            score = min(mx, half_up(num / den))
            cited = {eid for rid in c["requirement_ids"] for eid in cells[o][rid].get("evidence_ids", [])}
            rows = [e for e in ev if e["option_id"] == o and (e.get("requirement_id") in c["requirement_ids"]
                                                                or e.get("criterion_id") == c["id"] or e["evidence_id"] in cited)]
            capped = not rows or all(e["confidence"] in WEAK for e in rows)
            if capped:
                score = min(score, cap)
            n_ind = _independent_sources(rows)
            if any(e["source_kind"] == "vendor" and e["confidence"] == "PRIMARY" and _is_feature(req.get(e.get("requirement_id"))) for e in rows):
                n_ind += 1  # the vendor's official documentation counts once, for what the product provides
            conf = "high" if n_ind >= 2 else "medium" if n_ind == 1 else "low"
            ovr = overrides.get((o, c["id"]))
            if ovr:
                if not str(ovr.get("reason", "")).strip():
                    rep.err("override for %s / %s needs a reason" % (name[o], c["id"]))
                if abs(ovr["score"] - score) > 1:
                    rep.warn("override for %s / %s moves the score by more than one point" % (name[o], c["id"]))
                score = ovr["score"]
            rationale = rationales.get(o, {}).get(c["id"], "")
            if not rationale and c["weight"] > 0:
                rep.warn("no rationale for %s / %s" % (name[o], c["id"]))
            cscores[o][c["id"]] = score
            num_ub = sum(PRIORITY[req[rid]["priority"]] * (MIDPOINTS["provided"] if cells[o][rid]["value"] == "unknown" else MIDPOINTS[cells[o][rid]["value"]]) * factor
                         for rid in c["requirement_ids"])
            cscores_ub[o][c["id"]] = ovr["score"] if ovr else min(mx, half_up(num_ub / den))
            if rationale:
                all_rationales.append(rationale)
            detail[o][c["id"]] = {
                "score": score, "confidence": conf, "capped": capped, "overridden": bool(ovr),
                "evidence_ids": sorted({e["evidence_id"] for e in rows}), "rationale": rationale,
            }
        unknown_n[o] = sum(1 for rid in req if cells[o][rid]["value"] == "unknown")
        musts = [rid for rid in req if req[rid]["priority"] == "must"]
        gaps[o] = sum(1 for rid in musts if cells[o][rid]["value"] in GAP_VALUES)
        must_summary[o] = {v: sum(1 for rid in musts if cells[o][rid]["value"] == v) for v in CELL_VALUES}
    # evidence depth: requirements with a known value backed by at least one non-weak evidence row
    weak_ids = {e["evidence_id"] for e in ev if e["confidence"] in WEAK}
    if anchored:
        coverage = {o: sum(1 for rid in req if not rscores[o][rid].get("missing")
                           and any(eid not in weak_ids for eid in rscores[o][rid].get("evidence_ids", []))) for o in included}
    else:
        coverage = {o: sum(1 for rid in req if cells[o][rid]["value"] != "unknown"
                           and any(eid not in weak_ids for eid in cells[o][rid].get("evidence_ids", []))) for o in included}
    best = max(coverage.values(), default=0)
    for o in included:
        if len(included) > 1 and best and coverage[o] * 3 < best * 2:
            rep.warn("%s has evidence-backed values for %d of %d requirements against %d for the best-covered option; its scores may reflect how little "
                     "was researched, not its capability. Give every option the same depth of research before ranking" % (name[o], coverage[o], len(req), best))
    if rep.errors or not included:
        if not included:
            rep.err("no included options to score")
        return rep, None
    totals = _totals(included, cscores, weights, mx)
    margin = crit.get("meaningful_gap", 5 if anchored else TIE_MARGIN)
    ranking, ties = _rank(included, totals, cscores, gaps, weights, margin)
    base_top = ranking[0]
    totals_ub = _totals(included, cscores_ub, weights, mx)
    overtake = [o for o in included if o != base_top and totals_ub[o] > totals[base_top]]
    unknown_bounds = {o: {"as_scored": totals[o], "if_unknowns_provided": totals_ub[o], "unknown_cells": unknown_n[o]} for o in included}
    for text, n in sorted(((t, all_rationales.count(t)) for t in set(all_rationales)), key=lambda x: -x[1]):
        if n > 2:
            rep.warn("the same rationale is used for %d scores (%s); write a specific sentence for each" % (n, text[:50]))
    if overtake:
        rep.warn("unknown values could change the leader: %s could overtake %s if its unknown requirements turned out to be provided; "
                 "research the unknowns before relying on the ranking" % (", ".join(name[o] for o in overtake), name[base_top]))

    sens = []
    for cid in [c for c in sorted(weights, key=lambda k: -weights[k]) if weights[c] > 0][:3]:
        for delta in (5, -5):
            old = weights[cid]
            new = min(100, max(0, old + delta))
            if old >= 100:
                continue
            k = (100.0 - new) / (100.0 - old)
            w2 = {c: (new if c == cid else weights[c] * k) for c in weights}
            t2 = _totals(included, cscores, w2, mx)
            r2, ties2 = _rank(included, t2, cscores, gaps, w2, margin)
            sens.append({"criterion_id": cid, "delta": delta, "weights": {c: round(v, 2) for c, v in w2.items()},
                         "totals": t2, "top": r2[0], "changed": r2[0] != base_top, "tie": bool(ties2 and r2[0] in ties2[0]["options"])})

    def lowered(cells_to_lower):
        cs = {o: dict(v) for o, v in cscores.items()}
        for o, cid in cells_to_lower:
            cs[o][cid] = max(0, cs[o][cid] - 1)
        t = _totals(included, cs, weights, mx)
        r, _ = _rank(included, t, cs, gaps, weights, margin)
        return t, r[0]

    low = [(o, c["id"]) for o in included for c in criteria if detail[o][c["id"]]["confidence"] == "low"]
    conf_tests = []
    if low:
        t, top = lowered(low)
        conf_tests.append({"test": "all low-confidence scores lowered by one", "totals": t, "top": top, "changed": top != base_top})
        for o, cid in sorted(low, key=lambda x: -weights[x[1]])[:3]:
            t, top = lowered([(o, cid)])
            conf_tests.append({"test": "%s / %s lowered by one" % (o, cid), "totals": t, "top": top, "changed": top != base_top})

    scenarios = _scenarios(included, criteria, weights, cscores, rscores if anchored else None, req, scores, gaps, mx, margin, base_top, conf_tests)
    bias = bias_checks(reqs, opts, ev, included, name, cost_summary, rep)
    for o in included:
        for c in criteria:
            dd = detail[o][c["id"]]
            dd["attainment"] = round(cscores[o][c["id"]] / mx, 4)
            dd["contribution"] = round(cscores[o][c["id"]] / mx * c["weight"], 2)
    shares = {}
    for c in criteria:
        if c["weight"] > 0:
            pts = (scores.get("priority_points") or ANCHOR_POINTS) if anchored else PRIORITY
            shares[c["id"]] = largest_remainder({rid: pts[req[rid]["priority"]] for rid in c["requirement_ids"]}, c["weight"])
    out = dict(scores)
    out["bias_checks"] = bias
    out["scoring_model"] = model_of(scores)
    if anchored:
        out["requirement_scores"] = rscores
        out["mapping"] = {"scoring_model": "anchored", "anchors": crit.get("requirement_anchors") or DEFAULT_ANCHORS,
                          "priority_points": scores.get("priority_points") or ANCHOR_POINTS, "cap_unverified": CAP,
                          "tie_margin": margin, "meaningful_gap": margin, "rounding": "none (one decimal on totals)", "scale_factor": factor}
    if cost_summary:
        out["cost_summary"] = cost_summary
    out.update({
        "requirement_shares": shares, "must_gaps": gaps, "scenarios": scenarios["scenarios"], "order_changes": scenarios["order_changes"],
        "lead": scenarios["lead"], "meaningful_gap": margin, "deciding_cells": _deciding_cells(ranking, rscores if anchored else None, criteria, req, scores, crit),
        **({} if anchored else {"mapping": {"ranges": RANGES, "midpoints": MIDPOINTS, "priority_weights": PRIORITY, "cap_unverified": cap,
                                            "tie_margin": margin, "meaningful_gap": margin, "rounding": "half_up", "scale_factor": factor}}),
        "criterion_scores": detail, "totals": totals, "ranking": ranking, "ties": ties,
        "excluded": [{"option_id": o["option_id"], "reason": o["exclusion_reason"] or "not profiled"} for o in excluded],
        "must_summary": must_summary, "evidence_coverage": coverage, "unknown_bounds": unknown_bounds, "could_overtake_leader": overtake, "sensitivity": sens, "confidence_tests": conf_tests, "warnings": rep.warnings,
    })
    if not write:
        return rep, out
    _note_earlier_totals(d, totals)
    with open(os.path.join(d, "scores.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
    if os.path.exists(os.path.join(d, "features.json")):
        render_features(d, cost_summary)
    elif not anchored:  # the older model builds the feature table from its cells
        with open(os.path.join(d, "features.md"), "w", encoding="utf-8", newline="\n") as f:
            f.write(_features_md(reqs, opts, included, excluded, cells, must_summary, cost_summary))
    return rep, out


def _note_earlier_totals(d, totals):
    """Keep the totals of the previous run in status.json so an export can be checked for numbers that went stale."""
    old = _read_json(d, "scores.json", Report())
    status = _read_json(d, "status.json", Report())
    if not (isinstance(old, dict) and isinstance(old.get("totals"), dict) and isinstance(status, dict)):
        return
    gone = sorted({v for v in old["totals"].values() if v not in totals.values()})
    if gone or "earlier_totals" in status:
        status["earlier_totals"] = gone
        _write_status(d, status)


def render_features(d, cost_summary=None):
    """Write eval/features.md from eval/features.json. The scorer never reads either file."""
    feats = _read_json(d, "features.json", Report(), True)
    opts = _read_json(d, "options.json", Report(), True)
    scores = _read_json(d, "scores.json", Report()) or {}
    name = {o["option_id"]: o["name"] for o in opts}
    shown = [o["option_id"] for o in opts if not (o["excluded"] or o["not_profiled"])]
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")
    lines = ["# Feature comparison", "",
             "Generated by `scripts/eval_calc.py features` from `eval/features.json`. Do not edit by hand. "
             "This table describes what each option offers; it has no effect on the scores.", ""]
    cats = []
    for f in feats:
        if f["category"] not in cats:
            cats.append(f["category"])
    for cat in cats:
        lines += ["## " + cat, "", "| ID | Feature | " + " | ".join(esc(name[o]) for o in shown) + " |", "| --- | --- | " + " | ".join("---" for _ in shown) + " |"]
        for f in [x for x in feats if x["category"] == cat]:
            row = []
            for o in shown:
                cell = f["cells"].get(o) or {"status": "missing"}
                txt = cell["status"] + ((" {" + ", ".join(cell["scope_tags"]) + "}") if cell.get("scope_tags") else "") + ((" - " + cell["note"]) if cell.get("note") else "") + ((" [" + ", ".join(cell["evidence_ids"]) + "]") if cell.get("evidence_ids") else "")
                row.append(esc(txt))
            lines.append("| %s | %s | %s |" % (f["id"], esc(f["name"] + (": " + f["description"] if f.get("description") else "")), " | ".join(row)))
        lines.append("")
    cs = cost_summary or scores.get("cost_summary")
    if cs:
        lines += ["## Cost (total cost of ownership over %s months, %s)" % (cs["horizon_months"], cs["currency"]), "",
                  "| Option | Monthly | One-time | Total |", "| --- | --- | --- | --- |"]
        for o in shown:
            c = cs["options"].get(o)
            if c:
                lines.append("| %s | %s | %s | %s |" % (esc(name[o]), format(c["monthly"], ",.2f"), format(c["one_time"], ",.2f"),
                                                          ("quote needed" if not c["tco"] else format(c["tco"], ",.2f") + " + quote needed") if c["incomplete"] else format(c["tco"], ",.2f")))
    with open(os.path.join(d, "features.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")
    return os.path.join(d, "features.md")


def _features_md(reqs, opts, included, excluded, cells, must_summary, cost_summary=None):
    name = {o["option_id"]: o["name"] for o in opts}
    esc = lambda s: str(s).replace("|", "\\|").replace("\n", " ")
    lines = ["# Feature comparison", "",
             "Generated by `scripts/eval_calc.py score` from `eval/scores.json`. Do not edit by hand.", ""]
    cats = []
    for r in reqs:
        if r["category"] not in cats:
            cats.append(r["category"])
    head = "| ID | Requirement | Priority | " + " | ".join(esc(name[o]) for o in included) + " |"
    sep = "| --- | --- | --- | " + " | ".join("---" for _ in included) + " |"
    for cat in cats:
        lines += ["## " + cat, "", head, sep]
        for r in [x for x in reqs if x["category"] == cat]:
            row = []
            for o in included:
                cell = cells[o][r["id"]]
                txt = cell["value"]
                if cell.get("note"):
                    txt += " - " + cell["note"]
                if cell.get("evidence_ids"):
                    txt += " [" + ", ".join(cell["evidence_ids"]) + "]"
                row.append(esc(txt))
            lines.append("| %s | %s | %s | %s |" % (r["id"], esc(r["text"]), r["priority"], " | ".join(row)))
        lines.append("")
    lines += ["## Must-have summary", "", "| Option | " + " | ".join(CELL_VALUES) + " |", "| --- | " + " | ".join("---" for _ in CELL_VALUES) + " |"]
    for o in included:
        lines.append("| %s | %s |" % (esc(name[o]), " | ".join(str(must_summary[o][v]) for v in CELL_VALUES)))
    if cost_summary:
        cur, hz = cost_summary["currency"], cost_summary["horizon_months"]
        lines += ["", "## Cost (total cost of ownership over %s months, %s)" % (hz, cur), "",
                  "| Option | Monthly | One-time | Total | Notes |", "| --- | --- | --- | --- | --- |"]
        for o in included:
            c = cost_summary["options"].get(o)
            if c:
                shaky = [g for g in c["evidence_gaps"] if g not in c.get("assumed", [])]
                note = "; ".join(x for x in ("incomplete: a component has no price" if c["incomplete"] else "",
                                             "assumed: " + ", ".join(c["assumed"]) if c.get("assumed") else "",
                                             "unverified: " + ", ".join(shaky) if shaky and not c["incomplete"] else "") if x)
                total = format(c["tco"], ",.2f")
                if c["incomplete"]:
                    total = "quote needed" if not c["tco"] else total + " + quote needed"
                lines.append("| %s | %s | %s | %s | %s |" % (esc(name[o]), format(c["monthly"], ",.2f"), format(c["one_time"], ",.2f"), total, esc(note)))
    if excluded:
        lines += ["", "## Not compared", ""]
        for o in excluded:
            lines.append("- %s: %s" % (o["name"], o["exclusion_reason"] or "not profiled"))
    return "\n".join(lines) + "\n"


def reconcile(d, other_csv, map_csv, scale_max=5.0):
    """Compare our evaluation with another assessment: both totals, our ratings under their weights, and where they differ.

    other_csv: Criterion, Weight, then one numeric column per option (option id or name). map_csv: Criterion, Requirements (our ids, separated by ;).
    Our rating for one of their criteria is the priority-weighted mean of our requirement scores for the mapped requirements."""
    import csv
    rep = Report()
    reqs = _read_json(d, "requirements.json", rep, True)
    scores = _read_json(d, "scores.json", rep, True)
    opts = _read_json(d, "options.json", rep, True)
    if rep.errors:
        return rep, None
    if model_of(scores) != "anchored" or "requirement_scores" not in scores:
        rep.err("reconcile needs a scored evaluation on the anchored model")
        return rep, None
    names = {o["option_id"]: o["name"] for o in opts}
    with open(other_csv, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    with open(map_csv, encoding="utf-8-sig", newline="") as f:
        mapping = {r["Criterion"].strip(): [x.strip() for x in r["Requirements"].split(";") if x.strip()] for r in csv.DictReader(f)}
    cols = [c for c in rows[0] if c not in ("Criterion", "Weight")]
    col_opt = {}
    for c in cols:
        hit = [oid for oid, n in names.items() if c.strip() in (oid, n, n.split(" (")[0])]
        if hit and hit[0] in scores["requirement_scores"]:
            col_opt[c] = hit[0]
    if not col_opt:
        rep.err("no option column in the other assessment matches a scored option")
        return rep, None
    prio = {r["id"]: r["priority"] for r in reqs}
    pts = scores.get("priority_points") or ANCHOR_POINTS
    weights = {r["Criterion"].strip(): float(r["Weight"]) for r in rows}
    total_w = sum(weights.values()) or 1.0
    out = {"options": {}, "criteria": [], "unmapped": []}
    for r in rows:
        crit = r["Criterion"].strip()
        ids = mapping.get(crit)
        if not ids:
            out["unmapped"].append(crit)
            continue
        bad = [i for i in ids if i not in prio]
        if bad:
            rep.err("mapping for %s names unknown requirement(s): %s" % (crit, ", ".join(bad)))
            continue
        entry = {"criterion": crit, "weight": weights[crit], "requirements": ids, "options": {}}
        for c, oid in col_opt.items():
            rs = scores["requirement_scores"][oid]
            den = sum(pts[prio[i]] for i in ids)
            ours = sum(pts[prio[i]] * rs.get(i, {"score": 0})["score"] for i in ids) / den * scale_max / 5.0
            entry["options"][oid] = {"theirs": float(r[c]), "ours": round(ours, 2), "difference": round(ours - float(r[c]), 2)}
        out["criteria"].append(entry)
    if rep.errors:
        return rep, None
    for c, oid in col_opt.items():
        their = sum(e["weight"] * e["options"][oid]["theirs"] for e in out["criteria"]) / sum(e["weight"] for e in out["criteria"]) / scale_max * 100
        ours = sum(e["weight"] * e["options"][oid]["ours"] for e in out["criteria"]) / sum(e["weight"] for e in out["criteria"]) / scale_max * 100
        out["options"][oid] = {"name": names[oid], "their_total": round(their, 1), "our_ratings_under_their_weights": round(ours, 1), "our_total": scores.get("totals", {}).get(oid)}
    if out["unmapped"]:
        rep.warn("their criteria without a mapping were left out: " + ", ".join(out["unmapped"]))
    return rep, out


def matrix_report(path, scale_max=5.0):
    """Stress-test an external score table: a CSV with Criterion and Weight columns and one numeric column per option."""
    import csv
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    def is_num(v):
        try:
            float(v)
            return True
        except (TypeError, ValueError):
            return False

    if not rows or "Criterion" not in rows[0] or "Weight" not in rows[0]:
        raise ValueError("the CSV needs Criterion and Weight columns")
    options = [c for c in rows[0] if c not in ("Criterion", "Weight") and all(is_num(r.get(c)) for r in rows)]
    if len(options) < 2:
        raise ValueError("the CSV needs at least two numeric option columns")
    weights = [float(r["Weight"]) for r in rows]
    scores = [[float(r[o]) for o in options] for r in rows]
    total = sum(weights)

    def totals(w):
        s = sum(w)
        return {o: round(sum(w[i] * scores[i][j] for i in range(len(w))) / scale_max / s * 100, 1) for j, o in enumerate(options)}

    base = totals(weights)
    ranking = sorted(options, key=lambda o: -base[o])
    leader = ranking[0]
    flips, smallest, tests = [], None, 0
    for i, r in enumerate(rows):
        if not 0 < weights[i] < total:
            continue
        for delta in (5, -5):
            tests += 1
            new = max(0.0, weights[i] + delta)
            k = (total - new) / (total - weights[i])
            t = totals([new if j == i else weights[j] * k for j in range(len(rows))])
            top = max(options, key=lambda o: t[o])
            ordered = sorted(t.values(), reverse=True)
            gap = round(ordered[0] - ordered[1], 1)
            if top != leader:
                flips.append({"criterion": r["Criterion"], "delta": delta, "leader": top})
            if smallest is None or gap < smallest["lead"]:
                smallest = {"lead": gap, "criterion": r["Criterion"], "delta": delta}
    equal = totals([1.0] * len(rows))
    return {"options": options, "totals": base, "ranking": ranking, "single_weight_tests": tests, "leader_changes": flips,
            "smallest_lead": smallest, "equal_weights": equal, "equal_weights_ranking": sorted(options, key=lambda o: -equal[o])}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="eval_calc.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("weights")
    w.add_argument("ids", nargs="+")
    w.add_argument("--apply", metavar="DIR", help="write the weights into DIR/criteria.json (other criteria get weight 0)")
    cm = sub.add_parser("complete")
    cm.add_argument("dir")
    cm.add_argument("step", choices=STEPS)
    cm.add_argument("--slug")
    ch = sub.add_parser("changed")
    ch.add_argument("dir")
    ch.add_argument("what", choices=sorted(STALE_MAP))
    ch.add_argument("--reason", help="one line; required when weights change after eval-compare ran")
    v = sub.add_parser("validate")
    v.add_argument("dir")
    v.add_argument("--before", choices=STEPS)
    s = sub.add_parser("score")
    s.add_argument("dir")
    k = sub.add_parser("cost")
    k.add_argument("dir")
    t = sub.add_parser("status")
    t.add_argument("dir")
    g = sub.add_parser("gaps")
    g.add_argument("dir")
    g.add_argument("--limit", type=int, default=8)
    e = sub.add_parser("add-evidence")
    e.add_argument("dir")
    e.add_argument("--option", required=True)
    e.add_argument("--requirement")
    e.add_argument("--criterion")
    e.add_argument("--finding", required=True)
    e.add_argument("--url", required=True)
    e.add_argument("--confidence", required=True)
    e.add_argument("--kind", required=True)
    e.add_argument("--source-date", default="unknown")
    e.add_argument("--scope", choices=["in_scope", "out_of_scope"], help="out_of_scope marks evidence about a component the gate excludes")
    e.add_argument("--pin", help="release, tag, commit or dated snapshot the source was read at (or latest, with a source date)")
    e.add_argument("--source-class", choices=list(SOURCE_CLASSES))
    sv = sub.add_parser("stale-evidence")
    sv.add_argument("dir")
    sv.add_argument("--fast", default="", help="comma-separated option ids of fast-moving products (3 month limit instead of 12)")
    sv.add_argument("--today", help="YYYY-MM-DD, default today")
    sv.add_argument("--write", action="store_true", help="record the ids in status.json and mark compare and report stale")
    vq = sub.add_parser("verify-queue")
    vq.add_argument("dir")
    vq.add_argument("--limit", type=int, default=15)
    ft = sub.add_parser("features")
    ft.add_argument("dir")
    rc = sub.add_parser("reconcile")
    rc.add_argument("dir")
    rc.add_argument("other")
    rc.add_argument("--map", required=True, help="CSV with Criterion and Requirements (our ids separated by ;)")
    rc.add_argument("--scale-max", type=float, default=5.0)
    mx = sub.add_parser("matrix")
    mx.add_argument("path")
    mx.add_argument("--scale-max", type=float, default=5.0)
    a = ap.parse_args(argv)
    if a.cmd == "weights":
        if a.apply:
            rep, wts = apply_weights(a.apply, a.ids)
            for m in rep.errors:
                print("ERROR: " + m, file=sys.stderr)
            if wts is None:
                return 1
            print(json.dumps(wts, indent=2))
            return 0
        print(json.dumps(rank_sum_weights(a.ids), indent=2))
        return 0
    if a.cmd == "stale-evidence":
        import datetime
        today = datetime.date.fromisoformat(a.today) if a.today else None
        rep, stale = find_stale_evidence(a.dir, today, [x for x in a.fast.split(",") if x], a.write)
        for m in rep.errors:
            print("ERROR: " + m, file=sys.stderr)
        if stale is None:
            return 1
        print(json.dumps({"stale": stale, "count": len(stale)}, indent=2))
        return 0
    if a.cmd in ("complete", "changed"):
        rep, res = complete_step(a.dir, a.step, a.slug) if a.cmd == "complete" else mark_changed(a.dir, a.what, a.reason)
        for m in rep.errors:
            print("ERROR: " + m, file=sys.stderr)
        if res is None:
            return 1
        print(json.dumps(res if a.cmd == "changed" else {"completed_steps": res["completed_steps"], "stale_steps": res["stale_steps"]}, indent=2))
        return 0
    if a.cmd == "status":
        print(json.dumps(status_report(a.dir), indent=2))
        return 0
    if a.cmd == "verify-queue":
        rep, q = verify_queue(a.dir)
        for m in rep.errors:
            print("ERROR: " + m, file=sys.stderr)
        if q is None:
            return 1
        print(json.dumps({"total": len(q), "queue": q[:a.limit]}, indent=2))
        return 0
    if a.cmd == "features":
        rep = validate(a.dir)
        for m in rep.errors:
            print("ERROR: " + m, file=sys.stderr)
        if rep.errors or not os.path.exists(os.path.join(a.dir, "features.json")):
            print("ERROR: no usable eval/features.json", file=sys.stderr)
            return 1
        print("wrote " + render_features(a.dir))
        return 0
    if a.cmd == "reconcile":
        rep, res = reconcile(a.dir, a.other, a.map, a.scale_max)
        for m in rep.errors:
            print("ERROR: " + m, file=sys.stderr)
        for m in rep.warnings:
            print("WARNING: " + m, file=sys.stderr)
        if res is None:
            return 1
        print(json.dumps(res, indent=2))
        return 0
    if a.cmd == "matrix":
        try:
            print(json.dumps(matrix_report(a.path, a.scale_max), indent=2))
        except (OSError, ValueError) as err:
            print("ERROR: %s" % err, file=sys.stderr)
            return 1
        return 0
    if a.cmd == "gaps":
        rep, res = find_gaps(a.dir, a.limit)
        for m in rep.errors:
            print("ERROR: " + m, file=sys.stderr)
        if res is None:
            return 1
        print(json.dumps(res, indent=2))
        return 0
    if a.cmd == "add-evidence":
        rep, eid = add_evidence(a.dir, a.option, a.finding, a.url, a.confidence, a.kind, a.requirement, a.criterion, a.source_date, scope=a.scope, pin=a.pin, source_class=a.source_class)
        for m in rep.errors:
            print("ERROR: " + m, file=sys.stderr)
        if eid:
            print(eid)
        return 1 if rep.errors else 0
    if a.cmd == "validate":
        rep = validate(a.dir, a.before)
    elif a.cmd == "cost":
        rep, out = compute_cost(a.dir)
    else:
        rep, out = compute(a.dir)
    for m in rep.errors:
        print("ERROR: " + m, file=sys.stderr)
    for m in rep.warnings:
        print("WARNING: " + m, file=sys.stderr)
    if rep.errors:
        return 1
    if a.cmd == "validate":
        print("ok")
    elif a.cmd == "cost":
        print(json.dumps({"ranking": out["ranking"], "tco": {o: v["tco"] for o, v in out["options"].items()},
                          "cheapest_by_scenario": out["cheapest_by_scenario"],
                          "incomplete": [o for o, v in out["options"].items() if v["incomplete"]],
                          "unverified_components": {o: [g for g in v["evidence_gaps"] if g not in v["assumed"]] for o, v in out["options"].items() if [g for g in v["evidence_gaps"] if g not in v["assumed"]]},
                          "assumed_components": {o: v["assumed"] for o, v in out["options"].items() if v["assumed"]}}, indent=2))
    else:
        print(json.dumps({"ranking": out["ranking"], "totals": out["totals"], "ties": out["ties"],
                          "sensitivity_changes_top": any(x["changed"] for x in out["sensitivity"]),
                          "confidence_changes_top": any(x["changed"] for x in out["confidence_tests"]),
                          "unknowns_could_change_leader": out["could_overtake_leader"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
