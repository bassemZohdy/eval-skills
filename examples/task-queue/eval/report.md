# Evaluation report: background task queue

Evaluation date 2026-10-01. Scale 0 to 5. Cost mode: weighted.

## Decision recommendation

The choice between Beta Queue and Alpha Queue is not clear-cut: Beta Queue scores 78.0 against 76.0 for Alpha Queue, inside the 3-point tie margin. Beta Queue leads on core capabilities, but its operability claims are unverified, and lowering those low-confidence scores puts Alpha Queue ahead. Verify Beta Queue's metrics support before committing.

**Confidence: low.** A near-tie that flips when low-confidence scores are lowered, with the leader's best case 6 points higher if its unverified claims hold.

## Decision table

| Rank | Option | Score | Gates | Low-confidence criteria | Main strength | Main gap |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Beta Queue | 78.0 | F-01 pass | 1 | Strongest core queueing capabilities | Operability claims rest on vendor statements |
| 2 | Alpha Queue | 76.0 | F-01 pass |  | Well-documented operations, independent sources | Weaker core throughput features |

Near-tie (within 3.0 points): Beta Queue, Alpha Queue; broken by higher score on highest-weight criterion.

## Context

A small team needs a queue for background jobs (emails, report generation) in an existing web application. The decision is which queue product to adopt. This is a fictional sample evaluation used to test the eval skills.

## Criteria and weights

| Criterion | Weight | Requirements |
| --- | --- | --- |
| Core capabilities | 50 | F-01, F-02 |
| Operability | 30 | N-01, N-02 |
| Cost | 20 | C-01, C-02 |

## Weighted score matrix

| Criterion | Weight | Beta Queue | Alpha Queue |
| --- | --- | --- | --- |
| Core capabilities | 50 | 5 (high) | 4 (high) |
| Operability | 30 | 2† (low) | 4 (medium) |
| Cost | 20 | 4 (medium) | 3 (medium) |
| **Total** | 100 | **78.0** | **76.0** |

Contribution of a criterion = score / 5 × weight. † capped for weak evidence. Confidence: high = two sources, medium = one, low = none.

## Bias and assumptions

- Providers were not recorded, so concentration could not be checked.
- Requirements based on an assumption: none.
- Findings by source kind: Alpha Queue 1 vendor, 4 independent or open-source docs; Beta Queue 1 vendor, 3 independent or open-source docs.
- Cost comparison covers 2 of 2 options with a complete price.

This is a fictional sample evaluation with two profiled options; providers were not recorded.

## Cost

Currency USD, horizon 36 months. Assumptions: Jobs per month 5,000,000 jobs/month; Developers 4 people.

| Option | Priced monthly | One-time | Total over horizon | Not priced |
| --- | --- | --- | --- | --- |
| Alpha Queue | 1,260 | 0 | 45,360 | none |
| Beta Queue | 380 | 2,000 | 15,680 | none |

Both options have a complete price, so cost can be compared directly; see the table above.

## Feature-by-feature comparison

The full table, with notes and evidence ids in every cell, is in `eval/features.md` and in the exported report. Must-have summary:

| Option | provided | vendor-claimed | partial | not provided | unknown |
| --- | --- | --- | --- | --- | --- |
| Beta Queue | 2 | 0 | 1 | 0 | 0 |
| Alpha Queue | 2 | 0 | 1 | 0 | 0 |

## Sensitivity

Moving each of the highest weights by 5 points never changes the top option. Lowering low-confidence scores changes the top option in 2 test(s).

Moving the top weights by 5 points never changes the leader; lowering low-confidence scores does, which is why confidence is low.

## Recommended next steps

1. Verify Beta Queue's metrics support with a short proof of concept (E-008).
2. Ask the Beta vendor for independent operability evidence before committing.

## Risks and open questions

- Beta Queue's operability claims are vendor-only and unverified.
- The near-tie means a small change in weights or evidence can reverse the order.

## Excluded options

| Option | Reason |
| --- | --- |
| Gamma Queue | Fails F-01: no at-least-once delivery (E-010) |

Gamma Queue fails the at-least-once delivery gate (E-010), so it is not ranked.

## Sources

Every finding, with its source, source date, gathered date and label.

| ID | Option | Req | Finding | Source | Source date | Label | Kind |
| --- | --- | --- | --- | --- | --- | --- | --- |
| E-001 | Alpha Queue | F-01 | Delivers at least once under failure injection | https://bench.example.org/alpha | 2026-08-01 | CONFIRMED | independent |
| E-002 | Alpha Queue | F-02 | Delayed jobs supported, recurring schedules are not | https://review.example.net/alpha | 2026-07-15 | PROBABLE | independent |
| E-003 | Alpha Queue | N-01 | Exposes Prometheus metrics and a health endpoint | https://review.example.net/alpha | 2026-07-15 | PROBABLE | independent |
| E-004 | Alpha Queue | C-01 | Tiered pricing with a volume discount above 1M jobs | https://alpha.example.com/pricing | 2026-09-01 | PRIMARY | vendor |
| E-005 | Alpha Queue | C-02 | Free tier of 100k jobs per month | https://bench.example.org/alpha | 2026-08-01 | PROBABLE | independent |
| E-006 | Beta Queue | F-01 | At-least-once delivery confirmed in tests | https://bench.example.org/beta | 2026-08-01 | CONFIRMED | independent |
| E-007 | Beta Queue | F-02 | Delayed and recurring jobs supported | https://docs-mirror.example.net/beta | 2026-06-20 | PROBABLE | independent |
| E-008 | Beta Queue | N-01 | Vendor says metrics are available through a plugin | https://beta.example.com/docs/ops | 2026-09-10 | UNVERIFIED | vendor |
| E-009 | Beta Queue | C-01 | Open source; hosting cost is predictable | https://review.example.net/beta | 2026-07-15 | PROBABLE | independent |
| E-010 | Gamma Queue | F-01 | At-most-once delivery only | https://bench.example.org/gamma | 2026-08-01 | CONFIRMED | independent |
