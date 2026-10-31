#!/usr/bin/env python3
"""Export a finished evaluation as HTML, XLSX and PDF. Python 3, standard library only.

Usage: python scripts/export_report.py EVAL_DIR [--out DIR] [--formats html,xlsx,pdf]

Run `eval_calc.py score` first: the export reads the computed eval/scores.json.
The XLSX keeps weights as editable cells and totals as live formulas, so the
ranking can be retuned in a spreadsheet. The PDF is printed from the HTML by a
headless Edge or Chrome; without one, the PDF is skipped and the HTML can be
printed to PDF by hand.
"""
import argparse
import html
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from xml.sax.saxutils import escape as xesc


def _load(d, name, required=True):
    path = os.path.join(d, name)
    if not os.path.exists(path):
        if required:
            raise SystemExit("ERROR: %s is missing; run the eval skills (and eval_calc.py score) first" % name)
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


class Data:
    def __init__(self, d):
        self.reqs = _load(d, "requirements.json")
        self.crit = _load(d, "criteria.json")
        self.opts = _load(d, "options.json")
        self.ev = _load(d, "evidence.json")
        self.scores = _load(d, "scores.json")
        self.cost = _load(d, "cost.json", required=False)
        if "totals" not in self.scores:
            raise SystemExit("ERROR: scores.json has no computed results; run `eval_calc.py score` first")
        self.report = _load(d, "report.md", required=False) or ""
        self.solution = _load(d, "solution.md", required=False) or ""
        self.status = _load(d, "status.json", required=False) or {}
        self.name = {o["option_id"]: o["name"] for o in self.opts}
        self.pkg = {o["option_id"]: o.get("package") for o in self.opts}
        self.ranking = self.scores["ranking"]
        self.criteria = self.crit["criteria"]
        self.mx = self.crit["scale"]["max"]

    def label(self, text):
        """Replace option and criterion ids in a sentence with their names."""
        for o, n in self.name.items():
            text = text.replace(o, n)
        for c in self.criteria:
            text = text.replace(c["id"], c["name"])
        return text

    @property
    def title(self):
        m = re.search(r"^#\s+(.+)$", self.solution, re.M)
        slug = self.status.get("solution_slug", "evaluation")
        return re.sub(r"^Solution:\s*", "", m.group(1)) if m else slug


# ---- HTML ---------------------------------------------------------------

def _inline(s):
    s = html.escape(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)


def _md_table(rows):
    cells = [[c.strip() for c in re.split(r"(?<!\\)\|", r.strip().strip("|"))] for r in rows]
    cells = [r for r in cells if not all(re.fullmatch(r":?-{2,}:?", c) for c in r)]
    out = ['<div class="table-wrap"><table>', "<thead><tr>" + "".join("<th>%s</th>" % _inline(c) for c in cells[0]) + "</tr></thead>", "<tbody>"]
    for r in cells[1:]:
        out.append("<tr>" + "".join("<td>%s</td>" % _inline(c) for c in r) + "</tr>")
    return "\n".join(out + ["</tbody></table></div>"])


def md_to_html(md):
    lines, out, para, i = md.replace("\r\n", "\n").split("\n"), [], [], 0

    def flush():
        if para:
            out.append("<p>%s</p>" % _inline(" ".join(para)))
            para.clear()

    while i < len(lines):
        ln = lines[i]
        m = re.match(r"(#{1,6})\s+(.*)", ln)
        if not ln.strip():
            flush()
            i += 1
        elif m:
            flush()
            n = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (n, _inline(m.group(2)), n))
            i += 1
        elif ln.lstrip().startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append(_md_table(rows))
        elif re.match(r"\s*([-*]|\d+\.)\s+", ln):
            flush()
            tag = "ol" if re.match(r"\s*\d+\.\s+", ln) else "ul"
            items = []
            while i < len(lines) and re.match(r"\s*([-*]|\d+\.)\s+", lines[i]):
                items.append("<li>%s</li>" % _inline(re.sub(r"^\s*([-*]|\d+\.)\s+", "", lines[i])))
                i += 1
            out.append("<%s>%s</%s>" % (tag, "".join(items), tag))
        else:
            para.append(ln.strip())
            i += 1
    flush()
    return "\n".join(out)


CSS = """
:root{--bg:#fff;--fg:#1a2230;--muted:#5b6576;--line:#e1e4ea;--rule:#1a2230;--head:#f3f5f8;--accent:#0d6a73;--accent-soft:#d5ebed;--ok:#16703f;--ok-bg:#e0f1e7;--warn:#8a5a00;--warn-bg:#fbefd0;--bad:#a8261b;--bad-bg:#fbe3e0;--serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;--sans:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;--side:15.5rem;--gutter:clamp(16px,4vw,48px)}
@media (prefers-color-scheme:dark){:root{--bg:#12161c;--fg:#e4e8ee;--muted:#98a2b3;--line:#2a313c;--rule:#e4e8ee;--head:#1a2028;--accent:#5fc0d6;--accent-soft:#1d3a44;--ok:#5ccf92;--ok-bg:#16301f;--warn:#e6b84d;--warn-bg:#352a0f;--bad:#ff8a80;--bad-bg:#3a1b19}}
*{box-sizing:border-box}
html{scroll-padding-top:16px}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 var(--sans);-webkit-text-size-adjust:100%}
h1,h2,h3{font-family:var(--serif);font-weight:600;line-height:1.2;letter-spacing:-.01em}
p,li{max-width:76ch}
a{color:var(--accent)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:2px}
button,input,select{font:inherit;font-size:.85rem;color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:5px 10px}
button{cursor:pointer}button:hover{border-color:var(--accent);color:var(--accent)}

/* page frame: a sticky section index beside the report on wide screens */
.layout{display:grid;grid-template-columns:var(--side) minmax(0,1fr);gap:0 clamp(28px,4vw,56px);max-width:1500px;margin:0 auto;padding:0 var(--gutter)}
.side{position:sticky;top:0;align-self:start;max-height:100vh;overflow-y:auto;padding:44px 0 24px}
.side-title{margin:0 0 10px;font-size:.8rem;color:var(--muted)}
.toc-links{display:flex;flex-direction:column;border-left:1px solid var(--line)}
.toc-links a{display:block;padding:5px 0 5px 14px;margin-left:-1px;border-left:2px solid transparent;color:var(--muted);text-decoration:none;font-size:.88rem;line-height:1.35}
.toc-links a:hover{color:var(--fg)}
.toc-links a[aria-current]{color:var(--accent);border-left-color:var(--accent);font-weight:600}
.toc-tools{display:flex;gap:6px;margin-top:16px}
main{min-width:0;padding:44px 0 96px}

/* header */
h1{font-size:clamp(1.6rem,1.2rem + 1.6vw,2.4rem);margin:0 0 14px;max-width:28ch}
.meta{display:flex;flex-wrap:wrap;gap:6px 28px;margin:0;color:var(--muted);font-size:.88rem}
.meta div{display:flex;gap:.5em}.meta dd{margin:0;color:var(--fg);font-weight:600}

/* ranking summary: the one graphic the page leads with */
.verdict{margin:32px 0 0;padding:24px 0 6px;border-top:2px solid var(--rule)}
.verdict .lead{font:600 1.3rem/1.35 var(--serif);margin:0 0 6px;max-width:52ch}
.verdict .caveat{color:var(--muted);margin:0 0 20px}
ol.ranking{list-style:none;margin:0;padding:0;display:grid;gap:12px}
ol.ranking li{display:grid;grid-template-columns:1.6rem minmax(10rem,19rem) minmax(0,1fr) 3.6rem;gap:4px 14px;align-items:center;max-width:none}
.pos{font:600 1.1rem var(--serif);color:var(--muted);text-align:right}
.nm{font-weight:600;overflow-wrap:anywhere;line-height:1.3}
.bar{position:relative;height:18px;background:var(--head);border-radius:2px;overflow:hidden;background-image:linear-gradient(90deg,transparent calc(50% - .5px),var(--line) 50%,transparent calc(50% + .5px))}
.fill,.reach{position:absolute;top:0;bottom:0;transform-origin:left center;animation:grow .9s cubic-bezier(.2,.7,.2,1) both}
.fill{left:0;background:var(--accent)}
.reach{background:repeating-linear-gradient(135deg,var(--accent-soft) 0 4px,transparent 4px 8px);border-right:2px solid var(--accent);animation-delay:.25s}
@keyframes grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.val{font:600 1.05rem var(--sans);font-variant-numeric:tabular-nums;text-align:right}
.flags{grid-column:3 / 5;display:flex;flex-wrap:wrap;gap:4px 8px;margin-top:-4px}
.flag{font-size:.78rem;color:var(--warn);background:var(--warn-bg);padding:0 .55em;border-radius:3px}
.legend{display:flex;flex-wrap:wrap;gap:4px 20px;margin:16px 0 0;color:var(--muted);font-size:.84rem}
.legend i{display:inline-block;width:22px;height:10px;margin-right:6px;vertical-align:-1px}
.legend .k-fill{background:var(--accent)}.legend .k-reach{background:repeating-linear-gradient(135deg,var(--accent-soft) 0 4px,transparent 4px 8px);border-right:2px solid var(--accent)}
.intro{margin-top:18px}.intro p{color:var(--muted);font-size:.92rem}

/* collapsible sections */
details.sec{border-top:1px solid var(--line);scroll-margin-top:12px}
details.sec:first-of-type{margin-top:28px}
details>summary{display:flex;align-items:baseline;flex-wrap:wrap;gap:2px 14px;cursor:pointer;list-style:none;padding:16px 0 14px}
details>summary::-webkit-details-marker{display:none}
details>summary::before{content:"";flex:none;align-self:center;width:.5em;height:.5em;margin:0 .15em 0 .1em;border-right:2px solid var(--muted);border-bottom:2px solid var(--muted);transform:rotate(-45deg);transition:transform .15s ease}
details[open]>summary::before{transform:rotate(45deg)}
summary h2,summary h3{margin:0}
summary h2{font-size:1.3rem}summary h3{font-size:1.05rem}
summary:hover h2,summary:hover h3{color:var(--accent)}
.hint{margin-left:auto;color:var(--muted);font-size:.84rem;text-align:right}
.sec-body{padding:0 0 28px}
details.sub{border-top:1px solid var(--line)}
details.sub>summary{padding:10px 0}
details.sub[open]{padding-bottom:10px}
.prose p,.prose li{font-family:var(--serif);font-size:1.03rem;line-height:1.65}
.prose h3,.prose h4{margin:1.4rem 0 .3rem}
.sec-body>p,.sec-body>ul{max-width:76ch}
.sec-body h3{font-size:1.05rem;margin:1.6rem 0 .3rem}

/* tables */
.table-wrap{overflow-x:auto;margin:10px 0 18px;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:.88rem}
th,td{padding:8px 14px 8px 0;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
th{font-size:.78rem;font-weight:600;color:var(--muted);border-bottom:2px solid var(--rule);line-height:1.3}
th:last-child,td:last-child{padding-right:0}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}td.num{white-space:nowrap}
tbody tr:last-child td{border-bottom:0}
tbody tr:hover td{background:color-mix(in srgb,var(--head) 70%,transparent)}
code{background:var(--head);padding:1px 5px;border-radius:3px;font-size:.88em}
.feat td{min-width:12rem}.feat td:first-child{min-width:0;white-space:nowrap;color:var(--muted)}.feat td:nth-child(3){min-width:0}
.pkg{display:block;margin-top:2px;color:var(--muted);font-size:.8rem;line-height:1.4;font-weight:400}.cell .note{display:block;margin-top:3px;color:var(--fg);font-size:.84rem;line-height:1.45}
.cell .ev{display:block;margin-top:2px}
#src-table td{font-size:.82rem}#src-table td:nth-child(1),#src-table td:nth-child(5),#src-table td:nth-child(6){white-space:nowrap}#src-table td:nth-child(5) a{overflow-wrap:normal}#src-table td:nth-child(4){min-width:20rem}
td a{overflow-wrap:anywhere}
.provided,.partial,.vendor-claimed,.not-provided,.unknown{display:inline-block;padding:0 .6em;border-radius:999px;font-size:.76rem;font-weight:600;line-height:1.65;white-space:nowrap}
.provided{color:var(--ok);background:var(--ok-bg)}.partial,.vendor-claimed{color:var(--warn);background:var(--warn-bg)}.not-provided,.unknown{color:var(--bad);background:var(--bad-bg)}
.tag{font-size:.78rem;color:var(--muted)}.tag.low{color:var(--bad)}.tag.medium{color:var(--warn)}.tag.high{color:var(--ok)}
p.tag{margin:6px 0}
.heat{display:inline-block;min-width:2.1em;padding:1px 8px;border-radius:3px;text-align:center;font-weight:600;background:color-mix(in srgb,var(--accent) calc(var(--p) * 28%),transparent)}
.filters{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;margin:0 0 6px}
.filters input{flex:1 1 14rem;max-width:26rem}
.filters select{max-width:100%}

/* medium screens: the index becomes a one-line strip pinned to the top */
@media screen and (max-width:1080px){
.layout{display:block}
.side{z-index:5;max-height:none;overflow:visible;padding:0;margin:0 calc(-1 * var(--gutter));background:var(--bg);border-bottom:1px solid var(--line)}
nav.toc{display:flex;align-items:center;gap:10px;padding:0 var(--gutter)}
.side-title{display:none}
.toc-links{flex:1;flex-direction:row;border:0;overflow-x:auto;scrollbar-width:none;white-space:nowrap;gap:2px}
.toc-links::-webkit-scrollbar{display:none}
.toc-links a{padding:12px 8px;margin:0;border-left:0;border-bottom:2px solid transparent}
.toc-links a[aria-current]{border-bottom-color:var(--accent)}
.toc-tools{margin:0;flex:none}
main{padding-top:28px}
html{scroll-padding-top:56px}details.sec{scroll-margin-top:56px}
}
@media screen and (max-width:680px){
body{font-size:14.5px}
.toc-tools button{padding:4px 8px;font-size:.78rem}
ol.ranking li{grid-template-columns:1.4rem minmax(0,1fr) 3.2rem}
.bar{grid-column:2 / 4;grid-row:2}.flags{grid-column:2 / 4;grid-row:3;margin-top:0}
.hint{margin-left:1.35em;flex-basis:100%;text-align:left}
}
/* tablets and phones: rows become stacked cards labelled by their column */
@media screen and (max-width:860px){
.table-wrap{overflow:visible}
.table-wrap table,.table-wrap tbody,.table-wrap tr,.table-wrap td{display:block;width:100%}
.table-wrap thead{display:none}
.table-wrap tr{padding:10px 0;border-bottom:1px solid var(--line)}
.table-wrap td{display:grid;grid-template-columns:minmax(5.5rem,34%) minmax(0,1fr);gap:10px;border:0;padding:3px 0;min-width:0!important;white-space:normal!important;text-align:left}
.table-wrap td::before{content:attr(data-label);color:var(--muted);font-size:.76rem;line-height:1.6}
.table-wrap td:empty{display:none}
tbody tr:hover td{background:none}
}
@media (prefers-reduced-motion:reduce){.fill,.reach{animation:none}details>summary::before{transition:none}}
@page{size:A4 landscape;margin:12mm}
@media print{:root{--bg:#fff;--fg:#000;--muted:#444;--line:#bbb;--rule:#000;--head:#eee;--accent:#0b4a58;--accent-soft:#cfe3e8}body{font-size:12px}.layout{display:block;padding:0;max-width:none}.side,.filters{display:none}main{padding:0}details>summary::before{display:none}summary{break-after:avoid}.table-wrap{overflow:visible}table{break-inside:auto}tr{break-inside:avoid}tbody tr:hover td{background:none}.fill,.reach{animation:none!important}}
"""


def _table(head, rows, num_cols=(), cls=""):
    h = "".join('<th%s>%s</th>' % (' class="num"' if j in num_cols else "", c[0] if isinstance(c, tuple) else html.escape(str(c))) for j, c in enumerate(head))
    body = []
    for r in rows:
        tds = []
        for j, c in enumerate(r):
            raw = isinstance(c, tuple)
            txt = c[0] if raw else html.escape(str(c))
            tds.append('<td%s>%s</td>' % (' class="num"' if j in num_cols else "", txt))
        body.append("<tr>%s</tr>" % "".join(tds))
    return '<div class="table-wrap"><table%s><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (' class="%s"' % cls if cls else "", h, "".join(body))


def _opt_th(D, o):
    """Column header for an option: the short name, the full name on hover."""
    full = D.name[o]
    return ('<span title="%s">%s</span>' % (html.escape(full), html.escape(full.split(" (")[0])),)


def _slug(v):
    return v.replace(" ", "-")


def _money(v):
    return format(v, ",.2f")


def _cost_html(D):
    res = (D.cost or {}).get("results")
    if not res:
        return []
    inc = [o for o in D.ranking if o in res["options"]]
    cur, hz = res["currency"], res["horizon_months"]
    out = ["<h2>Cost: total cost of ownership</h2>", "<p>Over %s months, in %s. Prices come from the sources listed below; components marked unverified rest on weak evidence, and components marked assumed are placeholders, not published prices.</p>" % (hz, html.escape(cur))]
    out.append(_table(["Assumption", "Value", "Unit", "Scales in scenarios"],
                      [[a["name"], "{:,}".format(a["value"]), a["unit"], "yes" if a.get("scales") else "no"] for a in D.cost["assumptions"]], num_cols=(1,)))
    rows = []
    for o in sorted(inc, key=lambda x: res["ranking"].index(x)):
        r = res["options"][o]
        shaky = [g for g in r["evidence_gaps"] if g not in r.get("assumed", [])]
        note = "; ".join(x for x in ("incomplete: a component has no price" if r["incomplete"] else "", "assumed: " + ", ".join(r["assumed"]) if r.get("assumed") else "",
                                     "unverified: " + ", ".join(shaky) if shaky and not r["incomplete"] else "") if x)
        total = _money(r["tco"]) if not r["incomplete"] else ("quote needed" if not r["tco"] else _money(r["tco"]) + " + quote needed")
        rows.append([D.name[o], _money(r["monthly"]), _money(r["one_time"]), total, "%.2fx" % r["index_vs_cheapest"] if r["index_vs_cheapest"] else "n/a", note])
    out.append(_table(["Option", "Monthly", "One-time", "Total over horizon", "Vs cheapest", "Notes"], rows, num_cols=(1, 2, 3, 4)))
    if res["scenarios"]:
        rows = [[sc] + [_money(res["options"][o]["scenarios"][sc]) if not res["options"][o]["incomplete"] else "quote needed" for o in inc]
                + [D.name[res["cheapest_by_scenario"][sc]] if res["cheapest_by_scenario"][sc] else "n/a (quotes needed)"] for sc in res["scenarios"]]
        out += ["<h3>Volume scenarios</h3>", _table(["Scenario"] + [_opt_th(D, o) for o in inc] + ["Cheapest"], rows, num_cols=tuple(range(1, 1 + len(inc))))]
    rows = [[D.name[o], c["name"], _money(c["monthly"]), _money(c["one_time"]), "assumed" if c["id"] in res["options"][o].get("assumed", []) else "unverified" if c["id"] in res["options"][o]["evidence_gaps"] else ""]
            for o in inc for c in res["options"][o]["components"]]
    out += ["<h3>Components</h3>", _table(["Option", "Component", "Monthly", "One-time", "Evidence"], rows, num_cols=(2, 3))]
    return out


def _bias_html(D):
    b = D.scores.get("bias_checks")
    if not b:
        return []
    items = []
    pc = b.get("provider_concentration")
    if pc and pc.get("counts"):
        items.append("Candidate providers: " + ", ".join("%s %d" % (p, n) for p, n in pc["counts"].items()) + " (largest share %d%%)." % round(pc["largest_share"] * 100))
    elif pc:
        items.append("Candidate providers were not recorded, so concentration could not be checked.")
    if b.get("assumed_requirements"):
        items.append("Requirements based on an assumption, not a user statement: " + "; ".join("%s%s" % (a["id"], " (gate)" if a["gate"] else "") for a in b["assumed_requirements"]) + ".")
    else:
        items.append("No requirement is marked as an assumption.")
    mix = b.get("source_mix") or {}
    if mix:
        items.append("Findings by source: " + "; ".join("%s: %d vendor, %d independent or open source" % (D.name[o], v["vendor"], v["independent_or_open_source"]) for o, v in mix.items()) + ".")
    cc = b.get("cost_comparable")
    if cc:
        items.append("Cost compares %d of %d options; the others have no published price." % (cc["complete"], cc["total"]))
    return ["<h2>Bias and assumption checks</h2>", "<ul>%s</ul>" % "".join("<li>%s</li>" % html.escape(i) for i in items)]


def _verdict_html(D):
    inc = D.ranking
    if not inc:
        return []
    tot, ub = D.scores["totals"], D.scores.get("unknown_bounds", {})
    tie_opts = {o for t in D.scores["ties"] for o in t["options"]}
    over = set(D.scores.get("could_overtake_leader") or [])
    lead = html.escape(D.name[inc[0]])
    if len(inc) > 1:
        gap = tot[inc[0]] - tot[inc[1]]
        line = "%s scores %.1f of 100, %.1f ahead of %s." % (lead, tot[inc[0]], gap, html.escape(D.name[inc[1]]))
    else:
        line = "%s scores %.1f of 100." % (lead, tot[inc[0]])
    if over or inc[0] in tie_opts:
        why = []
        if inc[0] in tie_opts:
            why.append("the lead is inside the near-tie margin")
        if over:
            why.append("%d option%s could overtake it if the unknown requirements were provided" % (len(over), "" if len(over) == 1 else "s"))
        caveat = "The ranking is not settled: " + " and ".join(why) + "."
    else:
        caveat = "No unknown requirement is large enough to change the leader."
    rows = []
    for i, o in enumerate(inc, 1):
        t = tot[o]
        hi = max(t, ub.get(o, {}).get("if_unknowns_provided", t))
        flags = []
        if o in tie_opts:
            flags.append("near-tie")
        if o in over:
            flags.append("could overtake the leader")
        label = "%s: %.1f of 100%s" % (D.name[o], t, ", up to %.1f if unknowns are provided" % hi if hi > t else "")
        rows.append('<li><span class="pos">%d</span><span class="nm">%s</span>'
                    '<span class="bar" role="img" aria-label="%s"><i class="fill" style="width:%.1f%%"></i><i class="reach" style="left:%.1f%%;width:%.1f%%"></i></span>'
                    '<span class="val">%.1f</span>%s</li>'
                    % (i, html.escape(D.name[o]), html.escape(label), t, t, hi - t, t,
                       '<span class="flags">%s</span>' % "".join('<span class="flag">%s</span>' % f for f in flags) if flags else ""))
    return ['<section class="verdict" aria-label="Ranking summary"><p class="lead">%s</p><p class="caveat">%s</p><ol class="ranking">%s</ol>' % (line, html.escape(caveat), "".join(rows))
            + '<p class="legend"><span><i class="k-fill"></i>Score as researched</span><span><i class="k-reach"></i>Best case if every unknown requirement is provided</span></p></section>']


def _md_sections(md):
    """Split report.md into (title, markdown) pairs at its level-2 headings."""
    body = re.sub(r"^#\s+.*\n", "", md.strip() + "\n", count=1)
    secs, title, buf = [], "Recommendation and notes", []
    for ln in body.split("\n"):
        m = re.match(r"##\s+(.+)", ln)
        if m:
            if "\n".join(buf).strip():
                secs.append((title, "\n".join(buf).strip()))
            title, buf = m.group(1).strip(), []
        else:
            buf.append(ln)
    if "\n".join(buf).strip():
        secs.append((title, "\n".join(buf).strip()))
    return secs


# report.md headings that cover a computed section, matched on their start
_ALIAS = [("decision table", "decision"), ("criteria", "criteria"), ("bias", "bias"), ("weighted score", "matrix"), ("feature", "features"),
          ("cost", "cost"), ("sensitivity", "sensitivity"), ("excluded", "excluded"), ("sources", "sources")]
# computed tables replace the report's own copies of them; the report's prose is kept
_COMPUTED_TABLES = {"criteria", "matrix", "features", "cost", "sensitivity", "excluded", "sources"}

SCRIPT = """
(function(){
  var all=function(){return document.querySelectorAll('details');};
  function reveal(id){var el=document.getElementById(id);for(var d=el;d;d=d.parentElement){if(d.tagName==='DETAILS')d.open=true;}if(el)el.scrollIntoView();}
  document.querySelectorAll('nav.toc a').forEach(function(a){a.addEventListener('click',function(e){e.preventDefault();reveal(a.hash.slice(1));history.replaceState(null,'',a.hash);});});
  document.querySelectorAll('[data-all]').forEach(function(b){b.addEventListener('click',function(){var open=b.dataset.all==='open';all().forEach(function(d){d.open=open;});});});
  if(location.hash.length>1&&document.getElementById(location.hash.slice(1)))reveal(location.hash.slice(1));
  var q=document.getElementById('src-q'),sel=document.getElementById('src-opt'),rows=document.querySelectorAll('#src-table tbody tr'),n=document.getElementById('src-n');
  function filter(){var t=(q.value||'').toLowerCase(),o=sel.value,k=0;rows.forEach(function(r){var show=(!o||r.dataset.opt===o)&&r.textContent.toLowerCase().indexOf(t)>=0;r.hidden=!show;if(show)k++;});n.textContent=k+' of '+rows.length+' shown';}
  if(q){q.addEventListener('input',filter);sel.addEventListener('change',filter);filter();}
  // label each cell with its column, for the stacked layout on phones
  document.querySelectorAll('table').forEach(function(t){var hs=[].map.call(t.querySelectorAll('thead th'),function(h){return h.textContent.trim();});t.querySelectorAll('tbody tr').forEach(function(r){[].forEach.call(r.children,function(c,i){if(hs[i])c.setAttribute('data-label',hs[i]);});});});
  // mark the section in view in the index
  var links={},strip=document.querySelector('.toc-links');document.querySelectorAll('nav.toc a').forEach(function(a){links[a.hash.slice(1)]=a;});
  if('IntersectionObserver' in window){var io=new IntersectionObserver(function(es){es.forEach(function(e){if(!e.isIntersecting)return;var a=links[e.target.id];if(!a)return;Object.keys(links).forEach(function(k){links[k].removeAttribute('aria-current');});a.setAttribute('aria-current','true');if(strip.scrollWidth>strip.clientWidth)strip.scrollLeft=a.offsetLeft-strip.offsetLeft-24;});},{rootMargin:'-15% 0px -75% 0px'});document.querySelectorAll('details.sec').forEach(function(d){io.observe(d);});}
})();
"""


def build_html(D, expand=False):
    inc = D.ranking
    cs = D.scores["criterion_scores"]
    tie_opts = {o for t in D.scores["ties"] for o in t["options"]}
    title = D.title[:1].upper() + D.title[1:]
    head = ["<h1>%s</h1>" % html.escape(title)]
    meta = [("Evaluation date", D.status.get("evaluation_date", "n/a"))]
    if D.status.get("report_date"):
        meta.append(("Report date", D.status["report_date"]))
    meta += [("Scale", "0 to %s" % D.mx), ("Cost mode", D.crit["cost_mode"])]
    head.append('<dl class="meta">%s</dl>' % "".join("<div><dt>%s</dt><dd>%s</dd></div>" % (html.escape(str(k)), html.escape(str(v))) for k, v in meta))

    gen = {}  # key -> (title, hint, html parts)
    rows = []
    for i, o in enumerate(inc, 1):
        low = sum(1 for c in D.criteria if c["weight"] > 0 and cs[o][c["id"]]["confidence"] == "low")
        gaps = D.scores["must_summary"][o]
        gap_n = sum(v for k, v in gaps.items() if k != "provided")
        ub = D.scores.get("unknown_bounds", {}).get(o)
        rows.append([i, ('<strong>%s</strong>%s%s' % (html.escape(D.name[o]), " (near-tie)" if o in tie_opts else "", '<span class="note pkg">%s</span>' % html.escape(D.pkg[o]) if D.pkg.get(o) else ""),), "%.1f" % D.scores["totals"][o], low, gap_n]
                    + (["%d" % ub["unknown_cells"], "%.1f" % ub["if_unknowns_provided"]] if ub else []))
    cols = ["Rank", "Option", "Weighted score (of 100)", "Low-confidence criteria", "Must-have gaps"] + (["Unknown requirements", "Best case if unknowns are provided"] if D.scores.get("unknown_bounds") else [])
    dec = [_table(cols, rows, num_cols=(0, 2, 3, 4, 5, 6))]
    over = D.scores.get("could_overtake_leader") or []
    if over:
        dec.append('<p class="tag">The ranking is not decided: %s could overtake %s if the requirements still marked unknown turned out to be provided. Research those first.</p>'
                   % (html.escape(", ".join(D.name[o] for o in over)), html.escape(D.name[D.ranking[0]])))
    for t in D.scores["ties"]:
        dec.append('<p class="tag">Near-tie between %s; broken by %s.</p>' % (html.escape(", ".join(D.name[o] for o in t["options"])), html.escape(t["tie_break"])))
    gen["decision"] = ("Decision table", "%d options ranked" % len(inc), dec)

    gen["criteria"] = ("Criteria and weights", "%d criteria" % len(D.criteria), [_table(
        ["Criterion", "Weight", "Requirements"], [[c["name"], c["weight"], ", ".join(c["requirement_ids"])] for c in D.criteria], num_cols=(1,))])

    bias = _bias_html(D)
    if bias:
        gen["bias"] = ("Bias and assumption checks", "", bias[1:])

    rows = []
    for c in D.criteria:
        row = [c["name"], c["weight"]]
        for o in inc:
            d = cs[o][c["id"]]
            mark = "†" if d["capped"] else ""
            row.append(('<span class="heat" style="--p:%.2f">%s%s</span> <span class="tag %s">%s</span>' % (d["score"] / max(D.mx, 1), d["score"], mark, d["confidence"], d["confidence"]),))
        rows.append(row)
    rows.append([("<strong>Weighted total</strong>",), ("<strong>100</strong>",)] + [("<strong>%.1f</strong>" % D.scores["totals"][o],) for o in inc])
    gen["matrix"] = ("Weighted score matrix", "%d criteria, %d options" % (len(D.criteria), len(inc)), [
        _table(["Criterion", "Weight"] + [_opt_th(D, o) for o in inc], rows, num_cols=tuple(range(1, 2 + len(inc)))),
        '<p class="tag">† score capped because the evidence is unverified. Confidence: high = two sources, medium = one, low = none. Independent sources count, and the vendor&rsquo;s official documentation counts once for what a product provides.</p>'])

    cats = []
    for r in D.reqs:
        if r["category"] not in cats:
            cats.append(r["category"])
    feat = []
    for cat in cats:
        reqs = [x for x in D.reqs if x["category"] == cat]
        rows = []
        for r in reqs:
            row = [r["id"], r["text"], r["priority"]]
            for o in inc:
                cell = D.scores["cell_values"][o].get(r["id"], {"value": "unknown"})
                txt = '<div class="cell"><span class="%s">%s</span>' % (_slug(cell["value"]), html.escape(cell["value"]))
                if cell.get("note"):
                    txt += '<span class="note">%s</span>' % html.escape(cell["note"])
                if cell.get("evidence_ids"):
                    txt += '<span class="ev tag">%s</span>' % html.escape(", ".join(cell["evidence_ids"]))
                row.append((txt + "</div>",))
            rows.append(row)
        got = ", ".join("%s %d/%d" % (html.escape(D.name[o].split(" (")[0]), sum(1 for r in reqs if D.scores["cell_values"][o].get(r["id"], {}).get("value") == "provided"), len(reqs)) for o in inc)
        feat.append('<details class="sub"%s><summary><h3>%s</h3><span class="hint">provided: %s</span></summary>%s</details>'
                    % (" open" if expand else "", html.escape(cat), got, _table(["ID", "Requirement", "Priority"] + [_opt_th(D, o) for o in inc], rows, cls="feat")))
    gen["features"] = ("Feature-by-feature comparison", "%d requirements in %d groups" % (len(D.reqs), len(cats)), feat)

    cost = _cost_html(D)
    if cost:
        res = D.cost["results"]
        gen["cost"] = ("Cost: total cost of ownership", "%s over %s months" % (html.escape(res["currency"]), res["horizon_months"]), cost[1:])

    sens = D.scores["sensitivity"]
    rows = [[D.label(x["criterion_id"]), "%+d" % x["delta"], D.name[x["top"]].split(" (")[0], "yes" if x["changed"] else "no"] + ["%.1f" % x["totals"][o] for o in inc] for x in sens]
    flips = sum(1 for x in sens if x["changed"])
    part = ["<p>Each of the highest-weight criteria moved by 5 points, other weights rescaled.</p>",
            _table(["Criterion", "Change", "Top option", "Top changed"] + [_opt_th(D, o) for o in inc], rows, num_cols=tuple(range(4, 4 + len(inc))))]
    rows = [[D.label(t["test"]), D.name[t["top"]], "yes" if t["changed"] else "no"] for t in D.scores["confidence_tests"]]
    if rows:
        part += ["<h3>Confidence tests</h3>", _table(["Test", "Top option", "Top changed"], rows)]
    gen["sensitivity"] = ("Sensitivity", "top option changes in %d of %d tests" % (flips, len(sens)) if flips else "top option holds in all %d tests" % len(sens), part)

    if D.scores["excluded"]:
        gen["excluded"] = ("Excluded options", "%d options" % len(D.scores["excluded"]),
                           [_table(["Option", "Reason"], [[D.name[x["option_id"]], x["reason"]] for x in D.scores["excluded"]])])

    body = []
    for e in D.ev:
        url = html.escape(e["source_url"])
        cells = [html.escape(str(c)) for c in (e["evidence_id"], D.name.get(e["option_id"], e["option_id"]), e.get("requirement_id") or e.get("criterion_id") or "", e["finding"])]
        site = re.sub(r"^https?://(www\.)?", "", e["source_url"]).split("/")[0] or e["source_url"]
        cells.append('<a href="%s" title="%s">%s</a>' % (url, url, html.escape(site)))
        cells += [html.escape(str(c)) for c in (e["source_date"], e["confidence"], e["source_kind"])]
        body.append('<tr data-opt="%s">%s</tr>' % (html.escape(e["option_id"]), "".join("<td>%s</td>" % c for c in cells)))
    opts = sorted({e["option_id"] for e in D.ev}, key=lambda o: D.name.get(o, o))
    tools = ('<div class="filters"><input id="src-q" type="search" placeholder="Filter findings" aria-label="Filter findings">'
             '<select id="src-opt" aria-label="Option"><option value="">All options</option>%s</select><span id="src-n" class="tag" aria-live="polite"></span></div>'
             % "".join('<option value="%s">%s</option>' % (html.escape(o), html.escape(D.name.get(o, o))) for o in opts))
    gen["sources"] = ("Sources", "%d findings" % len(D.ev), [tools, '<div class="table-wrap"><table id="src-table"><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>'
                                                           % ("".join("<th>%s</th>" % h for h in ("ID", "Option", "Requirement", "Finding", "Source", "Source date", "Confidence", "Kind")), "".join(body))])

    # merge report.md sections with the computed sections they cover; the report's order wins
    order = ["decision", "criteria", "bias", "matrix", "features", "cost", "sensitivity", "excluded", "sources"]
    sections, used, intro = [], set(), []
    md_secs = _md_sections(D.report) if D.report.strip() else []
    if len(md_secs) > 1 and md_secs[0][0] == "Recommendation and notes":  # untitled opening text reads as an intro
        intro = ['<div class="prose intro">%s</div>' % md_to_html(md_secs.pop(0)[1])]
    for t, md in md_secs:
        key = next((k for p, k in _ALIAS if t.lower().startswith(p)), None)
        if key not in gen or key in used:
            sections.append((t, "", ['<div class="prose">%s</div>' % md_to_html(md)]))
            continue
        used.add(key)
        if key in _COMPUTED_TABLES:
            md = "\n".join(ln for ln in md.split("\n") if not ln.lstrip().startswith("|"))
        prose = ['<div class="prose">%s</div>' % md_to_html(md)] if md.strip() else []
        gt, hint, part = gen[key]
        if key in ("decision", "bias") and prose:
            part = ['<details class="sub"%s><summary><h3>%s</h3></summary>%s</details>' % (" open" if expand else "", "Scores, gaps and best case" if key == "decision" else "Computed checks", "".join(part))]
        sections.append((t, hint, prose + part))
    for key in order:
        if key in gen and key not in used:
            pos = len(sections)
            if key == "decision":  # right after the recommendation when the report has no decision table
                pos = min(1, len(sections))
            sections.insert(pos, gen[key])

    nav, out = [], []
    for i, (t, hint, part) in enumerate(sections):
        sid = re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-") or "section-%d" % i
        is_open = expand or i == 0 or t.lower().startswith("decision")
        nav.append('<a href="#%s">%s</a>' % (sid, html.escape(t)))
        out.append('<details class="sec" id="%s"%s><summary><h2>%s</h2>%s</summary><div class="sec-body">%s</div></details>'
                   % (sid, " open" if is_open else "", html.escape(t), '<span class="hint">%s</span>' % hint if hint else "", "\n".join(part)))
    toc = ('<aside class="side"><nav class="toc" aria-label="Report sections"><p class="side-title">In this report</p><div class="toc-links">%s</div><div class="toc-tools">'
           '<button type="button" data-all="open">Expand all</button><button type="button" data-all="close">Collapse all</button></div></nav></aside>' % "".join(nav))
    if intro and re.match(r"\s*<div[^>]*><p>\s*Evaluation date", intro[0]):  # the opening line already states the provenance
        head = [h for h in head if not h.startswith("<dl")]
    page = ['<div class="layout">', toc, "<main>", "<header>"] + head + ["</header>"] + _verdict_html(D) + intro + out + ["</main>", "</div>"]
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            "<title>%s</title><style>%s</style></head><body>%s<script>%s</script></body></html>\n"
            % (html.escape("Evaluation report: " + D.title), CSS, "\n".join(page), SCRIPT))


def _col(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class C:
    def __init__(self, v, s=0, f=None):
        self.v, self.s, self.f = v, s, f


def _cell(ref, c):
    if not isinstance(c, C):
        c = C(c)
    if c.f is not None:
        return '<c r="%s" s="%d"><f>%s</f><v>%s</v></c>' % (ref, c.s, xesc(c.f), c.v)
    if isinstance(c.v, bool) or c.v is None or c.v == "":
        return '<c r="%s" s="%d"/>' % (ref, c.s)
    if isinstance(c.v, (int, float)):
        return '<c r="%s" s="%d"><v>%s</v></c>' % (ref, c.s, c.v)
    return '<c r="%s" s="%d" t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, c.s, xesc(str(c.v)))


def _sheet(rows, widths):
    cols = "".join('<col min="%d" max="%d" width="%s" customWidth="1"/>' % (i, i, w) for i, w in enumerate(widths, 1))
    body = "".join('<row r="%d">%s</row>' % (r, "".join(_cell("%s%d" % (_col(c), r), v) for c, v in enumerate(row, 1))) for r, row in enumerate(rows, 1))
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
            "<cols>%s</cols><sheetData>%s</sheetData></worksheet>" % (cols, body))


STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<numFmts count="1"><numFmt numFmtId="164" formatCode="0.0"/></numFmts>'
    '<fonts count="3"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font>'
    '<font><sz val="11"/><color rgb="FF0000FF"/><name val="Calibri"/></font></fonts>'
    '<fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFE7E6E6"/><bgColor indexed="64"/></patternFill></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/><bgColor indexed="64"/></patternFill></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="6">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment wrapText="1" vertical="top"/></xf>'
    '<xf numFmtId="0" fontId="2" fillId="3" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
    '<xf numFmtId="164" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles><dxfs count="0"/></styleSheet>'
)
H, WRAP, INPUT, BOLDNUM, NUM = 1, 2, 3, 4, 5


def build_sheets(D):
    inc, cs, k = D.ranking, D.scores["criterion_scores"], len(D.criteria)
    # Scores sheet: editable weights and live totals
    srow = [[C("Criterion", H), C("Weight (editable)", H)] + [C(D.name[o], H) for o in inc]]
    for c in D.criteria:
        srow.append([C(c["name"], WRAP), C(c["weight"], INPUT)] + [C(cs[o][c["id"]]["score"]) for o in inc])
    srow.append([C("Weights sum (must be 100)", H), C(sum(c["weight"] for c in D.criteria), BOLDNUM, "SUM(B2:B%d)" % (k + 1))] + [C("") for _ in inc])
    tot_row = k + 3
    max_row = k + 4
    srow.append([C("Weighted total (of 100)", H), C("")] + [
        C(D.scores["totals"][o], BOLDNUM, "SUMPRODUCT($B$2:$B$%d,%s2:%s%d)/$B$%d" % (k + 1, _col(3 + i), _col(3 + i), k + 1, max_row)) for i, o in enumerate(inc)])
    srow.append([C("Scale maximum", H), C(D.mx)] + [C("") for _ in inc])
    scores = (srow, [34, 18] + [20] * len(inc))

    # Ranking sheet
    n = len(inc)
    ubs = D.scores.get("unknown_bounds") or {}
    rrow = [[C(h, H) for h in ("Rank (live)", "Option", "Weighted score", "Low-confidence criteria", "Must-have gaps") + (("Unknown requirements", "Best case if unknowns are provided") if ubs else ())]]
    for i, o in enumerate(inc):
        low = sum(1 for c in D.criteria if c["weight"] > 0 and cs[o][c["id"]]["confidence"] == "low")
        gap = sum(v for kk, v in D.scores["must_summary"][o].items() if kk != "provided")
        rrow.append([C(i + 1, 0, "RANK(C%d,$C$2:$C$%d)" % (i + 2, n + 1)), C(D.name[o], WRAP),
                     C(D.scores["totals"][o], NUM, "Scores!%s%d" % (_col(3 + i), tot_row)), C(low), C(gap)]
                    + ([C(ubs[o]["unknown_cells"]), C(ubs[o]["if_unknowns_provided"], NUM)] if ubs else []))
    if D.scores["excluded"]:
        rrow.append([C("")])
        rrow.append([C("Excluded", H), C("Reason", H)])
        for x in D.scores["excluded"]:
            rrow.append([C(""), C(D.name[x["option_id"]], WRAP), C(x["reason"], WRAP)])
    ranking = (rrow, [14, 28, 18, 24, 18, 22, 28])

    # Features sheet
    frow = [[C(h, H) for h in ["ID", "Category", "Requirement", "Priority"] + [D.name[o] for o in inc]]]
    for r in D.reqs:
        row = [C(r["id"]), C(r["category"], WRAP), C(r["text"], WRAP), C(r["priority"])]
        for o in inc:
            cell = D.scores["cell_values"][o].get(r["id"], {"value": "unknown"})
            txt = cell["value"] + (" - " + cell["note"] if cell.get("note") else "") + (" [" + ", ".join(cell["evidence_ids"]) + "]" if cell.get("evidence_ids") else "")
            row.append(C(txt, WRAP))
        frow.append(row)
    features = (frow, [8, 16, 44, 10] + [34] * len(inc))

    # Cost sheet: horizon is editable, totals are live
    cost = None
    res = (D.cost or {}).get("results")
    if res:
        cinc = [o for o in D.ranking if o in res["options"]]
        n2 = len(cinc)
        hrow = n2 + 3
        crow = [[C(h, H) for h in ("Option", "Monthly", "One-time", "Total over horizon", "Vs cheapest")]]
        for i, o in enumerate(cinc):
            r = res["options"][o]
            total = C("quote needed" if not r["tco"] else r["tco"], WRAP if not r["tco"] else BOLDNUM) if r["incomplete"] else C(r["tco"], BOLDNUM, "C%d+B%d*$B$%d" % (i + 2, i + 2, hrow))
            crow.append([C(D.name[o], WRAP), C(r["monthly"], NUM), C(r["one_time"], NUM), total, C(r["index_vs_cheapest"], NUM)])
        crow.append([C("")])
        crow.append([C("Horizon (months, editable)", H), C(res["horizon_months"], INPUT)])
        if res["scenarios"]:
            crow.append([C("")])
            crow.append([C("Scenario (total over horizon)", H)] + [C(D.name[o], H) for o in cinc] + [C("Cheapest", H)])
            for sc in res["scenarios"]:
                crow.append([C(sc, WRAP)] + [C("quote needed" if res["options"][o]["incomplete"] else res["options"][o]["scenarios"][sc], NUM) for o in cinc]
                            + [C(D.name[res["cheapest_by_scenario"][sc]] if res["cheapest_by_scenario"][sc] else "n/a (quotes needed)")])
        crow.append([C("")])
        crow.append([C("Currency: " + res["currency"], WRAP)])
        for o in cinc:
            gaps = res["options"][o]["evidence_gaps"]
            if gaps or res["options"][o]["incomplete"]:
                crow.append([C("%s: unverified or unpriced components: %s" % (D.name[o], ", ".join(gaps)), WRAP)])
        cost = (crow, [34, 18, 18, 22, 14])

    # Evidence sheet
    keys = ["evidence_id", "option_id", "requirement_id", "criterion_id", "finding", "source_url", "source_date", "gathered_on", "confidence", "source_kind"]
    erow = [[C(h, H) for h in keys]]
    for e in D.ev:
        erow.append([C(D.name.get(e[kk], e[kk]) if kk == "option_id" else e.get(kk, ""), WRAP) for kk in keys])
    evidence = (erow, [10, 16, 14, 14, 50, 44, 12, 12, 16, 16])

    # Sensitivity sheet
    hdr = ["Test", "Change", "Top option", "Top changed"] + ["Total: " + D.name[o] for o in inc]
    zrow = [[C(h, H) for h in hdr]]
    for x in D.scores["sensitivity"]:
        zrow.append([C(D.label(x["criterion_id"])), C("%+d" % x["delta"]), C(D.name[x["top"]]), C("yes" if x["changed"] else "no")] + [C(x["totals"][o], NUM) for o in inc])
    for t in D.scores["confidence_tests"]:
        zrow.append([C(D.label(t["test"]), WRAP), C(""), C(D.name[t["top"]]), C("yes" if t["changed"] else "no")] + [C(t["totals"][o], NUM) for o in inc])
    sens = (zrow, [34, 10, 20, 14] + [22] * len(inc))

    sheets = [("Ranking", ranking), ("Scores", scores), ("Features", features)]
    if cost:
        sheets.append(("Cost", cost))
    return sheets + [("Evidence", evidence), ("Sensitivity", sens)]


def write_xlsx(D, path):
    sheets = build_sheets(D)
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + "".join('<Override PartName="/xl/worksheets/sheet%d.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % i for i in range(1, len(sheets) + 1))
                   + "</Types>")
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr("xl/workbook.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="%s" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>%s</sheets>'
                   '<calcPr fullCalcOnLoad="1"/></workbook>' % (ns, "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (n, i, i) for i, (n, _) in enumerate(sheets, 1))))
        z.writestr("xl/_rels/workbook.xml.rels", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join('<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>' % (i, i) for i in range(1, len(sheets) + 1))
                   + '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>' % (len(sheets) + 1))
        z.writestr("xl/styles.xml", STYLES)
        for i, (_, (rows, widths)) in enumerate(sheets, 1):
            z.writestr("xl/worksheets/sheet%d.xml" % i, _sheet(rows, widths))


# ---- PDF ----------------------------------------------------------------

def find_browser():
    for n in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser"):
        p = shutil.which(n)
        if p:
            return p
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"):
        if os.path.exists(p):
            return p
    return None


def write_pdf(html_path, pdf_path):
    browser = find_browser()
    if not browser:
        return False, "no Edge or Chrome found; open report.html and print it to PDF"
    for _attempt in range(2):
        # a fresh profile avoids clashing with a browser the user already has open
        profile = tempfile.mkdtemp()
        cmd = [browser, "--headless", "--disable-gpu", "--no-pdf-header-footer", "--user-data-dir=" + profile,
               "--print-to-pdf=" + os.path.abspath(pdf_path), pathlib.Path(html_path).resolve().as_uri()]
        try:
            subprocess.run(cmd, capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired) as e:
            shutil.rmtree(profile, ignore_errors=True)
            return False, "browser failed: %s" % e
        for _ in range(20):  # the browser can exit just before the file is flushed
            if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
                break
            time.sleep(0.5)
        shutil.rmtree(profile, ignore_errors=True)
        if os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0:
            return True, ""
    return False, "browser did not produce a PDF; open report.html and print it to PDF"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="export_report.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir")
    ap.add_argument("--out")
    ap.add_argument("--formats", default="html,xlsx,pdf")
    a = ap.parse_args(argv)
    formats = [f.strip() for f in a.formats.split(",") if f.strip()]
    bad = [f for f in formats if f not in ("html", "xlsx", "pdf")]
    if bad:
        raise SystemExit("ERROR: unknown format %s (use html, xlsx, pdf)" % ", ".join(bad))
    D = Data(a.dir)
    out = a.out or os.path.join(a.dir, "export")
    os.makedirs(out, exist_ok=True)
    html_path = os.path.join(out, "report.html")
    if "html" in formats or "pdf" in formats:
        with open(html_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(build_html(D))
        if "html" in formats:
            print("wrote " + html_path)
    if "xlsx" in formats:
        write_xlsx(D, os.path.join(out, "report.xlsx"))
        print("wrote " + os.path.join(out, "report.xlsx"))
    status = 0
    if "pdf" in formats:
        # print from a copy with every section expanded
        fd, print_path = tempfile.mkstemp(suffix=".html", dir=out)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(build_html(D, expand=True))
        ok, why = write_pdf(print_path, os.path.join(out, "report.pdf"))
        os.remove(print_path)
        print("wrote " + os.path.join(out, "report.pdf") if ok else "WARNING: PDF skipped: " + why)
        status = 0 if ok else 2
    if "html" not in formats and "pdf" in formats and os.path.exists(html_path):
        os.remove(html_path)
    return status


if __name__ == "__main__":
    sys.exit(main())
