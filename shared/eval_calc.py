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
import json
import math
import os
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
SOURCE_KINDS = {"vendor", "independent", "oss_project_docs"}
CELL_VALUES = ["provided", "vendor-claimed", "partial", "not provided", "unknown"]
GAP_VALUES = {"vendor-claimed", "partial", "not provided", "unknown"}
GATE_STATUS = {"pass", "fail", "unverified", "waived_by_user"}
PRIORITY = {"must": 3, "should": 2, "could": 1}
RANGES = {"not provided": [0, 1], "vendor-claimed": [2, 2], "partial": [2, 3], "provided": [4, 5], "unknown": [1, 1]}
MIDPOINTS = {"not provided": 0.5, "vendor-claimed": 2, "partial": 2.5, "provided": 4.5, "unknown": 1}
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
REQ_KEYS = ["id", "type", "category", "text", "priority", "gate", "verification_note"]
OPT_KEYS = ["option_id", "name", "source_links", "excluded", "exclusion_reason", "not_profiled", "gate_status"]
EV_KEYS = ["evidence_id", "option_id", "finding", "source_url", "source_date", "gathered_on", "confidence", "source_kind"]
STATUS_KEYS = ["current_step", "completed_steps", "stale_steps", "stale_evidence", "evaluation_date", "report_date", "solution_slug"]


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []

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
    for key in ("completed_steps", "stale_steps"):
        if not isinstance(status[key], list) or any(s not in STEPS for s in status[key]):
            rep.err("status.json %s must be a list of step names (%s)" % (key, ", ".join(STEPS)))


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
        if r["type"] not in ("functional", "non-functional"):
            rep.err("%s: type must be functional or non-functional" % where)
        if r["priority"] not in PRIORITY:
            rep.err("%s: priority must be must, should, or could" % where)
        if r.get("evidence_class") not in (None, "feature", "measure"):
            rep.err("%s: evidence_class must be feature or measure" % where)
        if r.get("basis") not in (None, "stated", "assumed"):
            rep.err("%s: basis must be stated or assumed" % where)
        if not isinstance(r["gate"], bool):
            rep.err("%s: gate must be true or false" % where)
        elif r["gate"] and not str(r.get("gate_scope", "")).strip():
            rep.err("%s: gate_scope is required when gate is true" % where)
    if not any("cost" in str(r.get("category", "")).lower() for r in reqs if isinstance(r, dict)):
        rep.err("requirements.json has no cost requirement (a category containing 'cost')")
    return ids


def _check_criteria(c, req_ids, rep):
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
        if not isinstance(cr["anchors"], dict) or any(k not in cr["anchors"] for k in ("0", "3", "5")):
            rep.err("%s: anchors need keys 0, 3 and 5" % where)
        if c.get("cost_mode") == "separate" and "cost" in str(cr["category"]).lower() and cr["weight"] != 0:
            rep.err("%s: cost criterion must have weight 0 when cost_mode is separate" % where)
        for rid in cr["requirement_ids"]:
            if req_ids and rid not in req_ids:
                rep.err("%s: unknown requirement id %s" % (where, rid))
            covered[rid] = covered.get(rid, 0) + 1
    if abs(total - 100) > 1e-9:
        rep.err("criteria weights sum to %s, not 100" % total)
    for rid in sorted(req_ids):
        if covered.get(rid, 0) != 1:
            rep.err("requirement %s is covered by %d criteria (must be exactly 1)" % (rid, covered.get(rid, 0)))
    return crit_ids


def _check_options(opts, gate_ids, rep):
    ids = set()
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
        if "provider" in o and not (isinstance(o["provider"], str) and o["provider"].strip()):
            rep.err("%s: provider must be a non-empty string naming the company or foundation behind the option" % where)
        if "package" in o and not (isinstance(o["package"], str) and o["package"].strip()):
            rep.err("%s: package must be a non-empty string naming the editions and versions evaluated" % where)
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
        if e["source_kind"] not in SOURCE_KINDS:
            rep.err("%s: source_kind must be vendor, independent, or oss_project_docs" % where)
        if e.get("scope") not in (None, "in_scope", "out_of_scope"):
            rep.err("%s: scope must be in_scope or out_of_scope" % where)
        if opt_ids and e["option_id"] not in opt_ids:
            rep.err("%s: unknown option_id %s" % (where, e["option_id"]))
        if e.get("requirement_id") and req_ids and e["requirement_id"] not in req_ids:
            rep.err("%s: unknown requirement_id %s" % (where, e["requirement_id"]))
        if e.get("criterion_id") and crit_ids and e["criterion_id"] not in crit_ids:
            rep.err("%s: unknown criterion_id %s" % (where, e["criterion_id"]))
    return ids


def _check_scores(scores, opt_ids, req_ids, ev_ids, rep):
    if not isinstance(scores, dict) or not isinstance(scores.get("cell_values"), dict):
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
    crit_ids = _check_criteria(crit, req_ids, rep) if crit is not None else set()
    opt_ids = _check_options(opts, gate_ids, rep) if opts is not None else set()
    ev_ids = _check_evidence(ev, opt_ids, req_ids, crit_ids, rep) if ev is not None else set()
    if scores is not None:
        _check_scores(scores, opt_ids, req_ids, ev_ids, rep)
    if isinstance(opts, list) and isinstance(ev, list):
        have = {(e.get("option_id"), e.get("requirement_id")) for e in ev if isinstance(e, dict)}
        for o in opts:
            for gid, st in ((o.get("gate_status") or {}) if isinstance(o, dict) else {}).items():
                if st in ("pass", "fail") and (o.get("option_id"), gid) not in have:
                    rep.warn("gate %s is marked %s for %s without an evidence row for that requirement" % (gid, st, o.get("name", o.get("option_id"))))
    if cost is not None:
        _check_cost(cost, opts if isinstance(opts, list) else None, ev_ids, rep)
    return rep


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


def add_evidence(d, option_id, finding, url, confidence, kind, requirement_id=None, criterion_id=None, source_date="unknown", gathered_on=None, scope=None):
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
        rep.err("kind must be vendor, independent, or oss_project_docs")
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
    if slug:
        status["solution_slug"] = slug
    if step == "define" and not status.get("evaluation_date"):
        status["evaluation_date"] = today
    if step == "report":
        status["report_date"] = today
    _write_status(d, status)
    return rep, status


def mark_changed(d, what):
    """Mark the completed steps that depend on `what` as stale (contract rule 8)."""
    rep = Report()
    if what not in STALE_MAP:
        rep.err("what must be one of %s" % ", ".join(sorted(STALE_MAP)))
        return rep, None
    status = _read_json(d, "status.json", rep, True)
    if rep.errors:
        return rep, None
    done = set(status.get("completed_steps", []))
    stale = set(status.get("stale_steps", [])) | {s for s in STALE_MAP[what] if s in done}
    status["stale_steps"] = [s for s in STEPS if s in stale]
    _write_status(d, status)
    return rep, status["stale_steps"]


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


def _rank(opt_ids, totals, cscores, gaps, weights):
    top_c = max(weights, key=lambda c: weights[c])
    ordered = sorted(opt_ids, key=lambda o: -totals[o])
    groups = []
    for o in ordered:
        if groups and totals[groups[-1][0]] - totals[o] <= TIE_MARGIN + 1e-9:
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
        if r["source_kind"] in ("independent", "oss_project_docs"):
            keys.add(r["source_kind"] + ":" + urlparse(r["source_url"]).netloc.lower())
    return len(keys)


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


def compute(d):
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
        crep, cres = compute_cost(d)
        rep.errors += crep.errors
        if cres:
            cost_summary = {"currency": cres["currency"], "horizon_months": cres["horizon_months"], "cheapest": cres["cheapest"],
                            "options": {o: {k: v[k] for k in ("tco", "monthly", "one_time", "incomplete", "evidence_gaps", "assumed")} for o, v in cres["options"].items()}}
    else:
        rep.warn("no cost.json; cost is not modelled")
    if rep.errors:
        return rep, None
    req = {r["id"]: r for r in reqs}
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
    cells_in = scores["cell_values"]
    overrides = {(x["option_id"], x["criterion_id"]): x for x in scores.get("overrides", [])}
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
    ranking, ties = _rank(included, totals, cscores, gaps, weights)
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
            r2, ties2 = _rank(included, t2, cscores, gaps, w2)
            sens.append({"criterion_id": cid, "delta": delta, "weights": {c: round(v, 2) for c, v in w2.items()},
                         "totals": t2, "top": r2[0], "changed": r2[0] != base_top, "tie": bool(ties2 and r2[0] in ties2[0]["options"])})

    def lowered(cells_to_lower):
        cs = {o: dict(v) for o, v in cscores.items()}
        for o, cid in cells_to_lower:
            cs[o][cid] = max(0, cs[o][cid] - 1)
        t = _totals(included, cs, weights, mx)
        r, _ = _rank(included, t, cs, gaps, weights)
        return t, r[0]

    low = [(o, c["id"]) for o in included for c in criteria if detail[o][c["id"]]["confidence"] == "low"]
    conf_tests = []
    if low:
        t, top = lowered(low)
        conf_tests.append({"test": "all low-confidence scores lowered by one", "totals": t, "top": top, "changed": top != base_top})
        for o, cid in sorted(low, key=lambda x: -weights[x[1]])[:3]:
            t, top = lowered([(o, cid)])
            conf_tests.append({"test": "%s / %s lowered by one" % (o, cid), "totals": t, "top": top, "changed": top != base_top})

    bias = bias_checks(reqs, opts, ev, included, name, cost_summary, rep)
    out = dict(scores)
    out["bias_checks"] = bias
    if cost_summary:
        out["cost_summary"] = cost_summary
    out.update({
        "mapping": {"ranges": RANGES, "midpoints": MIDPOINTS, "priority_weights": PRIORITY, "cap_unverified": cap,
                    "tie_margin": TIE_MARGIN, "rounding": "half_up", "scale_factor": factor},
        "criterion_scores": detail, "totals": totals, "ranking": ranking, "ties": ties,
        "excluded": [{"option_id": o["option_id"], "reason": o["exclusion_reason"] or "not profiled"} for o in excluded],
        "must_summary": must_summary, "evidence_coverage": coverage, "unknown_bounds": unknown_bounds, "could_overtake_leader": overtake, "sensitivity": sens, "confidence_tests": conf_tests, "warnings": rep.warnings,
    })
    with open(os.path.join(d, "scores.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(os.path.join(d, "features.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(_features_md(reqs, opts, included, excluded, cells, must_summary, cost_summary))
    return rep, out


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
    if a.cmd in ("complete", "changed"):
        rep, res = complete_step(a.dir, a.step, a.slug) if a.cmd == "complete" else mark_changed(a.dir, a.what)
        for m in rep.errors:
            print("ERROR: " + m, file=sys.stderr)
        if res is None:
            return 1
        print(json.dumps(res if a.cmd == "changed" else {"completed_steps": res["completed_steps"], "stale_steps": res["stale_steps"]}, indent=2))
        return 0
    if a.cmd == "status":
        print(json.dumps(status_report(a.dir), indent=2))
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
        rep, eid = add_evidence(a.dir, a.option, a.finding, a.url, a.confidence, a.kind, a.requirement, a.criterion, a.source_date, scope=a.scope)
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
