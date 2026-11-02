# Evaluation report: background task queue

Evaluation date 2026-10-01. Scale 0 to 5. Cost mode: weighted.

## Eligibility

**Eligibility: 2 of 3 options pass every gate.**

- Gamma Queue: F-01 not met: At-most-once delivery only; Documentation states the weaker guarantee.

## Decision recommendation

Alpha Queue leads Beta Queue by about one point, so the choice is not clear-cut and should be treated as a near-tie. Alpha's edge is operability, where its documentation is independent and Beta's metrics rest on a vendor claim.

**Confidence: medium.** The lead holds in all six scenarios but is far smaller than the 5-point meaningful gap, and Beta's operability evidence is vendor-only.

## Decision table

| Rank | Option | Score | Gates | Low-confidence criteria | Main strength | Main gap |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Alpha Queue | 71.6 | F-01 pass (tested), N-03 pass (documented) |  | Documented operations and independent delivery tests | No recurring schedules |
| 2 | Beta Queue | 70.5 | F-01 pass (documented), N-03 pass (vendor_confirmed) | 1 | Strong core and low hosting cost | Metrics support is a vendor claim |

Near-tie (within 5 points): Alpha Queue, Beta Queue; broken by fewer must-have gaps.

## Context

A small team needs a queue for background jobs (emails, report generation) in an existing web application. The decision is which queue product to adopt. This is a fictional sample evaluation used to test the eval skills.

Incumbent role: replace (the team has no queue today).

## Packages scored

| Option | Component | Version | Released | Lifecycle | Newest release on the evaluation date | Compatibility |
| --- | --- | --- | --- | --- | --- | --- |
| Alpha Queue | Alpha Queue server | 4.2.1 | 2026-06-10 | supported | 4.2.1 |  |
| Alpha Queue | Alpha Queue worker SDK | 4.2.0 | 2026-05-02 | supported | 4.2.0 | Works with server 4.x |
| Beta Queue | Beta Queue | 2.4.0 | 2026-04-15 | lts | 2.5.0 | Metrics plugin 1.3 tested with 2.4 |

## Recommended next steps

1. Run POC test P2 (offline install and upgrade) for Alpha and verify Beta's metrics plugin before choosing.

## Gates

**G-1** (F-01). Passes only if all hold: Delivery is at least once when a worker crashes mid-job; The behaviour is shown in a test or in the official documentation. Package rule: Every component of the package must keep the guarantee

| Option | Verdict | Basis | Confirm by | Clause notes |
| --- | --- | --- | --- | --- |
| Alpha Queue | PASS | tested |  | 1. Independent benchmark kills workers; no job lost; 2. Benchmark publishes the result |
| Beta Queue | PASS | documented | POC test P1: kill a worker mid-job and count delivered jobs | 1. Confirmed in tests by a third party; 2. Documented guarantee |
| Gamma Queue | NOT MET |  |  | 1. At-most-once delivery only; 2. Documentation states the weaker guarantee |

**G-2** (N-03). Passes only if all hold: Installation works without internet access; Upgrades work without internet access; Licence validation works without a vendor service. Package rule: Every component of the package must satisfy every clause

| Option | Verdict | Basis | Confirm by | Clause notes |
| --- | --- | --- | --- | --- |
| Alpha Queue | PASS | documented | POC test P2: install, upgrade and start in an isolated network | 1. Offline installer documented; 2. Offline upgrade bundle documented; 3. Licence is a signed file checked locally |
| Beta Queue | PASS | vendor_confirmed |  | 1. Open source; installs from a local mirror; 2. Upgrades from a local mirror; 3. No licence needed |

## Excluded options

| Option | Reason |
| --- | --- |
| Gamma Queue | Fails F-01: no at-least-once delivery (E-010) |

Gamma Queue fails the delivery gate (at-most-once only).

## Criteria and weights

| Criterion | Weight | Requirements |
| --- | --- | --- |
| Core capabilities | 50 | F-01, F-02 |
| Operability | 30 | N-01, N-02, N-03 |
| Cost | 20 | C-01, C-02 |

## Weighted score matrix

| Criterion | Weight | Alpha Queue | Beta Queue |
| --- | --- | --- | --- |
| Core capabilities | 50 | 3.62 (medium) | 4 (medium) |
| Operability | 30 | 3.64 (medium) | 2.91 (low) |
| Cost | 20 | 3.38 (medium) | 3.25 (medium) |
| **Total** | 100 | **71.6** | **70.5** |

Contribution of a criterion = score / 5 × weight. † capped for weak evidence. Confidence: high = two sources, medium = one, low = none.

## Sensitivity

Moving each of the highest weights by 5 points never changes the top option. Lowering low-confidence scores never changes the top option.

The ranking holds when the largest weights move by 5 points and when low-confidence scores drop by one.

## Bias and assumptions

- Providers were not recorded, so concentration could not be checked.
- Requirements based on an assumption: none.
- Findings by source kind: Alpha Queue 2 vendor, 4 independent or open-source docs; Beta Queue 2 vendor, 3 independent or open-source docs.
- Cost comparison covers 2 of 2 options with a complete price.

Only two options were profiled, both from different providers.

## Cost

Currency USD, horizon 36 months. Assumptions: Jobs per month 5,000,000 jobs/month; Developers 4 people.

| Option | Priced monthly | One-time | Total over horizon | Not priced |
| --- | --- | --- | --- | --- |
| Alpha Queue | 1,260 | 0 | 45,360 | none |
| Beta Queue | 380 | 2,000 | 15,680 | none |

Beta is cheaper over 36 months; cost is part of the weighted score.

## POC tests

| Test | Option | Linked to | What it must show | Owner | Status |
| --- | --- | --- | --- | --- | --- |
| P1 | Beta Queue | G-1 | Does Beta redeliver a job when a worker is killed mid-job? | platform team | open |
| P2 | Alpha Queue | G-2 | Do install, upgrade and licence start work in an isolated network? | platform team | open |

## Open verification items

| ID | Option | Linked to | Question | Type | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- |
| OI-3 | Beta Queue | N-01 | Which metrics does the plugin export, and is it supported by the vendor? | vendor_question | procurement | open |

## Verify before deciding

The cells that decide the result; check them by hand before relying on it.

- Gate G-1 for Alpha Queue: PASS (tested).
- Gate G-1 for Beta Queue: PASS (documented).
- Gate G-1 for Gamma Queue: NOT MET.
- Gate G-2 for Alpha Queue: PASS (documented).
- Gate G-2 for Beta Queue: PASS (vendor_confirmed).
- N-01: Alpha Queue scores 4 against 2 for Beta Queue (+5.5 points).

## Feature-by-feature comparison

The full table, with notes and evidence ids in every cell, is in `eval/features.md` and in the exported report. Must-have summary:

| Option | meets (4-5) | limits (3) | partial (2) | workaround (1) | not met (0) |
| --- | --- | --- | --- | --- | --- |
| Alpha Queue | 3 | 1 | 0 | 0 | 0 |
| Beta Queue | 3 | 0 | 1 | 0 | 0 |

## Candidate requirements

Found while researching and not scored. Accepting one goes back to eval-define.

| ID | Requirement | Suggested priority | Category | Why | Source |
| --- | --- | --- | --- | --- | --- |
| CR-1 | Jobs can be replayed from a dead-letter queue by operators | should | Operations | Found while profiling Alpha: failed jobs are kept only for seven days | E-002 |

## Risks and open questions

- Beta's operability evidence comes only from the vendor.

Not assessed: Operating effort and team skills; Lock-in and exit cost. These can decide a close call.


### Changes since evidence was gathered

Nothing relevant has been released since the evidence date.

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
| E-011 | Alpha Queue | N-03 | Offline installer, upgrade bundle and signed licence file are documented | https://alpha.example.com/docs/offline | 2026-09-01 | PRIMARY | vendor |
| E-012 | Beta Queue | N-03 | Vendor confirmed in writing that every component installs and upgrades from a local mirror | https://beta.example.com/support/confirmation-42 | 2026-09-20 | CONFIRMED | vendor |
