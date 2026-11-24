<!-- Copy of plugins/option-evaluator/shared/calculation.md. Edit the source in shared/, not this copy. -->

# Calculation rules and the review protocol

This plugin ships no scripts. Every number is computed by you, by hand, from the evaluation files, using only the rules below. These rules are the whole calculation: do not use another formula, do not round earlier than stated, and do not estimate. Run the review protocol (section 11) on every calculation before you write it to a file or show it to the user.

## 0. Ground rules

1. **Show the arithmetic.** Every result is written first in a working table (inputs, formula, result on each row). A number that appears in a file or in the chat must come from such a table.
2. **Use exact fractions.** Keep full precision in every intermediate value. Round only where a rule below says so, and round half up (62.25 becomes 62.3; 0.5 becomes 1).
3. **Use only recorded inputs.** Weights come from `eval/criteria.json`, scores from `eval/scores.json`, assumptions and prices from `eval/cost.json`. Never type a number from memory.
4. **When two passes disagree, the inputs win.** Recompute from the raw files, never from an earlier result (section 11).
5. **Fixed vocabulary and defaults.** Evidence labels are PRIMARY, CONFIRMED, PROBABLE, UNVERIFIED, COULD NOT VERIFY and DISPUTED. *Weak* means UNVERIFIED or COULD NOT VERIFY only. PRIMARY, CONFIRMED and PROBABLE are usable. A missing `scope` means `in_scope`; a missing `inherited_from_oss` means false; a missing `meaningful_gap` means 5; missing `requirement_anchors` mean the default anchors below; the per-criterion `anchors` text in `criteria.json` is descriptive and never enters a calculation. Every criterion with weight above 0 takes part in every total and in the sensitivity runs, including a cost criterion when `cost_mode` is `weighted`.
6. **Compare rounded totals.** Totals are rounded to one decimal (section 3) and every comparison afterwards (ranking, near-tie groups, lead, scenario leaders) uses those rounded totals, never the unrounded ones.
7. **A calculation you cannot finish is stated, not guessed.** If an input is missing, say which, mark the affected result UNVERIFIED, and stop.

## 1. Rank-sum weights (criteria weights from a ranking)

Input: the criterion ids from most to least important, `n` of them (leave out the cost criterion when `cost_mode` is `separate`).

1. Points: the first gets `n`, the second `n-1`, down to 1 for the last. Total points `T = n(n+1)/2`.
2. Raw weight of each = `points x 100 / T`.
3. Floor each raw weight to a whole number. Let `short = 100 - sum of floors`.
4. Give `+1` to the `short` criteria with the largest fractional part (raw minus floor). If fractional parts are equal, the criterion ranked higher (earlier in the list) goes first.
5. Check: the weights are whole numbers and sum to exactly 100. Criteria left out of the ranking (such as a separate cost criterion) get weight 0.

Worked checks: n=4 gives 40, 30, 20, 10. n=3 gives 50, 33, 17 (raw 50, 33.33, 16.67; floors 50, 33, 16; the one missing point goes to the largest fraction, .67). n=7 gives 25, 21, 18, 14, 11, 7, 4.

If the user supplies their own point allocation, accept it when it sums to 100 and every weight is a whole number.

## 2. Requirement scores (the model's judgment, bounded by rules)

Each included option gets a score of 0 to 5 on every active requirement (a requirement with `retired: true` is ignored). The anchors are in `requirement_anchors` of `eval/criteria.json`; the defaults are: 5 exceeds the requirement; 4 fully meets it and is generally available; 3 core is met with limits; 2 partial, preview or beta; 1 only via a custom build, a third-party add-on or a component outside the package; 0 not met.

Rules applied to every score, in this order:

1. **Missing score.** A requirement with no score entry counts as 0 with confidence `low` in the result and as 4 in the best-case bound (section 4). Warn the user, naming the cells.
2. **Out of scope.** If the score is 1 or more and every cited evidence row has `scope: out_of_scope`, that is an error: score it 0.
3. **Weak evidence cap.** A cited row is *weak* when its confidence is UNVERIFIED or COULD NOT VERIFY. The score is *weakly supported* when none of its cited ids is an existing, non-weak evidence row (a score with no citation at all is weakly supported). A weakly supported score above 2 is lowered to 2, marked `capped`, and the user is warned; a score of 2 or less is left unchanged and not marked `capped`. DISPUTED rows are not weak for the cap, but they never count as a source for confidence.
4. **Zero without evidence.** A score entry of 0 is a scored 0 (it is not missing). A score of 0 with no evidence draws a warning: "not met" needs a source saying the capability is absent. If nothing could be read, leave the cell unscored and research it.
5. **Confidence.** Supported confidence of a score is computed from its cited rows:
   - Usable rows: confidence not UNVERIFIED, COULD NOT VERIFY or DISPUTED, and `scope` not `out_of_scope`.
   - `n` = the number of distinct sources among usable rows whose `source_kind` is `independent`, `oss_project_docs` or `source_code`, where a source is the pair (`source_kind`, host name of `source_url`, lower case). Two pages of one host count once.
   - Add 1, once, to `n` when the requirement is a *feature requirement* and any usable row has `source_kind: vendor` (one vendor row or ten give the same +1). `n` is worked out separately for each score from that score's own cited rows. A row with `inherited_from_oss: true` is counted like any other for `n`. A feature requirement has `evidence_class: feature`, or no `evidence_class` and `type: functional`.
   - Supported confidence is `high` when `n >= 2`, `medium` when `n = 1`, `low` when `n = 0`.
   - If the confidence written on the score is higher than the supported confidence, lower it to the supported one and warn.
   - If every cited row has `inherited_from_oss: true` and the confidence is `high`, lower it to `medium` and warn.
6. **Override.** A user override replaces the score after the cap. It needs a non-empty reason (error if not), and a warning is shown when it moves the score by more than 1 point. An override leaves the written confidence unchanged.
7. **Must-have gap.** A must requirement scoring 2 or less is a *must gap*. The must-gap count of an option is the number of such requirements; a missing must requirement counts as 0 and so is a must gap.

## 3. Category attainment and totals

`mx` is `scale.max` from `criteria.json` (default 5). Priority points `pts` default to must 5, should 3, could 1; `priority_points` in `scores.json` replaces them.

For every included option and every criterion (category) `c`:

1. `den = sum of pts[priority] over the requirements of c`.
2. `num = sum of pts[priority] x score over the requirements of c`.
3. **Category score** = `num / den / 5 x mx` (on the 0 to `mx` scale; a category is marked `capped` when any of its requirement scores was capped). **Attainment** = category score / `mx` = `num / den / 5` (between 0 and 1).
4. **Contribution** = attainment x category weight (show 2 decimals; do not use the rounded value further).
5. **Category confidence** (using each requirement's confidence after rule 5 of section 2 has lowered it where needed): `low_share` = points of the requirements whose confidence is `low`, divided by `den`. The category is `low` when `low_share >= 0.5`, `high` when every requirement is `high`, otherwise `medium`.
6. **Total** of an option = the sum over criteria of attainment x weight, out of 100, rounded half up to **one decimal**. Never round a category value before summing. A cost criterion with weight 0 (when `cost_mode` is `separate`) contributes nothing.
7. **Requirement shares** (how a category weight splits over its requirements): each requirement's share = category weight x its points / `den`, floored; the remaining whole points go to the largest fractional parts, ties broken by requirement id in alphabetical order; each category's shares sum to its weight.

Checks that must hold: category weights are whole numbers summing to 100 over the weighted criteria; every attainment is between 0 and 1; each total equals the sum of its contributions (up to rounding in the last decimal) and is at most 100; a scored category holds at least two requirements.

## 4. Best-case bound (unknown requirements)

For each option, recompute category scores with every *missing* requirement scored 4 instead of 0 (all other scores unchanged), then the total as in section 3. This is `if_unknowns_provided`. An option other than the leader **could overtake the leader** when its best-case total is greater than the leader's total as scored. The leader is the first option in the ranking (section 5). When no score is missing, the best-case total equals the total as scored and no option could overtake. When any option could overtake, tell the user to research the unknowns first, or to call the ranking undecided.

## 5. Which options are ranked

For every option in `options.json`:

- `excluded: true` or `not_profiled: true`: not ranked; listed separately with `exclusion_reason` (or "not profiled").
- Any gate status `fail` without `excluded`: treat as excluded and warn.
- Any gate status `unverified` (not `waived_by_user`) on an option still in play: **stop**. Ranking is blocked until the gate is resolved or waived in eval-discover.
- `waived_by_user` is ranked normally; note the waiver.

## 6. Ranking, near-ties and tie-breaks

`margin` = `meaningful_gap` from `criteria.json` (default 5 points).

1. Sort the included options by their one-decimal total, highest first.
2. Build groups: walk down the sorted list; an option joins the current group when `(total of the group's first option) - (its total) <= margin`; otherwise it starts a new group. (Compare with the first option of the group, not the previous one, and use the one-decimal totals.)
3. A group of one is ranked as is. Inside a group of two or more, order by: fewer must gaps; then higher category score on the highest-weight criterion (the first criterion in file order when weights tie); then higher total. Record the tie-break actually used: "fewer must-have gaps" when the must-gap counts differ, else "higher score on highest-weight criterion" when those scores differ, else "total score".
4. The ranking is the groups in order, each group internally ordered as in step 3. A near-tie group can therefore put an option with a slightly lower total first; say so.
5. **Lead** = one-decimal total of the option with the highest total minus the one-decimal total of the option with the second-highest total, rounded to one decimal (taken from totals, not from the tie-broken order). A lead below `margin` is a near-tie.

## 7. Sensitivity (always run all of it)

Notation: `weights` are the base weights. "Rank" means sections 3 and 6 with the stated weights or scores and the same `margin`; the near-tie tie-break uses the base must-gap counts (they do not change in any scenario) and the highest-weight criterion *of the weights used in that run*. A run's **leader** is the first option of that run's ranking, which after a tie-break can be an option with a lower total. `base leader` = first option of the base ranking. A scenario is *changed* when its leader differs from the base leader.

**A. Weight moves.** Take the three criteria with the highest weight (weight above 0; file order breaks ties). For each of them and for each `delta` of +5 and -5:

1. `old` = its weight; `new` = `old + delta`, held between 0 and 100. Skip the case when `old` is 100.
2. `k = (100 - new) / (100 - old)`. Every other criterion's weight = its weight x `k`. The moved criterion's weight = `new`. (The weights still sum to 100; they need not be whole numbers, and are not rounded.)
3. Recompute every total, rank, and record the leader, whether it changed, and whether the leader is part of a near-tie group (an option within `margin` of the first option).

**B. Scenarios** (each is a full re-ranking with the leader recorded):

1. *Base weights.*
2. *Equal category weights*: every criterion with weight above 0 gets `100 / (number of such criteria)`; the rest 0.
3. *Must-have requirements only*: for each category, use only its must requirements and the plain mean of their scores (`mean score / 5 x mx` as the category score); a category with no must requirement uses all its requirements with the priority-weighted mean of section 3. Base weights.
4. *Five points moved between the two largest weights*: with `a` the largest and `b` the second largest weight, run (`a` +5, `b` -5) and (`b` +5, `a` -5), changing only those two weights and leaving every other weight as it is (no rescaling); skip a direction when the donor's weight is below 5. Each direction is its own scenario.
5. *Low-confidence scores lowered* (see C, test 1), when any category confidence is low. A scenario that is not run (no low cell, a skipped direction) is not listed and not counted.

`order_changes` = "N of M scenarios", where M counts every scenario of B actually run (base weights, equal weights, must-have only, each five-point direction, and the low-confidence scenario when run) and N the ones that are changed. The A weight moves and the C tests other than test 1 are not counted in M.

**C. Confidence tests.** `low cells` = every (option, criterion) whose category confidence is `low`. When there are none, skip C.

1. *All low-confidence scores lowered by one*: subtract 1 from the category score (0 to `mx` scale, so one point of the category score, not one point of a requirement) of every low cell, never below 0 (this removes `weight / mx` points from that option's total per lowered cell); re-rank.
2. *Each of the three highest-weighted low cells alone*: order the low cells by criterion weight, highest first (equal weights keep option file order, then criterion file order); for each of the first three, lower only that cell by one and re-rank. Run this even when it gives the same result as test 1 (for example when there is a single low cell).

Report whether the top option changes in any test, and every near-tie.

**D. Deciding cells** (what to verify before deciding). List every gate verdict. Then, for the leader `a` and the runner-up `b` (first two of the ranking), for each must requirement `r` in category `c`: `worth = weight(c) x pts[must] / den(c) / 5`; `points = (score of a - score of b) x worth`, rounded to 2 decimals. Sort by absolute `points`, largest first (equal absolute values keep category order, then requirement order in the file); `gap` = sum of all the 2-decimal `points` (signed). Round `points` half up to 2 decimals (-1.875 becomes -1.87, that is toward +infinity). Take rows from the top, adding each row's signed `points` to a running sum after taking it, and stop as soon as the running sum is at least 80% of `gap` (only when `gap` is above 0); also stop before a row whose `points` are 0; when `gap` is 0 or negative, take every nonzero row. Gate requirements that are must-haves are included like any other must requirement. These are the cells a person should verify.

## 8. Cost (total cost of ownership)

Inputs: `eval/cost.json` (`currency`, `horizon_months`, `assumptions` with `id`, `value`, `scales`; optional `scenarios` with `name`, `multiplier`; `options`, each with a `components` list). The default scenarios are *low* (multiplier 0.5) and *high* (multiplier 2) when none are given.

**Assumption values.** For a scenario with multiplier `m`: value of an assumption = `value x m` if `scales` is true, otherwise `value`. The base case uses `m = 1`.

**Monthly cost and one-time cost of one component** (`vals` = the assumption values above):

1. `price_unknown: true`: monthly 0, one-time 0, and the option is **incomplete**.
2. Quantity `q`: the value of `quantity_driver` when set, otherwise `quantity` (default 1). If `quantity_steps` is present, `q` is the `quantity` of the first step whose `up_to` is at least the value of `quantity_driver` (a step with `up_to: null` matches anything).
3. `kind: fixed_monthly`: monthly = `amount x period factor x q`. Period factors: `hour` 730, `day` 365/12 (30.4167), `month` 1, `year` 1/12; `per` defaults to `month`.
4. `kind: one_time`: one-time = `amount x q`.
5. `kind: usage`: `units` = value of `driver`; monthly = `unit_price x max(0, units - included_free)` (`included_free` defaults to 0).
6. `kind: tiered`: `units` = value of `driver`; `tiers` are `up_to` (the last is null) and `unit_price`.
   - `tier_mode: volume`: find the first tier with `up_to` null or `units <= up_to`; monthly = `units x` that tier's `unit_price` (all units at one price).
   - otherwise (*graduated*, the default): walk the tiers in order with `prev = 0`; for each tier `top = units` (when `up_to` is null) or `min(units, up_to)`; when `top > prev`, add `(top - prev) x unit_price` and set `prev = top`.

**Per option:** `monthly` = sum of component monthly costs; `one_time` = sum of one-time costs; **TCO** = `one_time + monthly x horizon_months`. Each scenario total = `one_time + monthly x horizon_months`, recomputed with that scenario's assumption values (the quantity steps and drivers move with the scenario). Round money to 2 decimals only when writing a result, never in between.

**Flags.** `assumed` lists components with `assumed: true`. `evidence_gaps` lists components that are `price_unknown`, or have no `evidence_id`, or whose evidence row is weak (UNVERIFIED or COULD NOT VERIFY).

**Comparison.** Only complete options (no `price_unknown` component) are compared: they are ranked by TCO ascending, the cheapest is the first, and `index vs cheapest` = TCO / cheapest TCO, rounded to 2 decimals. Incomplete options are listed after, with no index and their total marked a lower bound. The cheapest option in each named scenario is found among the complete options only (the base case is not a scenario). When no option is complete there is no cheapest option and no index; show each total as a lower bound. List a component once in `evidence_gaps` however many of the conditions it meets, and leave an option with no entry in `cost.json` out of the cost tables. When fewer options are complete than total, say that the cheapest is the cheapest among those that publish a price, not overall.

**In the score.** With `cost_mode: weighted`, the cost criterion is scored like any other, from requirement scores (cheaper at the stated volume is better). When you write the confidence of a cost score that rests on an incomplete or weakly evidenced price, write `low`; the calculation itself never forces a confidence, it only applies section 2 rule 5 to the value written. With `cost_mode: separate`, the cost criterion has weight 0 and cost is shown beside the score.

## 9. Gates

A gate's verdict for an option is judged clause by clause against the rubric in `criteria.json` `gates`:

- Each clause: `met` true, false or null (null means not checked), a note, and evidence ids (required when `met` is true or false).
- **PASS** needs every clause met, and a `basis` of `documented`, `vendor_confirmed` or `tested`; a documented PASS names `confirm_by`.
- **NOT MET** needs at least one clause marked not met.
- **UNVERIFIED** when no clause is marked not met and at least one is null.
- `gate_status` in `options.json` follows the verdict: PASS is `pass`, NOT MET is `fail`, UNVERIFIED is `unverified`; `waived_by_user` is the only other allowed value and overrides the match. Gates are never scored.

## 10. Coverage and bias checks (shown as warnings in the review)

1. **Evidence coverage** of an option = the number of active requirements whose score is not missing and cites at least one non-weak evidence row. If an option's coverage is below two thirds of the best-covered option's (`coverage x 3 < best x 2`), warn that its scores may reflect how little was researched, and send the user back to eval-discover to bring it to the same depth.
2. **Provider concentration**: with at least 3 included options that name a `provider`, warn when more than half share one provider (largest share above 0.5), unless a stated requirement explains it.
3. **Open-source base**: if some included options have an `oss_base` and others were never checked (no `oss_base` key), warn: apply the inheritance rule to every option or to none.
4. **Assumed requirements**: list each requirement with `basis: assumed`; warn for each one that is a gate.
5. **Source mix**: per option, count evidence rows with `source_kind: vendor` against all other rows (every non-vendor row counts as independent or open-source). Warn when every option has only vendor rows, or when some options have independent rows and others have none.
6. **Cost comparability**: warn when only some options are complete (section 8).
7. **Repeated rationale**: warn when the same rationale text is used for more than two scores.

## 11. The review protocol (3 to 5 passes, mandatory)

Run this for every set of numbers: weights, requirement-to-category results, totals, ranking, sensitivity, cost. Write each pass into `eval/calc-check.md` (create it if absent; keep one section per calculation, newest last) so the user can inspect it.

**Pass 1: full working tables.** For every option and category write one row with: each requirement's points and score, `num`, `den`, attainment, weight, contribution. Then one row per option with the sum of contributions and the rounded total. For cost write one row per component with its formula and the option totals. For sensitivity write the weights used and the totals in every scenario. Nothing may be computed outside a table.

**Pass 2: recompute in a different order.** Recompute the totals option by option instead of category by category (or the reverse of what pass 1 did), and the cost totals scenario by scenario instead of component by component. Do not look at the pass-1 numbers while doing it. Compare the two sets row by row.

**Pass 3: invariant checks.** Confirm every item and write PASS or the failure:

- Weights are whole numbers and sum to exactly 100 (the scaled weights of a weight-move scenario and the equal-weights scenario may be fractions; they still sum to 100).
- Every attainment is between 0 and 1; every category score is between 0 and `mx`.
- Each total equals the sum of its contributions (difference under 0.1) and is at most 100, and at least 0.
- The ranking agrees with the totals, apart from groups reordered by a tie-break, and each such group is within `margin` of its first option.
- Each cost total equals the sum of its components; each scenario total is at least the one-time cost; fixed costs do not change between scenarios.
- Requirement shares sum to the category weight.
- Every number in the working tables traces to a value in an input file.

**Stop rule.** Passes *agree* when every number (to the rounding stated for it) and every label (ranking order, tie-break, confidence, leader) is the same. If passes 1, 2 and 3 agree and no invariant failed, stop: the calculation is verified, and you record "3 passes agree".

**Passes 4 and 5.** Only if the passes disagree or an invariant failed. Pass 4: recompute from the raw input files alone, without opening any earlier result. Pass 5 is the same by a second independent route (use a subagent for it when the Agent tool exists, giving it only the input files and this document). Stop as soon as three passes agree. Locate and fix the cause of each disagreement (a misread input, a wrong formula, a rounding step), and say what it was in `eval/calc-check.md`.

**If five passes still do not agree,** do not write the result. Mark the affected scores UNVERIFIED, tell the user which numbers could not be verified and why, and ask how to proceed.

**Reporting.** The report and the review message state that the calculation was checked and how many passes agreed. Never claim a check that was not run.
