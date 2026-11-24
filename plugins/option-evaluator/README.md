# Option Evaluator

A chain of Claude skills for evaluating options for a solution (products, platforms, libraries, approaches). This edition is **Markdown only**: it contains no scripts, so every calculation is done by the model from written rules and then checked by a fixed review protocol.

| Step | Skill | Purpose |
| --- | --- | --- |
| - | `eval-orchestrator` | Entry point: reads the status, runs or resumes the right step, reruns stale steps, routes change requests |
| 1 | `eval-define` | Capture the solution and approve grouped requirements |
| 2 | `eval-analyze` | Criteria, rank-sum weights, scoring scale, gates |
| 3 | `eval-discover` | Find and profile candidate options with sourced evidence and priced components |
| 4 | `eval-compare` | Anchored scores, weighted totals, ranking, sensitivity |
| 5 | `eval-report` | Final Markdown report with recommendation, risks, sources |
| - | `eval-deep-research` | Evidence-led research that the steps call for sourced findings |

All skills share one workspace folder, `eval/`, in your project root. The contract is in each skill's `references/workspace-contract.md`.

## Install

```
/plugin marketplace add bassemZohdy/eval-skills
/plugin install option-evaluator@eval-skills
```

Start with the orchestrator (ask Claude to help you choose between options), or with `eval-define`.

## How the numbers stay accurate without scripts

- `references/calculation.md` holds the whole calculation: rank-sum weights, the 0 to 5 anchored requirement scores with their caps and confidence rules, category attainment and totals, ranking and near-ties, the best-case bound, sensitivity, total cost of ownership, gates and the bias checks. Formulas, constants and rounding are written out, and no other formula may be used.
- Every calculation goes through a **review protocol**: working tables with every intermediate value (pass 1), a recomputation in a different order (pass 2), invariant checks such as weights summing to 100 and totals equalling the sum of contributions (pass 3), and up to two more independent recomputations if the passes disagree. The passes are logged in `eval/calc-check.md`. If five passes never agree, the affected scores are marked UNVERIFIED and the user is told.
- `references/validation.md` is a checklist for the `eval/` files before each step, and `references/procedures.md` replaces the housekeeping commands (status, completing a step, marking steps stale, the feature table).
- The rules were checked against a tested reference implementation: the repository's test suite compares the constants and worked examples in `calculation.md` with it, and the instructions were followed blind (by hand, and with a calculator) on the two sample evaluations and on a hard case with missing scores, evidence caps, an override and every cost component type. The readers' totals, rankings, sensitivity runs and costs matched the tested implementation; a hand-calculation slip of 0.1 in one sensitivity run is the kind of error the review protocol catches, and ambiguities the readers reported were closed in `calculation.md`.

## Limits of this edition

- The report is `eval/report.md` only. There are no HTML, spreadsheet or PDF exports.
- Only the anchored scoring model is supported.
- Calculations are done by the model, so they depend on the review protocol being followed. For the script-checked edition, see the `eval-skills` plugin in the same repository.

Licensed under Apache-2.0 (see `LICENSE`).
