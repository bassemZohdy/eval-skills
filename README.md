# eval-skills

A chain of five Claude skills for evaluating options for a solution (products, platforms, libraries, approaches).

| Step | Skill | Purpose |
| --- | --- | --- |
| - | `eval-orchestrator` | Entry point: reads the status, runs or resumes the right step, reruns stale steps, routes change requests |
| 1 | `eval-define` | Capture the solution and approve grouped requirements |
| 2 | `eval-analyze` | Criteria, weights, scoring scale, gates |
| 3 | `eval-discover` | Find and profile candidate options with sourced evidence |
| 4 | `eval-compare` | Weighted score matrix and feature-by-feature comparison |
| 5 | `eval-report` | Final report with recommendation, risks, sources |

All skills share one workspace folder, `eval/`. The contract is in each skill's `references/workspace-contract.md`.

## Dependency: deep-research

Evidence gathering uses the `deep-research` skill (`anthropic-skills:deep-research`) that ships with Claude. It is referenced by name only and is **not copied into this repo**, so its licence terms are not affected. Install or enable it separately. It coordinates subagents; without the Agent tool, the eval skills research directly instead.

`deep-research` does not emit the evidence labels used here. The eval skills apply the labels themselves (PRIMARY, CONFIRMED, PROBABLE, UNVERIFIED, COULD NOT VERIFY, DISPUTED) when recording each finding in `eval/evidence.json`, and enforce the look-up budgets stated in each skill.

## Bundled: deep-researcher

`skills/deep-researcher/` is a separate, general research skill (evidence origins, counter-evidence, claim-level verdicts) with its own regression cases. It is not part of the eval chain and no eval skill calls it. Install the whole folder, not just `SKILL.md`. The package ships without a licence (see its `README.md`), so choose one before redistributing this repo publicly.

## Optional: market context

For market-level questions, `eval-discover` may use `sector-overview` from the market-researcher plugin as a secondary source, if installed. It is referenced by name only and not copied here. Its output must be converted to evidence rows before it counts.

## Install

Copy the five folders in `skills/` into your skills directory (for example `~/.claude/skills/`). Start with `eval-define`; each step tells you which skill to run next. Evaluation files are written to `eval/` in your project root.

## Cost model

Pricing is structured, not prose. `eval/cost.json` holds the cost assumptions (volumes, seats, horizon, currency) written by `eval-define` and, per option, priced components written by `eval-discover`: `fixed_monthly`, `one_time`, `usage` (with an included free amount) and `tiered` (graduated or volume tiers). Prices are entered as published (`per` hour, day, month or year), a cluster that grows with volume uses `quantity_steps`, and a cost no vendor publishes (such as operations time) is marked `assumed` with a note. Every other priced component cites an evidence row; a price that cannot be found is marked `price_unknown` and the option's total is flagged incomplete, never guessed. The script computes the total over the horizon, volume scenarios that multiply the assumptions marked `scales`, and which option is cheapest in each. Results flow into `scores.json`, `features.md` and the HTML, spreadsheet and PDF exports (the spreadsheet keeps the horizon editable).

## Bias checks

Options can name their `provider` and requirements can be marked `basis: assumed`. `score` then reports provider concentration, assumed constraints, the vendor-against-independent mix of the evidence and how many options the cost comparison covers (`bias_checks`), warns when they look skewed, and the HTML report includes a section on them.

## Scoring and gates

Scores come only from the requirement scores: each requirement is scored 0 to 5 against written anchors (the `anchored` model; priority points default to must 5, should 3, could 1), a category's attainment is the weighted mean divided by 5, and the total is the sum of category weight times attainment, out of 100. Category weights are whole numbers adding up to 100. `eval/features.json` is a separate descriptive feature table (with scope tags) that never changes a score. Gates are judged with a written rubric (`gates` in `criteria.json`): every clause for every option, a verdict of PASS, NOT MET or UNVERIFIED, and for a PASS its basis (documented, vendor_confirmed or tested). The report opens with how many options pass every gate. Sensitivity covers equal weights, must-have requirements only, the two largest weights traded and lowered low-confidence scores, and a lead smaller than `meaningful_gap` (default 5 points) is a near-tie. Unverified items live in `open_items.json` with owners and POC test ids, and research-found requirements in `candidate_requirements.json`.

## Scope and packages

Options name the `package` evaluated: a list of `components`, each with its version, release date and support lifecycle (supported, lts or outside_matrix), the newest release on the evaluation date and compatibility notes. The report has a "Packages scored" table. Each option also records `oss_base` (the open-source project and commit or tag it is built on, or `null`), and the same open-source inheritance rule is applied to every option or to none (see the contract). Evidence rows carry a `pin` (release, tag, commit or dated snapshot) and a `source_class`; `source_kind: source_code` findings cite `path@commit` and a line range and are PROBABLE at best unless tested. Evidence about a component that a gate excludes, such as a vendor-hosted registry in an air-gapped evaluation, is marked `scope: out_of_scope`; the scorer then refuses to credit a requirement from it. Define asks about support and lifecycle gates and deployment constraints up front.

## Scripts

Each skill bundles `scripts/eval_calc.py` (Python 3, standard library only) for the parts that must be exact:

- `weights ID ... [--apply eval]` computes rank-sum weights that sum to 100 and can write them into `criteria.json`.
- `validate eval [--before STEP]` checks the `eval/` files against the contract and that earlier steps are complete and not stale.
- `cost eval` computes total cost of ownership and volume scenarios from `eval/cost.json`.
- `add-evidence eval --option ID --requirement ID --finding ... --url ... --confidence ... --kind ...` appends one evidence row with the next free id.
- `complete eval STEP [--slug S]` marks a step complete in `status.json`; `changed eval TOPIC` marks the steps that depend on a change as stale (requirements, weights, gates, options, evidence, cost, scores).
- `matrix FILE.csv` stress-tests an external score table (Criterion and Weight columns plus one numeric column per option): weight sensitivity, equal weights and the smallest lead.
- `gaps eval [--limit N]` lists, per option, the unknown and unsupported requirements to research first, most important first.
- `status eval` prints where an evaluation stands and which skill runs next (used by `eval-orchestrator`).
- `stale-evidence eval [--fast IDS] [--write]` flags evidence older than 3 months (fast-moving options) or 12 months, and with `--write` records it in `status.json`.
- `score eval` computes criterion scores from the 0 to 5 requirement scores (the `anchored` model; the older `cell_midpoint` model still works), the weighted ranking, ties, sensitivity and confidence tests.
- `verify-queue eval` lists what to re-check first: low or medium confidence scores, inherited-only evidence and documented-only gate passes, ordered by weight times the gap between options. `examples/task-queue/verify-queue.json` shows its output.
- `reconcile eval OTHER.csv --map MAP.csv` compares the evaluation with another assessment: both totals, our ratings under their weights and the per-criterion differences.
- `changed eval weights --reason "..."` is the form to use once scores exist; only the latest reason is kept and the report states the late change.
- `features eval` renders `eval/features.md` from `eval/features.json`, the descriptive feature table that never feeds the scores.

`eval-report` also bundles `scripts/report_draft.py`: `draft eval --prose FILE` writes the computed sections of `eval/report.md` from the evaluation files plus the judgment text in a JSON file, and `check eval` verifies the finished report against `scores.json` (the provenance line, the decision table's order and scores, a recommendation that names the leader first and quotes the lead correctly, no "decisive" wording on a near-tie, confidence wording, every excluded option under "Excluded options" and never recommended, every factor not assessed).

`validate` also checks evidence dates (`gathered_on` not in the future, `source_date` not after it), that a score or feature cell cites evidence about its own option, that every gate has a rubric and every option still in play has a verdict and a `gate_status` for it, that judged gate clauses cite evidence, that steps complete in order, that labels fit the source (a lone vendor page is not CONFIRMED), and warns about vague requirements and options named in requirements. With `--before report` it also recomputes the scores and fails when `scores.json` is out of date. `score` lowers any confidence the evidence does not support (contract rule 13) and warns, and warns when it caps a score or when a score of 0 has no evidence.

`eval-report` also bundles `scripts/export_report.py` (`--check` verifies the page: totals match `scores.json`, no total from an earlier run is still shown, and with Edge or Chrome no script errors or sideways scroll at 1400 and 390 px; the HTML also has a what-if panel for weights, a strict-scope toggle for the feature table and sources numbered by first citation), which writes the finished evaluation to `eval/export/` as `report.html`, `report.xlsx` (editable weights and live totals) and `report.pdf` (printed from a fully expanded copy of the HTML by headless Edge or Chrome, skipped if neither is installed). The HTML has a section index, collapsible sections, a source filter, and adapts to phone, tablet and desktop widths. The `examples/task-queue/export/` folder shows the output.

## Try it

`playground/` is a git-ignored scratch folder for trying the skills. Run `python scripts/setup_playground.py`, open Claude Code in `playground/`, and describe a decision. See `playground/README.md`.

## Development

The contract and the script each have one source in `shared/`. After editing them, run `python scripts/sync_shared.py` to copy them into every skill (each skill must be installable on its own). `examples/task-queue/eval/` is a complete sample evaluation used by the tests, and `examples/gateway-like/eval/` is a larger gated, multi-component one (three options, six gates, open-source inheritance, scope tags, open items and a candidate requirement). `tests/fixtures/task-queue-legacy/` keeps the older `cell_midpoint` model working.

```bash
python -m unittest discover -s tests -v
```

### Scorecard

`scripts/scorecard.py` scores the skills themselves, out of 100:

- **Defect detection (50%).** Each case copies a sample evaluation, injects one defect the contract or a skill's quality rules forbid (weights that do not sum to 100, a PASS with an unmet clause, a score citing another option's evidence, a confidence the evidence does not support, `scores.json` edited after scoring, a report whose decision table or lead disagrees with `scores.json`, and so on), runs what a skill would run (`validate --before report`, `score`, `report_draft.py check`) and counts the defect as caught when a new error or a matching warning appears. Both samples must pass clean.
- **Instruction lint (30%).** Static checks on every `SKILL.md` and the contract: frontmatter, step numbering, script commands and bundled files that exist, thresholds that agree across skills and `scoring.md`, contract keys listed once.
- **Tests (20%).** The unit-test pass rate.

```bash
python scripts/scorecard.py --md scorecard.md        # add --skip-tests for the fast part only
```

CI fails below 98. `tests/test_scorecard.py` keeps every case caught. The browser checks need Edge or Chrome; in a container set `EVAL_BROWSER` to a browser path (`chrome-headless-shell` works) and the scripts add `--no-sandbox` when running as root.

## License

Apache-2.0. See `LICENSE`.
