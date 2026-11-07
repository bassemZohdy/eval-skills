# Quantified confidence

Load only when numeric confidence is requested or materially affects the decision.
Qualitative verdicts remain the default. High stakes, user preference, and reproducible
arithmetic do not themselves justify a probability estimate.

## Choose the right quantity

- **Criterion performance score:** rates fit against declared comparison criteria. Follow
  the skill's comparison gates, anchors, weights, and sensitivity rules.
- **Heuristic evidence score:** summarizes judgments using an explicit rubric. Label the
  scale and its anchors; do not express it as percentage confidence or automatically map
  it to a truth verdict.
- **Probability estimate:** requires a model whose calibration and applicability can be
  inspected. Cite the method and its demonstrated scope; report limitations and uncertainty.

Statistical uncertainty in a study is not automatically confidence that a broader claim
is true. Do not substitute an evidence score for a probability-based mandatory gate:
if a justified estimate is unavailable, mark the gate `UNKNOWN`.

## Requirements before calculation

1. Define the quantity, claim, scope, method, and any decision threshold.
2. Cite or explicitly justify parameters, base rates, and scoring anchors. Do not assign
   default source-reliability percentages or infer probabilities from evidence roles.
3. Group duplicates and dependency families before calculation. Count a common observation
   once unless the method explicitly models dependence.
4. Explain how supporting and opposing evidence enters the method. Do not mechanically add
   per-source confidence estimates as if they were independent likelihood ratios.
5. For an additive heuristic, predefine diminishing returns and family-level contribution
   limits on both sides, including a weak-evidence cap. These are rubric judgments, not
   empirical calibration. If they cannot be justified, do not calculate a score.
6. Recalculate under plausible parameter and dependency assumptions. Report a range or
   conditional conclusion when those choices change the decision.
7. Check arithmetic, input bounds, numerical stability, and actual implementation of the
   stated limits. Keep the method and intermediate calculations in an auditable ledger.

Many weak or dependent origins never establish strong corroboration simply by accumulation.
Neither a calculated number nor its rounding may override applicability, inaccessible
content, material opposition, or unresolved decision-critical scope.

## When calculation is not justified

Say why a percentage cannot be justified and provide the qualitative verdict, decisive
evidence, and uncertainty that matters to the decision. A conditional answer is better than
invented precision. If the user wants a heuristic rubric instead, clearly distinguish that
score from a probability and from criterion performance.

This skill supplies no generic probability formula or default reliability bands. Introducing
one requires documented justification and regression cases for duplicates, dependent and
weak evidence, opposing evidence, sensitivity, and numerical extremes.
