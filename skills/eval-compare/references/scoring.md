# Scoring rules and the calculation script

Detail for eval-compare steps 3 to 8. SKILL.md holds the process; this file holds the rules the script applies.

## Calculation script

Steps 3 to 8 are computed by the bundled script, so the arithmetic is the same every run. Do not calculate scores, totals, rankings, or the feature table by hand.

1. Write the judgments into `eval/scores.json` with `"scoring_model": "anchored"`: a `requirement_scores` entry for every included option and requirement (`score` 0 to 5 against the anchors in `criteria.json` `requirement_anchors`: 5 exceeds, 4 fully meets and is generally available, 3 core met with limits, 2 partial, preview or beta, 1 only via a custom build, a third-party add-on or a component outside the package, 0 not met; `confidence`; a `rationale` of at most 40 words; `evidence_ids`) and any `overrides` the user asked for, each with a requirement_id and a reason. A requirement left out counts as 0, and as 4 in the best case. Evaluations that still use `"scoring_model": "cell_midpoint"` keep the older cell values described at the end of this file.
2. Run `python scripts/eval_calc.py score eval`. It validates the inputs, applies the shared mapping, the priority weighting, the cap for weak evidence, and the confidence rule, then writes the criterion scores, totals, ranking, ties, sensitivity and confidence tests back into `eval/scores.json` and renders `eval/features.md` from `eval/features.json`.
3. If it reports errors, fix the inputs and rerun. Show the user its warnings (missing cells, missing rationales, large overrides). A warning that one option has far fewer evidence-backed requirements than the best-covered option means its score may reflect how little was researched: run `python scripts/eval_calc.py gaps eval`, which lists for each option the unknown and unsupported requirements to research first, and go back to eval-discover to bring that option up to the same depth before ranking or reporting. The result also lists `unknown_bounds` and `could_overtake_leader`: when an option could overtake the leader once its unknown requirements are researched, research them in eval-discover first, or say in the review that the ranking is undecided.

4. The script also recomputes the total cost of ownership and the volume scenarios from `eval/cost.json`. Use them to score the cost criterion (cheaper at the user's stated volume is better; an option priced with unverified or missing components stays low-confidence) and say in the review which option is cheapest in each scenario.

If Python is unavailable, apply the rules in steps 3 to 7 by hand and say so in the review.


## Weak evidence and confidence (step 4)

A score resting only on UNVERIFIED or COULD NOT VERIFY evidence is capped at 2 and marked low-confidence; the script warns when it caps. DISPUTED evidence counts as no source for confidence, so score on the weaker side and expect low confidence. When the confidence written in `scores.json` is higher than the evidence supports, the script lowers it and warns. Never award a high score on a vendor claim alone. Give every score a confidence value of high (two sources), medium (one source), or low (none). Independent sources count, and the vendor's official documentation counts once more for what a product provides (a functional requirement, or one marked `evidence_class: feature`), never for performance or quality. Sources are independent only if they come from different organizations and neither is the vendor or sells the option, so a vendor's docs page and its blog count as one source, and a reseller counts as the vendor. Exception: the official docs or source repository of an open-source project with no commercial seller count as one independent source for what the project provides, never for its own performance or quality claims, and show it next to the score and the total.

## Sensitivity and ties (step 6)

Recompute the ranking with each of the three highest-weight criteria moved by plus or minus 5 points, rescaling the other weights proportionally so they still sum to 100. Report whether the top option changes. Report near-ties as ties: options closer than `meaningful_gap` in `criteria.json` (default 5 points on the anchored model, 3 on the older cell_midpoint model), and break them by fewer must-have gaps (vendor-claimed, partial, missing, and unknown all count as gaps), then by the higher score on the highest-weight criterion, stating which tie-break was used. Also test confidence: lower all low-confidence scores by one point together, then each of the three highest-weighted low-confidence scores alone, and report whether the top option changes.

## Feature table (older cell_midpoint model) and shared mapping (step 7)

One row per requirement, grouped by category, one column per option. Each cell is one of: provided, vendor-claimed (the vendor says it is provided only in marketing, a press release, or a page that was not read; a feature described in the official documentation counts as provided), partial, not provided, unknown, with a short note and the evidence id. Use one shared mapping so the table and the scores never disagree: record in `eval/scores.json` how each cell value maps to the score range (not provided 0 to 1, partial 2 to 3, provided 4 to 5, vendor-claimed 2, unknown counts as 1). A criterion score is the priority-weighted mean of its requirements' range midpoints (not provided 0.5, partial 2.5, provided 4.5, vendor-claimed 2, unknown 1; priority weights must 3, should 2, could 1, recorded in the mapping), rounded half up to a whole number; a written rationale or a recorded user override may move it by at most one point. Store the canonical cells as `cell_values` in `eval/scores.json` and generate `eval/features.md` from them, with the note and evidence id in each cell. Add a summary row per option counting provided, vendor-claimed, partial, missing, and unknown for must-have requirements.


## Anchored model

The criterion attainment is the priority-weighted mean of its requirement scores divided by 5; priority points default to must 5, should 3, could 1 and can be changed with `priority_points`. A requirement with no non-weak evidence is capped at 2. The total is the sum of category weight times attainment, shown out of 100 with one decimal and not rounded earlier. `requirement_shares` splits each category weight over its requirements by priority points, rounded by largest remainder so the shares add up to the category weight.
