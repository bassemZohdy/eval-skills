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

## Optional: market context

For market-level questions, `eval-discover` may use `sector-overview` from the market-researcher plugin as a secondary source, if installed. It is referenced by name only and not copied here. Its output must be converted to evidence rows before it counts.

## Install

Copy the five folders in `skills/` into your skills directory (for example `~/.claude/skills/`). Start with `eval-define`; each step tells you which skill to run next. Evaluation files are written to `eval/` in your project root.

## Cost model

Pricing is structured, not prose. `eval/cost.json` holds the cost assumptions (volumes, seats, horizon, currency) written by `eval-define` and, per option, priced components written by `eval-discover`: `fixed_monthly`, `one_time`, `usage` (with an included free amount) and `tiered` (graduated or volume tiers). Prices are entered as published (`per` hour, day, month or year), a cluster that grows with volume uses `quantity_steps`, and a cost no vendor publishes (such as operations time) is marked `assumed` with a note. Every other priced component cites an evidence row; a price that cannot be found is marked `price_unknown` and the option's total is flagged incomplete, never guessed. The script computes the total over the horizon, volume scenarios that multiply the assumptions marked `scales`, and which option is cheapest in each. Results flow into `scores.json`, `features.md` and the HTML, spreadsheet and PDF exports (the spreadsheet keeps the horizon editable).

## Bias checks

Options can name their `provider` and requirements can be marked `basis: assumed`. `score` then reports provider concentration, assumed constraints, the vendor-against-independent mix of the evidence and how many options the cost comparison covers (`bias_checks`), warns when they look skewed, and the HTML report includes a section on them.

## Scope and packages

Options name the `package` evaluated (editions, products, versions). Evidence about a component that a gate excludes, such as a vendor-hosted registry in an air-gapped evaluation, is marked `scope: out_of_scope`; the scorer then refuses to credit a requirement from it. Define asks about support and lifecycle gates and deployment constraints up front.

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
- `score eval` computes criterion scores, the weighted ranking, ties, sensitivity and confidence tests, and writes `eval/features.md`.

`eval-report` also bundles `scripts/report_draft.py`: `draft eval --prose FILE` writes the computed sections of `eval/report.md` from the evaluation files plus the judgment text in a JSON file, and `check eval` verifies the finished report against `scores.json` (leader, scores, confidence wording, excluded options).

`eval-report` also bundles `scripts/export_report.py`, which writes the finished evaluation to `eval/export/` as `report.html`, `report.xlsx` (editable weights and live totals) and `report.pdf` (printed from a fully expanded copy of the HTML by headless Edge or Chrome, skipped if neither is installed). The HTML has a section index, collapsible sections, a source filter, and adapts to phone, tablet and desktop widths. The `examples/task-queue/export/` folder shows the output.

## Try it

`playground/` is a git-ignored scratch folder for trying the skills. Run `python scripts/setup_playground.py`, open Claude Code in `playground/`, and describe a decision. See `playground/README.md`.

## Development

The contract and the script each have one source in `shared/`. After editing them, run `python scripts/sync_shared.py` to copy them into every skill (each skill must be installable on its own). `examples/task-queue/eval/` is a complete sample evaluation used by the tests.

```bash
python -m unittest discover -s tests -v
```

## License

Apache-2.0. See `LICENSE`.
