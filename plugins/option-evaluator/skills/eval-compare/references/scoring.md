<!-- Copy of plugins/option-evaluator/shared/scoring.md. Edit the source in shared/, not this copy. -->

# Scoring rules

Detail for eval-compare steps 3 to 8. SKILL.md holds the process; this file holds the rules in plain words. The exact formulas, constants and the review protocol are in `references/calculation.md`, which wins if the two ever differ.

## Calculation

Steps 3 to 8 are computed by hand with `references/calculation.md`, so the arithmetic is the same every time. Never calculate a total from memory or from an unshown sum.

1. Write the judgments into `eval/scores.json` with `"scoring_model": "anchored"`: a `requirement_scores` entry for every included option and requirement (`score` 0 to 5 against the anchors in `criteria.json` `requirement_anchors`: 5 exceeds, 4 fully meets and is generally available, 3 core met with limits, 2 partial, preview or beta, 1 only via a custom build, a third-party add-on or a component outside the package, 0 not met; `confidence`; a `rationale` of at most 40 words; `evidence_ids`) and any `overrides` the user asked for, each with a requirement_id and a reason. A requirement left out counts as 0, and as 4 in the best case.
2. Apply the rules of calculation.md sections 2 to 6 (cap for weak evidence, confidence rule, priority weighting, totals, ranking and ties) in working tables, then sections 7 and 8 (sensitivity, cost), then the review protocol of section 11. Write the criterion scores, totals, ranking, ties, sensitivity and confidence tests into `eval/scores.json` and render `eval/features.md` from `eval/features.json`.
3. Show the user the warnings (missing cells, missing rationales, large overrides). A warning that one option has far fewer evidence-backed requirements than the best-covered option means its score may reflect how little was researched: build the research gaps list ('Research gaps' in `references/procedures.md`), which lists for each option the unknown and unsupported requirements to research first, and go back to eval-discover to bring that option up to the same depth before ranking or reporting. Also state the best-case bound and which options could overtake the leader (calculation.md section 4): when an option could overtake the leader once its unknown requirements are researched, research them in eval-discover first, or say in the review that the ranking is undecided.
4. Use the total cost of ownership and the volume scenarios from calculation.md section 8 to score the cost criterion (cheaper at the user's stated volume is better; write confidence low for a cost score that rests on unverified or missing prices) and say in the review which option is cheapest in each scenario.

## Weak evidence and confidence (step 4)

A score resting only on UNVERIFIED or COULD NOT VERIFY evidence is capped at 2 and marked low-confidence; warn the user when you cap. DISPUTED evidence counts as no source for confidence, so score on the weaker side and expect low confidence. When the confidence written in `scores.json` is higher than the evidence supports, lower it and warn. Never award a high score on a vendor claim alone. Give every score a confidence value of high (two sources), medium (one source), or low (none). Independent sources count, and the vendor's official documentation counts once more for what a product provides (a functional requirement, or one marked `evidence_class: feature`), never for performance or quality. Sources are independent only if they come from different organizations and neither is the vendor or sells the option, so a vendor's docs page and its blog count as one source, and a reseller counts as the vendor. Exception: the official docs or source repository of an open-source project with no commercial seller count as one independent source for what the project provides, never for its own performance or quality claims, and show it next to the score and the total.

## Sensitivity and ties (step 6)

Recompute the ranking with each of the three highest-weight criteria moved by plus or minus 5 points, rescaling the other weights proportionally so they still sum to 100. Report whether the top option changes. Report near-ties as ties: options closer than `meaningful_gap` in `criteria.json` (default 5 points), and break them by fewer must-have gaps (vendor-claimed, partial, missing, and unknown all count as gaps), then by the higher score on the highest-weight criterion, stating which tie-break was used. Also test confidence: lower all low-confidence scores by one point together, then each of the three highest-weighted low-confidence scores alone, and report whether the top option changes.

## Anchored model

The criterion attainment is the priority-weighted mean of its requirement scores divided by 5; priority points default to must 5, should 3, could 1 and can be changed with `priority_points`. A requirement with no non-weak evidence is capped at 2. The total is the sum of category weight times attainment, shown out of 100 with one decimal and not rounded earlier. `requirement_shares` splits each category weight over its requirements by priority points, rounded by largest remainder so the shares add up to the category weight.
