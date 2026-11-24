# Validation checklist for the `eval/` workspace

**How to use this**
1. Open each `eval/` file the current step needs (section 2 lists them), run its checks (section 1), then the cross-file checks (section 3), in that order.
2. Collect every problem first, then report them all at once in plain words. Name the file and the row (for example `evidence.json` row 3, id E-004), and name the skill that writes the file (section 0).
3. **Error** = stop, do not continue the step, tell the user which skill to rerun or fix. **Warning** = continue, but tell the user.
4. Never guess around a missing, unreadable or half-written file. Never invent a value to make a check pass.

Terms: "nonblank" = present and not empty after trimming spaces. "known id" = an id that exists in the file that defines it. "Retired" requirements (`retired: true`) keep their ids but are ignored by scoring. A key listed as "required" must be present, but any other rule on it applies only when stated. If a row is not an object, or a required key is missing, report one Error ("row N must be an object" or "row N is missing keys: ...") and skip the other checks for that row.

## 0. Which skill writes which file
| File | Written by |
| --- | --- |
| `solution.md`, `requirements.md`, `requirements.json` | eval-define |
| `criteria.md`, `criteria.json` | eval-analyze |
| `options.md`, `options.json`, `evidence.json`, `cost.json` | eval-discover |
| `scores.json`, `features.md` | eval-compare |
| `report.md` | eval-report |
| `status.json` | every eval skill |
| `open_items.json`, `candidate_requirements.json`, `features.json` | discover and compare (not a step file) |

- **Error** if a file you read is not valid JSON: "<file> cannot be read as JSON; rerun <writing skill>".
- A file that is not required for the current step and does not exist is simply skipped. A file that exists is always checked.

## 1. Checks by file

### 1.1 status.json
Required keys: `current_step`, `completed_steps`, `stale_steps`, `stale_evidence`, `evaluation_date`, `report_date`, `solution_slug`. Step names are, in order: define, analyze, discover, compare, report.

| Rule | Level |
| --- | --- |
| `post_scoring_weight_change` is true but `weight_change_reason` is blank | Error |
| `completed_steps` and `stale_steps` must each be a list containing only step names (stop checking this file if not) | Error |
| `evaluation_date` and `report_date`, when non-empty, must be `YYYY-MM-DD` | Error |
| both dates valid and `report_date` is earlier than `evaluation_date` | Error |
| a step is in `completed_steps` but an earlier step is not (steps complete in order; report only the first such case, name the earliest missing step's skill) | Error |

### 1.2 requirements.json
A non-empty list, otherwise **Error**. Required keys per row: `id`, `type`, `category`, `text`, `priority`, `gate`, `verification_note`.

| Rule | Level |
| --- | --- |
| `id` is unique in the file | Error |
| `retired`, if present, is exactly true or false | Error |
| `type` is `functional` or `non-functional` | Error |
| `priority` is `must`, `should` or `could` | Error |
| `evidence_class`, if present, is `feature` or `measure` | Error |
| `basis`, if present, is `stated` or `assumed` | Error |
| `text` is nonblank | Error |
| `gate` is a real boolean (true or false), not text | Error |
| `gate` is true and `gate_scope` is blank | Error |
| at least one requirement has a `category` containing the word "cost" (any letter case) | Error |
| `text` contains a vague word and contains no threshold (see below) | Warning |

- Vague words (whole words, any letter case): fast, quick, quickly, secure, scalable, robust, performant, user-friendly (or "user friendly"), easy to use, intuitive, high-performance (or "high performance"), reliable, efficient, flexible, modern, seamless, seamlessly.
- A threshold is any one of: a digit anywhere in the text; the letters TBD; "to be set", "to be agreed" or "to be confirmed"; text in angle brackets such as `<value>`; text in square brackets such as `[value]`.
- Warning wording: name the requirement id and the vague word; ask for a measurable threshold or an explicit placeholder such as TBD.

### 1.3 criteria.json (including gates)
Required top-level keys: `cost_mode`, `scale`, `criteria`. Requirement ids used below exclude retired ones where stated.

| Rule | Level |
| --- | --- |
| `cost_mode` is `weighted` or `separate` | Error |
| `scale` is an object with `min` and `max`, and `max` is greater than `min` | Error |
| `scale.min` is 0 | Error |
| each criterion has `id`, `name`, `category`, `weight`, `requirement_ids`, `anchors`; `id` unique | Error |
| `anchors` is an object with the keys `"0"`, `"3"` and `"5"` | Error |
| `weight` is a whole number (this edition always scores on the anchored model) | Error |
| `weight` is above 0 and the criterion lists fewer than 2 requirement ids (a scored category needs at least two) | Error |
| `cost_mode` is `separate`, the criterion's `category` contains "cost", and `weight` is not 0 | Error |
| a listed requirement id is retired ("remove it from the criterion") | Error |
| a listed requirement id is not a known requirement id (skip if requirements.json has no ids) | Error |
| all criterion weights sum to exactly 100 | Error |
| every non-retired requirement appears in exactly one criterion's `requirement_ids` (report "covered by N criteria") | Error |

**Gates** (the `gates` list; if the key is absent skip this whole block; if present it must be a list, else Error). A "gate requirement" is a requirement with `gate: true`. An option "in play" is one with `excluded` not true and `not_profiled` not true.

| Rule | Level |
| --- | --- |
| every non-retired gate requirement has a gate entry whose `requirement_id` is that requirement ("eval-analyze writes one for every gate") | Error |
| each gate has `id`, `requirement_id`, `pass_clauses`, `evidence_needed`, `package_rule`, `verdicts` | Error |
| gate `id` is unique | Error |
| gate `requirement_id` is a gate requirement | Error |
| `pass_clauses` is a non-empty list | Error |
| for every option in play, `verdicts` has an entry for that option | Error |
| for every option in play, options.json `gate_status` has an entry for the gate's `requirement_id` | Error |
| a verdict's option id is a known option | Error |
| `verdict` is `PASS`, `NOT MET` or `UNVERIFIED` | Error |
| the verdict's `clauses` list has exactly one entry per pass clause | Error |
| each clause is an object with `met` of true, false or null, and a nonblank `note` | Error |
| a clause with `met` true or false has a non-empty `evidence_ids` list (judged only from evidence rows) | Error |
| every id in a clause's `evidence_ids` is a known evidence id | Error |
| verdict is `PASS` and any clause is not true (false or null) | Error |
| verdict is `NOT MET` and no clause is false | Error |
| verdict is `UNVERIFIED` and some clause is false (it must then be `NOT MET`) | Error |
| verdict is `PASS` and `basis` is not `documented`, `vendor_confirmed` or `tested` | Error |
| verdict is `PASS`, `basis` is `documented` and `confirm_by` is blank | Error |
| options.json `gate_status` for that option and gate is set, is not `waived_by_user`, and disagrees with the verdict (`PASS` = pass, `NOT MET` = fail, `UNVERIFIED` = unverified) | Error |

The three verdict-consistency rules, the basis rules and the `gate_status` agreement rule apply only to verdicts whose clause list is well formed (the count and every clause shape above are fine).

### 1.4 options.json
A list, otherwise **Error**. Required keys per row: `option_id`, `name`, `source_links`, `excluded`, `exclusion_reason`, `not_profiled`, `gate_status`.

| Rule | Level |
| --- | --- |
| `option_id` is unique | Error |
| `name` is unique ignoring letter case and surrounding spaces | Error |
| `provider`, if the key is present, is a nonblank text | Error |
| `oss_base`, if present, is null or an object whose `project`, `ref` and `source` are all nonblank (null = checked, none; a missing key = not checked, which is allowed) | Error |
| `excluded` is true and `exclusion_reason` is blank | Error |
| each `gate_status` value is `pass`, `fail`, `unverified` or `waived_by_user` | Error |
| each `gate_status` key is a gate requirement id (skip if the evaluation has no gate requirements) | Error |

**Package** (only if the `package` key is present):

| Rule | Level |
| --- | --- |
| a text package is nonblank (it names the editions and versions evaluated) | Error |
| otherwise it is an object with a non-empty `components` list | Error |
| each component has `name`, `version`, `release_date`, `lifecycle` | Error |
| `lifecycle` is `supported`, `lts` or `outside_matrix` | Error |
| `lifecycle` is `outside_matrix` | Warning |
| more than one component and none has a nonblank `compatibility` | Warning |

### 1.5 evidence.json
A list, otherwise **Error**. Required keys per row: `evidence_id`, `option_id`, `finding`, `source_url`, `source_date`, `gathered_on`, `confidence`, `source_kind`.

| Rule | Level |
| --- | --- |
| `evidence_id` is unique and never reused | Error |
| the row has a `requirement_id` and/or a `criterion_id` (at least one nonblank) | Error |
| `confidence` is one of PRIMARY, CONFIRMED, PROBABLE, UNVERIFIED, COULD NOT VERIFY, DISPUTED | Error |
| `confidence` is CONFIRMED and `source_kind` is `vendor` (a vendor statement alone is PRIMARY, as an attributed statement) | Warning |
| `confidence` is PRIMARY and `source_kind` is `independent` (one independent source is PROBABLE, two that agree are CONFIRMED) | Warning |
| `finding` or `source_url` is blank | Error |
| `source_kind` is `vendor`, `independent`, `oss_project_docs` or `source_code` | Error |
| `scope`, if present, is `in_scope` or `out_of_scope` | Error |
| `option_id` is a known option (skip if no options) | Error |
| `requirement_id`, if given, is a known requirement id, retired ones included (skip if no requirements) | Error |
| `criterion_id`, if given, is a known criterion id (skip if no criteria) | Error |

**Dates**
| Rule | Level |
| --- | --- |
| `gathered_on` is a `YYYY-MM-DD` date | Error |
| `gathered_on` is later than today | Error |
| `source_date` is `unknown` (any letter case): no further date check | OK |
| otherwise `source_date` is `YYYY-MM-DD` or `YYYY-MM` (an empty value fails) | Error |
| `source_date` is after `gathered_on` (compare year and month only if `source_date` is a month; skip if `gathered_on` was invalid) | Error |

**Source code** (`source_kind` is `source_code`)
| Rule | Level |
| --- | --- |
| an `@` appears in `source_url` or in `pin` (path@commit) | Error |
| `lines` is nonblank (a line range such as 120-148) | Error |
| `confidence` is PRIMARY or CONFIRMED and `tested` is not true (reading code is PROBABLE at best unless a test proves it) | Error |

**Pins**
| Rule | Level |
| --- | --- |
| `pin` is `latest` (any letter case) and `source_date` is blank or `unknown` | Error |
| `source_class`, if present, is `primary`, `company` or `secondary` | Error |
| `source_url` contains `/main/` or `/master/` (moving branch; cite a tag or commit) | Warning |
| some rows have a blank or missing `pin`: one Warning for all, count them and name the first 6 ids | Warning |
| the same document (the URL without any `#fragment` and without a trailing `/`) appears with different non-blank pins: one Warning per document, list the pins | Warning |
| compare is complete (in `completed_steps`) and an evidence row is cited by no gate clause, no requirement score and no feature cell | Error |

### 1.6 scores.json (anchored model only)
Run this section only when `scores.json` exists. It is first written by eval-compare, so skip it at every step before compare. Must be an object, otherwise **Error**. `cell_midpoint` is **not supported in this edition**: `scoring_model` must be exactly `anchored`; a missing `scoring_model` or any other value is an Error ("rerun eval-compare"). Data under `cell_values` is not used here.

| Rule | Level |
| --- | --- |
| the object has no `features` or `feature_cells` key (feature data lives only in features.json) | Error |
| `requirement_scores` is an object (option id, then requirement id, then row) | Error |
| each option id in it is a known option | Error |
| each requirement id in it is a known requirement id | Error |
| each row is an object whose `score` is a number (not true/false) from 0 to 5 inclusive; skip the row's other checks if not | Error |
| `confidence` is `high`, `medium` or `low` | Error |
| `rationale` is blank | Warning |
| `rationale` has more than 40 words | Warning |
| each id in `evidence_ids` is a known evidence id | Error |
| `priority_points`, if present, is an object with exactly the keys `must`, `should`, `could`, each a number above 0 (default must 5, should 3, could 1) | Error |
| each entry of `overrides`, if any, has a `requirement_id` that is a known requirement id | Error |

Totals, ranking and other computed sections (`totals`, `ranking`, `ties`, and the like) are not checked field by field; see 2.4 and 3.4.

### 1.7 cost.json
Required keys: `currency`, `horizon_months`, `assumptions`, `options`.

| Rule | Level |
| --- | --- |
| `horizon_months` is a number above 0 | Error |
| each assumption has `id`, `name`, `value`, `unit` | Error |
| assumption `id` is unique | Error |
| assumption `value` is a number, 0 or more | Error |
| each `scenarios` entry (optional list) has a `name` and a `multiplier` that is a number, 0 or more | Error |
| each key of `options` is a known option id (skip if no options) | Error |
| each option entry has a non-empty `components` list | Error |
| component `id` is unique within the option | Error |
| every option that is not excluded and not `not_profiled` has a cost model under `options` ("eval-discover must price every profiled option") | Error |

**Each component** (required keys: `id`, `name`, `kind`):
| Rule | Level |
| --- | --- |
| `kind` is `fixed_monthly`, `one_time`, `usage` or `tiered` (stop checking the component if not) | Error |
| `assumed` is true and `assumption_note` is blank | Error |
| not assumed, not `price_unknown: true`, and `evidence_id` is blank | Error |
| `evidence_id` is given and is not a known evidence id (skip if evidence.json has no ids) | Error |
| `price_unknown` is true: no further checks on this component | OK |
| required keys by kind: fixed_monthly needs `amount`; one_time needs `amount`; usage needs `unit_price` and `driver`; tiered needs `tiers` and `driver` | Error |
| `amount`, `unit_price`, `included_free`, `quantity`, where present, are numbers, 0 or more | Error |
| `driver` and `quantity_driver`, where non-empty, name a known assumption id | Error |
| `per` (default `month`) is `hour`, `day`, `month` or `year` | Error |
| `per` is anything but `month` on a kind other than `fixed_monthly` | Error |
| `quantity_steps` present on a component that is not `fixed_monthly` or has no `quantity_driver` | Error |
| `quantity_steps` is not a non-empty list of objects each with a numeric `quantity` and an `up_to` key | Error |
| `quantity_steps` `up_to` values are not ascending, or the last is not null, or a non-last one is null | Error |
| tiered: `tiers` is not a non-empty list of objects each with `up_to` and `unit_price` | Error |
| tiered: `up_to` values not ascending, or the last is not null, or a non-last one is null | Error |
| tiered: a tier `unit_price` is not a number, 0 or more | Error |
| tiered: `tier_mode` (default `graduated`) is `graduated` or `volume` | Error |

### 1.8 open_items.json (only if the file exists)
A list, otherwise **Error**. Required keys: `id`, `option`, `linked`, `question`, `owner_type`, `status`.

| Rule | Level |
| --- | --- |
| `id` is unique | Error |
| `owner_type` is `vendor_question`, `poc_test` or `contract_term` | Error |
| `status` is `open` or `closed` | Error |
| `option` is a known option id (skip if no options) | Error |
| `linked` is a requirement id (retired included), a gate id, or a gate's `requirement_id` | Error |
| `owner_type` is `poc_test` and `test_id` is not `P` followed by digits (P1, P2, ...) | Error |
| `test_id` repeats another item's `test_id` | Error |
| a gate verdict's `confirm_by` text mentions a test id (a word like P3) that no `poc_test` item has | Error |

### 1.9 features.json (only if the file exists)
A list, otherwise **Error**. Required keys: `id`, `category`, `name`, `cells`.

| Rule | Level |
| --- | --- |
| feature `id` is unique | Error |
| each key of `cells` is a known option id (skip if no options) | Error |
| each cell is an object whose `status` is `included`, `partial` or `missing` (skip the cell's other checks if not) | Error |
| each id in a cell's `evidence_ids` is a known evidence id | Error |
| each entry of `scope_tags` is one of saas, separate_product, unassessed_release, third_party, external_service, latest_only, preview | Error |

### 1.10 candidate_requirements.json (only if the file exists)
A list, otherwise **Error**. Required keys: `id`, `text`, `suggested_priority`, `suggested_category`, `why`, `source`. `suggested_priority` is `must`, `should` or `could` (**Error**).

## 2. Before step X
Run section 0 existence rules first. Run a section 1 check only on a file that exists and that the step has already produced (never demand `scores.json`, `features.md` or `report.md` before the step that writes them). "Before X" means: every step earlier than X must be finished. Steps in order: define, analyze, discover, compare, report. For each earlier step: **all** its files must exist (**Error** "<file> is missing; it is written by eval-<step>") and the step must be in `completed_steps` (**Error** "step <step> is not complete; run eval-<step>"). Also, `status.json` itself must exist (**Error**), `stale_steps` must be empty (**Error** "stale steps: <list>; rerun the earliest one first"), and every file that exists passes its section 1 checks.

| Step files | Files |
| --- | --- |
| define | `solution.md`, `requirements.md`, `requirements.json` |
| analyze | `criteria.md`, `criteria.json` |
| discover | `options.md`, `options.json`, `evidence.json`, `cost.json` |
| compare | `scores.json`, `features.md` |
| report | `report.md` |

### 2.1 Before define
No prior steps and `status.json` need not exist. If `eval/` already holds an evaluation, archive it first (see the workspace contract). Run section 1 checks only on files that exist.

### 2.2 Before analyze
define files exist, define is complete, no stale steps, `status.json` valid.

### 2.3 Before discover
Everything in 2.2, plus the analyze files exist and analyze is complete.

### 2.4 Before compare
Everything in 2.3, plus the discover files (`options.md`, `options.json`, `evidence.json`, `cost.json`) exist and discover is complete. `features.json` is not required here.

### 2.5 Before report
Everything in 2.4, plus `scores.json` and `features.md` exist and compare is complete, and section 3.4 passes.

## 3. Cross-file checks
Run these after the per-file checks, on whatever files exist.

### 3.1 Evidence and options
| Rule | Level |
| --- | --- |
| a gate is marked `pass` or `fail` for an option in `gate_status` but no evidence row has that `option_id` and `requirement_id` equal to the gate requirement | Warning |
| an evidence row has `inherited_from_oss: true` but its option records `oss_base` null | Error |
| a feature cell cites an evidence id whose row is about a different option than the cell's option | Error |

### 3.2 Names (needs options.json)
Match each option's `name` (only names of 3 or more characters, any letter case) as a whole word: the character before and after must not be a letter, digit, underscore or hyphen.
| Rule | Level |
| --- | --- |
| a requirement's `text` contains an option name ("a requirement describes the need, not a product") | Warning |
| a criterion's `name` or any of its `anchors` texts contains an option name ("no criterion may mention a specific option") | Error |

### 3.3 Score citations (needs scores.json, evidence.json, options.json)
| Rule | Level |
| --- | --- |
| scores exist for an option that is excluded or not profiled ("its scores are ignored and it is never ranked") | Warning |
| a score cites an evidence row about a different option | Error |
| a score cites an evidence row about the right option but whose `requirement_id` is a different requirement, and whose `criterion_id` is not the criterion that holds the scored requirement | Warning |

### 3.4 Scores current (Before report only)
Run only if no Errors were found above and `scores.json` holds a `totals` object. Recompute every option's total and the ranking from `requirement_scores`, `priority_points`, the criteria weights and the overrides, with the scoring method of eval-compare. Totals are out of 100.
| Rule | Level |
| --- | --- |
| scores.json cannot be recomputed (name the first one or two problems; rerun eval-compare) | Error |
| any option's stored total differs from the recomputed total by more than 0.05, an option is in only one of the two sets, or the stored ranking order differs from the recomputed order ("scores.json is out of date; weights, scores or evidence changed after scoring"; list the recomputed and the stored totals) | Error |
