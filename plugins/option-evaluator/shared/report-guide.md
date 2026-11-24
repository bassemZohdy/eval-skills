# Report guide: write and check `eval/report.md` by hand

This plugin ships no scripts and no exports. You write `eval/report.md` yourself as UTF-8 Markdown with LF line endings. Copy every number from the evaluation files; never compute or round a number in the report, and never invent one. If a file disagrees with what you want to say, fix the file's step, not the report. Do the self-check (section 4) before you show the report.

Keys below name fields of the eval files: `scores.json` (S), `criteria.json` (C), `options.json` (O), `evidence.json` (E), `cost.json` (K), `status.json` (T), `open_items.json` (I), `solution.md`, `candidate_requirements.json`. "Short name" means the option name cut before the first ` (`. In table cells replace `|` with `/` and line breaks with a space.

## 1. Sections: order, headings, opening

Title: `# Evaluation report: <title>`. The title is the first `# ` heading of `solution.md` without a leading `Solution: `; if there is none, `T.solution_slug`, or `evaluation`.

Opening provenance line, the first non-blank line under the title, exactly:
`Evaluation date <T.evaluation_date or n/a>. Scale 0 to <C.scale.max>. Cost mode: <C.cost_mode>` then, only when the mode is `separate`, ` (cost is shown beside the score, not in it)`, then `.` and a space, then the provenance prose (reruns, how the evidence was gathered). If `T.post_scoring_weight_change` is true, add ` Weights were changed after scoring: <T.weight_change_reason without its final period>.`

Section order (level-2 headings, `## `). Use these headings and this order; omit a section only where the rule says so.

| # | Heading | Present |
| --- | --- | --- |
| 1 | Eligibility | only if a profiled option has a gate `fail` or `unverified` (see below) |
| 2 | Decision recommendation | always |
| 3 | Decision table | always |
| 4 | Context | always |
| 5 | Packages scored | if any option in O has a `package` object |
| 6 | Recommended next steps | always |
| 7 | Gates | always |
| 8 | Excluded options | always |
| 9 | Criteria and weights | always |
| 10 | Weighted score matrix | always |
| 11 | Sensitivity | always |
| 12 | Bias and assumptions | always |
| 13 | Cost | always (heading and prose even when there is no cost data) |
| 14 | Option profiles | only if you write profiles |
| 15 | POC tests | if `open_items.json` has items with `owner_type` `poc_test` |
| 16 | Open verification items | if it has items of another `owner_type` |
| 17 | Verify before deciding | if `S.deciding_cells` has `gates` or `requirements` |
| 18 | Comparison with an earlier assessment | only if the user supplied one (goes here) |
| 19 | Feature-by-feature comparison | always (the heading must start with `Feature`) |
| 20 | Candidate requirements | if `candidate_requirements.json` is non-empty |
| 21 | Risks and open questions | always |
| 22 | Sources | always |

A heading that is not in this list stays after the section before it. `### Changes since evidence was gathered` is a level-3 heading inside section 21, after the "Not assessed:" line.

### Eligibility (section 1) and the shortlist case

Consider only options in O with `not_profiled` false. A profiled option is blocked if any value of its `gate_status` is `fail` or `unverified`. If at least one is blocked, write:

- `## Eligibility`, then `**Eligibility: P of T options pass every gate.**` (P = options with no blocked gate, T = profiled options), then one bullet per blocked option in O order: `- <full option name>: <blocker>; <blocker>.`
- A blocker is `<requirement id> not met` (for `fail`) or `<requirement id> unverified`, followed by `: ` and the clause notes joined with `; ` when there are notes. The notes are the `note` of every clause of that option in the gate whose `requirement_id` is that id, whose `met` is not `true`, from `C.gates[].verdicts[option].clauses`.

If no option passes every gate (P = 0 and T > 0), write a short report only: the title (from `T.solution_slug`, or `evaluation`), the Eligibility section, `## Decision recommendation` (shortlist the options and close their blockers; never recommend or "choose" an option; never use the phrase "recommended option"), `**Confidence: low.** <why>` (default why: no ranking is given because no option is eligible), and `## Recommended next steps` as a numbered list. No other section, no provenance line, no tables.

## 2. Computed sections (copy from the files)

Rank order means the order of `S.ranking` (best first), which holds only the scored options. `%.1f` means one decimal.

**Decision table.** Columns: `Rank | Option | Score | Gates | Low-confidence criteria | Main strength | Main gap`. One row per option in `S.ranking`, rank 1, 2, 3... Option is the short name. Score is `S.totals[option]` with one decimal. Gates is, for each entry of the option's `O.gate_status` in file order, `<requirement id> <status>` joined with `, `, and ` (<basis>)` appended when the gate verdict of that option for that requirement has a non-empty `basis` (`C.gates[].verdicts[option].basis`). Low-confidence criteria is the number of criteria with weight above 0 whose `S.criterion_scores[option][criterion].confidence` is `low`; leave the cell empty when the number is 0. Strength and gap are your prose.
After the table, one line per entry of `S.ties`: `Near-tie (within <S.mapping.tie_margin> points): <short names joined with ", ">; broken by <tie_break>.` Then, for each option in `S.could_overtake_leader`: `<short name> could overtake <short name of rank 1> if its unknown requirements turned out to be provided.`

**Context.** The text of `solution.md` without its first heading line, trimmed.

**Packages scored.** Columns: `Option | Component | Version | Released | Lifecycle | Newest release on the evaluation date | Compatibility`. One row per component of every option that has a `package` object, in O file order (not rank order): short name, `name`, `version`, `release_date`, `lifecycle`, `newest_release`, `compatibility` (empty if absent).

**Gates.** If `C.gates` is empty write `No gate rubric was recorded.` Otherwise, per gate in file order: the line `**<id>** (<requirement_id>). Passes only if all hold: <pass_clauses joined with "; ">. Package rule: <package_rule>`, a blank line, then the table `Option | Verdict | Basis | Confirm by | Clause notes`, one row per option in `verdicts` (file order, every option including excluded ones): short name, `verdict` as written (for example PASS, NOT MET), `basis`, `confirm_by`, and the clause notes as `1. <note>; 2. <note>`.

**Excluded options.** If any entry of `S.excluded` has a reason other than `not profiled`, a table `Option | Reason` with the full option name and the reason as written. Then one prose line: your `excluded` text, or `No profiled option failed a gate.` when nothing failed (the line is required when something failed). If any option has `not_profiled` true, add `Listed but not profiled: <full names joined with ", ">.`

**Criteria and weights.** Columns: `Criterion | Weight | Requirements`. One row per criterion in `C.criteria` (including weight 0), file order: name, weight, requirement ids joined with `, `.

**Weighted score matrix.** Columns: `Criterion | Weight | <short name of each ranked option, in rank order>`. One row per criterion with weight above 0, file order. Cell = `<score> (<confidence>)` from `S.criterion_scores[option][criterion]`; the score has up to two decimals with trailing zeros removed (3.636 becomes 3.64, 4.0 becomes 4), and a `†` right after the score when `capped` is true. Last row: `**Total** | 100 | **<S.totals, one decimal>**` per option. Under the table, exactly: `Contribution of a criterion = score / <scale max> × weight. † capped for weak evidence. Confidence: high = two sources, medium = one, low = none.`

**Sensitivity.** Opening sentence: `Moving each of the highest weights by 5 points <A>. Lowering low-confidence scores <B>.` A = `never changes the top option` if no entry of `S.sensitivity` has `changed` true, otherwise `changes the top option in X of N tests` (X = entries with `changed` true, N = number of entries). B = `never changes the top option` if no entry of `S.confidence_tests` has `changed` true, otherwise `changes the top option in X test(s)`. Then your `sensitivity` prose.

**Bias and assumptions.** Bullets from `S.bias_checks`, then your `bias` prose after a blank line:
- If `provider_concentration.counts` exists: `Providers behind the profiled options: <name> <count>, ... (largest share <largest_share x 100, rounded>%).` Otherwise: `Providers were not recorded, so concentration could not be checked.`
- `Requirements based on an assumption: <ids, with " (gate)" after a gate requirement, joined with ", ", or none>.`
- If `source_mix` is present: `Findings by source kind: <short name> <vendor> vendor, <independent_or_open_source> independent or open-source docs; ...` (one clause per option, joined with `; `, ending with a period).
- If `cost_comparable` is present: `Cost comparison covers <complete> of <total> options with a complete price.`

**Cost.** If `K.results` exists: `Currency <currency>, horizon <horizon_months> months. Assumptions: <name> <value with thousands separators> <unit>; ...` (period at the end), then the table `Option | Priced monthly | One-time | Total over horizon | Not priced`, one row per option in `K.results.options` order that is in O: short name, `monthly` and `one_time` as whole numbers with thousands separators, `tco` as a whole number with thousands separators plus ` + quote` when `incomplete` is true, and the names of components with `price_unknown` true joined with `, ` (else `none`). Then your `cost` prose, which states the cheapest option over the horizon, how cost enters the ranking (in the score, or beside it), any component priced from unverified or missing evidence, and the volume scenarios and the cheapest option in each (from `K.results.options[].scenarios`).

**Option profiles** (only if written). For each ranked option in rank order that has a profile: `**<short name>.** <text>` with a blank line after. Text: strengths, blockers and risks only.

**POC tests.** Columns: `Test | Option | Linked to | What it must show | Owner | Status`; one row per item with `owner_type` `poc_test`, file order: `test_id`, short name of `option` (the raw id if it is not an option), `linked`, `question`, `owner`, `status`.

**Open verification items.** Columns: `ID | Option | Linked to | Question | Type | Owner | Status`; one row per other item: `id`, option as above, `linked`, `question`, `owner_type`, `owner`, `status`.

**Verify before deciding.** Intro line `The cells that decide the result; check them by hand before relying on it.` Then bullets from `S.deciding_cells`: for each `gates` entry `- Gate <gate> for <short name>: <verdict>` plus ` (<basis>)` if basis is non-empty, then a period; for each `requirements` entry `- <requirement_id>: <leader short name> scores <leader_score> against <runner_up_score> for <runner_up short name> (<points with sign and one decimal> points).`

**Feature-by-feature comparison.** Say: `The full table, with notes and evidence ids in every cell, is in `eval/features.md`. Must-have summary:` then the table `Option | <the keys of S.must_summary of the first option, in order>` with one row per ranked option (rank order): short name and each count (0 if missing).

**Candidate requirements** (only if non-empty). Intro `Found while researching and not scored. Accepting one goes back to eval-define.` Then `ID | Requirement | Suggested priority | Category | Why | Source` from `id`, `text`, `suggested_priority`, `suggested_category`, `why`, `source`.

**Risks and open questions.** Bullets `- ...` (prose). Then, if `C.not_assessed` is non-empty, a blank line and `Not assessed: <factors joined with "; ">. These can decide a close call.` Then, if you have something new from the freshness sweep, `### Changes since evidence was gathered` and your `changes` text.

**Sources.** Intro `Every finding, with its source, source date, gathered date and label.` Table `ID | Option | Req | Finding | Source | Source date | Label | Kind`, one row per entry of `evidence.json` in file order: `evidence_id`; short name of the option (the raw id if it is not an option); `requirement_id`, else `criterion_id`, else empty; `finding` cut at 220 characters; `source_url`; `source_date`; `confidence` (the label); `source_kind`, with ` (from source code, POC candidate)` appended when `source_kind` is `source_code` and `tested` is not true, and ` (out of scope)` appended when `scope` is `out_of_scope`. The report is keyed by evidence id; it does not number documents.

## 3. Prose you write

Write only what the files support. Keep each item short.

- **Recommendation** (under `## Decision recommendation`, one or two sentences). Name the rank-1 option first: no other option's name may appear earlier in the text. Give the lead as `S.lead` points; if you write "by N points", N must be within 0.55 of `S.lead`. Name the main condition under which the recommendation would change. If `S.ties` is non-empty, say the choice is a near-tie or not clear-cut. If `S.could_overtake_leader` is non-empty, say unknown requirements could let another option overtake. Mention an excluded option only in a sentence that says it failed a gate, was excluded, ruled out, not eligible or ineligible.
- **Confidence line**, right after it: `**Confidence: high.** <why>` (or medium or low). Use only the words high, medium or low, never a percentage or a number near the word confidence. Levels:
  - high: no scenario in `S.scenarios` changes the leader (`S.order_changes` starts with `0 of`), the lead `S.lead` is at least `S.meaningful_gap`, and the key scores rest on independent evidence.
  - medium: the margin holds but some key scores are low-confidence.
  - low: a near-tie, a flip under sensitivity, more than half of the total weight resting on low-confidence scores, or unknown requirements that could let another option overtake the leader. A shortlist report is always low.
- **confidence_why**: the sentence(s) after the level giving the reasons above, with the numbers from the files.
- **Near-tie wording.** When `S.ties` is non-empty, the lead is below `S.meaningful_gap`, or `S.order_changes` does not start with `0 of`, never call the result decisive. Avoid: decisive, decisively, clear winner, clearly best, clearly ahead, clearly better, by a wide margin, comfortably, undisputed, outright. Say the choice is not clear-cut and name what would settle it.
- **Per option**: one phrase for the main strength and one for the main gap, in the decision table.
- **Profiles** (optional): strengths, blockers and risks per option.
- **bias**: what the bias checks limit about the recommendation. **cost**: see Cost above. **sensitivity**: what moves the ranking and what does not.
- **next_steps**: two to four concrete actions as a numbered list `1. ...`, for example a POC on the riskiest requirement, a question to put to a vendor, or evidence to refresh. Do not repeat a POC test or open item you already list; refer to its id.
- **risks**: at most 10 bullets. Unverified claims that touch the recommendation, assumptions, evidence flagged stale with its gathered date. A risk must not restate a gate clause, a gate pass clause or an open item question (see check 17).
- **excluded**: one sentence per excluded option on the gate it failed, in the Excluded options section.
- **changes** (optional): what is new since the evidence was gathered, or that nothing relevant is. Do not change scores here; scores change only by rerunning the scoring step.
- **provenance**: the reruns and how the evidence was gathered, appended to the opening line.
- **Never** write process history: the words "this round", "rechecked" or "re-checked", "revalidated" or "re-validated", "previous round", "last round", "earlier round", "next round", "round 1" (any digit) are banned anywhere in the report, sources table included. The method history lives in `eval/status.json`.
- The report adds no fact that is not in the evidence file, apart from context the user gave in the solution file.
- A `TODO(prose)` marker must not remain anywhere.

## 4. Self-check before review

Read the finished `eval/report.md` and tick every line. Fix and recheck until all hold.

1. The file exists, is not empty, and contains no `TODO(prose)` text.
2. If a profiled option has a `fail` or `unverified` gate, the report contains `Eligibility: P of T options pass every gate` with the correct counts, and the blockers follow.
3. If no option passes every gate: no sentence says "recommended option" or "Choose <Name>"; no other section is required; stop here after checks 1 and 2.
4. These headings exist (each heading may continue after the listed words): Decision recommendation, Decision table, Context, Recommended next steps, Criteria and weights, Weighted score matrix, Bias and assumptions, Cost, Sensitivity, Feature, Risks and open questions, Sources.
5. The `## ` headings that appear in the section table of section 1 are in that table's order.
6. No banned process wording appears (this round, re-checked, re-validated, previous/last/earlier/next round, round N), anywhere.
7. The first non-blank line under the title starts with `Evaluation date <date>. Scale 0 to <n>. Cost mode: <mode>` and agrees with `status.json` and `criteria.json`.
8. The Decision recommendation names the rank-1 option (short name), and no other ranked option's name appears before it.
9. The recommendation contains `Confidence: high`, `medium` or `low`, and no percentage appears within about 40 characters after the word confidence anywhere in the report.
10. If the level is high: `S.order_changes` starts with `0 of` and `S.lead` is at least `S.meaningful_gap`.
11. Every ranked option's total, with one decimal, appears in the report.
12. The Decision table rows are in `S.ranking` order, with each row's Score equal to `S.totals` at one decimal.
13. If `S.ties` is non-empty, the recommendation says near-tie, tie, not clear-cut or undecided.
14. If `S.could_overtake_leader` is non-empty, the recommendation says unknown, overtake or undecided.
15. If the result is close (ties, lead below the meaningful gap, or order changes under sensitivity), the recommendation contains none of the decisive words listed in section 3.
16. Any "by N points" in the recommendation has N within 0.55 of `S.lead`.
17. Risks and open questions has at most 10 bullets, and none repeats a gate pass clause, a clause note or an open item question (judge by sharing most of the same distinctive words).
18. If `C.not_assessed` is non-empty, a `Not assessed:` line exists and names every factor on that same line.
19. Every excluded option (reason other than `not profiled`) is named in the report and listed under `## Excluded options` with the gate it failed.
20. Any sentence of the recommendation that names an excluded option says it failed, was excluded, is not eligible, failed a gate, was not met or was ruled out.
21. Every number in the computed sections equals the value in the files (totals, weights, scores, costs, counts, dates); no figure was recomputed or rounded by you.
