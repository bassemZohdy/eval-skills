# Evidence handoff to the eval skills

Load only when an eval skill (eval-define, eval-analyze, eval-discover, eval-compare or
eval-report) asks for research. The calling skill owns `eval/`, the look-up budget, the
labels, and every score. This skill finds and judges evidence; it never writes scores,
weights, gate verdicts, or files in `eval/`, and it never ranks options.

## What the caller supplies

Treat these as the research question. Ask the caller, not the user, if one is missing:

- option id, its name, and the package evaluated (product, edition, version);
- the requirement or gate ids, with their text and gate scope;
- the deployment scope, including components that a gate excludes;
- the look-up budget and the as-of date;
- confidential details that must stay out of searches.

Use Standard mode. Stop at the caller's budget, even when the research rules above would
continue, and report what was left unresearched.

## What to return, per finding

One row per claim per option per requirement, with the fields `evidence.json` needs:

| Field | Value |
|---|---|
| `option_id`, `requirement_id` | from the caller |
| `finding` | one sentence of what the source says, attributed, and nothing more |
| `source_url` | the page actually opened; a search result is only a lead |
| `source_date` | publication or update date as `YYYY-MM-DD`, `YYYY-MM`, or `unknown` |
| `gathered_on` | the date the page was read |
| `pin` | release, tag, commit or dated snapshot the page describes |
| `source_kind` | see the origin mapping below |
| `source_class` | `primary` for the operative record, `company` for other vendor material, `secondary` otherwise |
| `confidence` | see the verdict mapping below |
| `scope` | `out_of_scope` when the evidence is about a component a gate excludes |
| `lines` | for source code only, the line range read |

Add, for the caller to read and not to store: the evidence origin, its dependencies, the
counter-evidence searched for, and the unresolved gap.

## Origin to `source_kind`

- The vendor's own documentation, pricing page, release notes or written statement: `vendor`.
  A reseller or a partner selling the option counts as the vendor.
- An organisation that neither makes nor sells the option: `independent`. Two pages from one
  organisation, or pages repeating one benchmark, form one origin.
- The documentation of an open-source project with no commercial seller: `oss_project_docs`.
  When a vendor sells an enterprise edition built on the project, documentation of the
  enterprise features is `vendor`.
- Code read at a pinned commit: `source_code`, cited as `path@commit` with `lines`.

## Verdict to eval label

| This skill's verdict | Eval label |
|---|---|
| Supported, by two or more independent origins | CONFIRMED |
| Supported, by the operative record only (the vendor's documentation of what it provides) | PRIMARY |
| Supported or likely supported, by one independent origin | PROBABLE |
| Likely supported by a vendor performance or quality claim alone, or read in an unopened summary | UNVERIFIED |
| Disputed | DISPUTED, with one row per side |
| Could not verify, including pages that could not be read | COULD NOT VERIFY |
| Contradicted or likely false | the opposing finding as its own row, labelled by its origin as above |
| Misleading | the narrower, defensible reading as the finding, PROBABLE at best |

Code reading is PROBABLE at best unless a test proved it. Evidence about an adjacent
product or an older major version is PROBABLE at best, and the finding says so.

An absent or unreadable page never means the capability is missing. Report "not read"
and leave it to the caller, which keeps the requirement unknown.

## Gates

For a gate, return each pass clause with the rows that bear on it and this skill's gate
result: `PASS`, `FAIL` or `UNKNOWN`. The caller records them as PASS, NOT MET or
UNVERIFIED, together with the basis of a PASS (documented, vendor_confirmed or tested).
