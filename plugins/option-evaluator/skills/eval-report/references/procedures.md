<!-- Copy of plugins/option-evaluator/shared/procedures.md. Edit the source in shared/, not this copy. -->

# Procedures for the `eval/` housekeeping

These are the housekeeping procedures for the evaluation files. Follow them by reading and writing the JSON files directly. Every rule, constant and ordering below is exact; do not round, reorder or relax anything. File and key names are those of `workspace-contract.md`.

General rules for every write in this file:

- Read the whole file, change only the keys named, write the whole file back as UTF-8 JSON indented by 2 spaces, with a final newline and non-ASCII characters kept as they are.
- Steps, always in this order: `define`, `analyze`, `discover`, `compare`, `report`. Any list of steps in `status.json` is stored in this order.
- Today's date is written `YYYY-MM-DD`.
- Where a check cannot reasonably be done by hand, this file says so. Say the same to the user instead of pretending the check ran.

## 1. Status and next action

Use at the start of every skill (except eval-define) and whenever the user asks where the evaluation stands.

1. If `eval/status.json` does not exist: `action` is `start`, `next_step` is `define`, skill `eval-define`, no completed or stale steps, no problems. Stop.
2. Read `eval/status.json`. If it cannot be read as JSON, `problems` gets that message and the writing skill is rerun (the file is written by every skill).
3. `completed_steps` = the steps listed in `completed_steps`, in step order. `stale_steps` = the steps listed in `stale_steps`, in step order.
4. Decide the action:
   - If `stale_steps` is not empty: `action` is `rerun` and `next_step` is the first stale step in step order (even when an earlier step is incomplete).
   - Otherwise, if some step is not in `completed_steps`: `action` is `continue` and `next_step` is the first step not completed.
   - Otherwise: `action` is `done` and there is no next step.
   - The skill to run is `eval-` plus `next_step`.
5. `problems` is the list of validation errors. By hand, check these status rules and list every failure:
   - `status.json` has all of these keys: `current_step`, `completed_steps`, `stale_steps`, `stale_evidence`, `evaluation_date`, `report_date`, `solution_slug`.
   - `completed_steps` and `stale_steps` are lists of step names only.
   - `evaluation_date` and `report_date`, when not empty, are `YYYY-MM-DD`; `report_date` is not before `evaluation_date`.
   - If `post_scoring_weight_change` is true, `weight_change_reason` is not empty.
   - Steps complete in order: a completed step has every earlier step completed. The error names the first missing earlier step and says to run its skill.
   - Every JSON file that exists in `eval/` can be read as JSON; a file that cannot is a problem naming the skill that writes it.
6. Limitation: a full check would also validate every other file against the contract and recompute `scores.json` to find edits nobody marked stale. Here, run only the checks above, and say that the cross-file checks and the recomputation were not done. If the user says inputs changed after scoring, mark them with section 3.
7. Report these values: `exists`, `action`, `next_step`, `skill`, `completed_steps`, `stale_steps`, `problems`, `archived`, `solution_slug`, `evaluation_date`, `report_date`, and `summary`:
   - `archived`: the sorted names of the folders in `eval-archive/` next to `eval/` (an empty list if the folder is missing).
   - `summary.requirements`, `summary.options`, `summary.evidence_rows`: the number of entries in `requirements.json`, `options.json` and `evidence.json` (only for files that exist and are lists). `summary.criteria`: the number of entries in the `criteria` list of `criteria.json`.
   - If `scores.json` has a non-empty `ranking`: `summary.top_option` is the name (from `options.json`, else the id) of `ranking[0]`, `summary.top_score` is its value in `totals`, and `summary.near_tie` is true when `ties` is not empty.

Files each step writes, used as the step gate before a step starts (to start step X, every file of every earlier step exists and that step is in `completed_steps`, and `stale_steps` is empty; otherwise name the missing file or step and the skill that writes it):

| Step | Files |
| --- | --- |
| define | `solution.md`, `requirements.md`, `requirements.json` |
| analyze | `criteria.md`, `criteria.json` |
| discover | `options.md`, `options.json`, `evidence.json`, `cost.json` |
| compare | `scores.json`, `features.md` |
| report | `report.md` |

Before the report step also confirm that `scores.json` still matches its inputs; by hand this means checking that no input changed since scoring was written (the totals cannot be recomputed here). If unsure, ask the user or send them back to eval-compare.

## 2. Completing a step

Use at the end of every skill, after its work and its approvals are done.

1. If `eval/status.json` does not exist:
   - for `define`: create the `eval/` folder if needed and start from `current_step` `""`, `completed_steps` `[]`, `stale_steps` `[]`, `stale_evidence` `[]`, `evaluation_date` today, `report_date` `""`, `solution_slug` the slug given (or `""`);
   - for any other step: stop with "status.json is missing; run eval-define first".
2. Every step before this one must already be in `completed_steps`. If not, stop and name each missing step ("step X is not complete; complete it before Y"). Write nothing.
3. Update the status in memory:
   - `completed_steps`: the old list plus this step, in step order, without duplicates.
   - `stale_steps`: remove this step only. Later steps that were stale stay stale; `stale_evidence`, `post_scoring_weight_change` and `weight_change_reason` are left as they are.
   - `current_step`: this step.
   - If the step is `analyze`: set `weights_locked_on` to today (also when analyze is completed again).
   - If a slug was given: set `solution_slug` to it.
   - If the step is `define` and `evaluation_date` is empty or missing: set it to today.
   - If the step is `report`: set `report_date` to today.
4. Write `eval/status.json`. Report the new `completed_steps` and `stale_steps`.
5. This procedure does not validate any other file. Each skill runs its own checks before completing; do not mark a step complete when those checks fail.
6. Tell the user which skill runs next (section 1, step 4).

## 3. Marking changes stale

Use whenever a step changes something that later steps depend on. The topic is one of: `requirements`, `weights`, `gates`, `options`, `evidence`, `cost`, `scores`.

Staleness map (the steps that depend on the topic):

| Topic | Steps marked stale |
| --- | --- |
| requirements | analyze, discover, compare, report |
| weights | compare, report |
| gates | discover, compare, report |
| options | compare, report |
| evidence | compare, report |
| cost | compare, report |
| scores | report |

A change to scale or `cost_mode` counts as `weights`.

1. Read `eval/status.json`. If it is missing, stop: the evaluation is not defined.
2. If the topic is `weights` and `compare` is in `completed_steps` (weights moved after scores existed):
   - a one-line reason is required and must not be empty after trimming; if there is none, stop, write nothing and ask the user for it ("weights changed after eval-compare ran; give a one-line reason");
   - set `post_scoring_weight_change` to true and `weight_change_reason` to the trimmed reason. Only the latest reason is kept.
   If `compare` is not completed, the reason is not needed and neither key is changed. For other topics a reason is ignored.
3. Add to `stale_steps` only those steps of the topic's row that are in `completed_steps` (a step that has not run yet is not stale). Keep the steps already stale. Write the list in step order.
4. Write `eval/status.json`. Tell the user the new `stale_steps` and that the earliest stale step is rerun first.

A skill that finds a stale earlier step stops and names the skill to rerun (section 1).

## 4. Stale evidence

Use at the start of eval-compare and eval-report, and when the user asks for a freshness check.

Inputs: `eval/evidence.json`, the date of the check (today, unless the user gives another), and the ids of fast-moving options (products with frequent releases, for example SaaS or fast-release software; ask the user or judge from `options.json` and state the choice; none is assumed).

1. Limit per row: 3 months when the row's `option_id` is in the fast-moving list, otherwise 12 months.
2. Age of a date, in whole months: `(year today - year date) * 12 + (month today - month date)`, minus 1 if the day of today is earlier than the day of the date. A future date gives a negative age.
3. For each row compute the age of `gathered_on` and the age of `source_date`. A date counts only if it is a full `YYYY-MM-DD`; `unknown`, empty and month-only values (`YYYY-MM`) are skipped. If a row has no usable age, it is never stale.
4. The row is stale when the larger of its two ages is strictly greater than its limit (exactly 3 or 12 months is not stale). Note the consequence: an old `source_date` makes a row stale even if it was gathered today.
5. List each stale row as `evidence_id`, `option_id`, `age_months` (the larger age) and `limit_months`.
6. Writing the result is done only when the user or the skill asks for it ("write"). Then:
   - set `stale_evidence` in `status.json` to the stale ids (replacing the old list; an empty list when none are stale);
   - if at least one row is stale, add `compare` and `report` to `stale_steps` when they are in `completed_steps`, in step order. If none are stale, `stale_steps` is not touched.
7. Refreshing the evidence is done only when the user asks; archived evaluations are never changed silently.

## 5. Adding an evidence row

Use for every new claim found during research.

Input fields: `option_id`, `finding`, `source_url`, `confidence`, `source_kind`; at least one of `requirement_id` and `criterion_id`; optional `source_date` (default `unknown`), `gathered_on` (default today), `scope`, `pin`, `source_class`.

1. Read `eval/evidence.json` (a missing file counts as an empty list) and `eval/options.json`.
2. Check before writing; if any check fails, write nothing and say which:
   - `requirement_id` and/or `criterion_id` is given.
   - `confidence` is exactly one of `PRIMARY`, `CONFIRMED`, `PROBABLE`, `UNVERIFIED`, `COULD NOT VERIFY`, `DISPUTED`.
   - `source_kind` is one of `vendor`, `independent`, `oss_project_docs`, `source_code`.
   - If `options.json` is not empty: `option_id` is one of its `option_id` values.
   - `scope`, if given, is `in_scope` or `out_of_scope`; `source_class`, if given, is `primary`, `company` or `secondary`.
   - `finding` and `source_url` are not empty.
   - `gathered_on` is a real date, not in the future. `source_date` is `YYYY-MM-DD`, `YYYY-MM` or `unknown`, and is not after `gathered_on` (compare month-only dates by month).
   - `pin` of `latest` is allowed only when `source_date` is not `unknown`.
   - `source_kind` `source_code`: `source_url` or `pin` contains `path@commit`, and the row also needs `lines` (a line range such as `120-148`); `confidence` `PRIMARY` or `CONFIRMED` needs `tested: true`. Add `lines` and `tested` by hand when relevant.
3. The new id is `E-` plus a three-digit number (`E-001`, `E-002`, ...): take the largest number among existing ids of the form `E-` followed by digits, add 1, pad to three digits (an empty file starts at `E-001`). Ids are never reused.
4. Append one row with these keys, in this order: `evidence_id`, `option_id`, `finding`, `source_url`, `source_date`, `gathered_on`, `confidence`, `source_kind`; then, only when present, `requirement_id`, `criterion_id`; `scope` only when it is `out_of_scope` (omit it for in-scope evidence); `pin`; `source_class`.
5. Write `evidence.json` and tell the user the new id. A change to evidence marks `compare` and `report` stale (section 3, topic `evidence`).
6. Guidance for the values: weak labels are `UNVERIFIED` and `COULD NOT VERIFY`; `CONFIRMED` is for two or more independent sources, so a vendor-only row is `PRIMARY` (attributed statement) and one independent source is `PROBABLE`; evidence about a component a gate excludes is `scope: out_of_scope`.

## 6. Research gaps list

Use to decide what to research first. Needs `requirements.json`, `criteria.json`, `options.json`, `evidence.json` and `scores.json`; if one is missing or unreadable, stop and name the skill that writes it. A full check would also validate every file first; here, check only that these five files are readable.

1. Weak evidence ids: ids of evidence rows whose `confidence` is `UNVERIFIED` or `COULD NOT VERIFY`. (`DISPUTED` is not weak here.)
2. Per requirement: the `weight` of the criterion that holds it and that criterion's `id`.
3. For every option that is not `excluded` and not `not_profiled`, and every requirement that is not `retired`, decide its state:
   - Anchored scoring model (`scoring_model` is `anchored`): look at `requirement_scores[option][requirement]`. No row: state `unknown`. A row with no evidence id outside the weak ids (including an empty `evidence_ids`): state `unsupported`. Otherwise it is not a gap.
   - `cell_midpoint` model (the default when `scoring_model` is absent): look at `cell_values[option][requirement]`. No cell or `value` `unknown`: `unknown`. Any other value with no evidence id outside the weak ids: `unsupported`. Otherwise it is not a gap.
4. Each gap carries `requirement_id`, `text`, `priority`, `criterion_id`, `criterion_weight`, `state` and `note` (the row's `rationale` under the anchored model, or the cell's `note`; empty if none).
5. Order each option's gaps by: priority (`must` first, then `should`, then `could`), then criterion weight, largest first, then `requirement_id` ascending.
6. Per option report `name`, `total_gaps` (all gaps) and `research_first` (the first N gaps). N is 8 unless the user asks for another limit.

## 7. Verification queue

Use to decide what to re-check first before a decision. Needs `requirements.json`, `criteria.json`, `scores.json` and `evidence.json` (stop and name the writing skill if one is missing or unreadable).

1. Priority points: `scores.json` `priority_points` if present, otherwise `must` 5, `should` 3, `could` 1.
2. Gate items. For every gate in `criteria.json` `gates` and every option in its `verdicts`, make an item (`kind` gate, `id` the gate id, `option_id`) with reasons:
   - `unverified` when the verdict is `UNVERIFIED`;
   - `documented only` when the verdict's `basis` is `documented`.
   Items with at least one reason get priority 1000, so they come before every requirement item.
3. Requirement items. This applies to the anchored model (under `cell_midpoint` there are no `requirement_scores`, so there are no requirement items). For each criterion (including weight 0) and each requirement id in its `requirement_ids`:
   - `den` = the sum of the priority points of all requirements of that criterion (use 1 if that sum is 0);
   - `worth` = criterion weight x priority points of this requirement / `den`;
   - `spread` = highest minus lowest `score` for this requirement over every option that has a row for it (0 if none);
   - for every option with a row for this requirement (no filter on excluded options), the reasons are, in this order: `low confidence` or `medium confidence` (the row's `confidence`; `high` gives no reason), `page not read` (the `rationale` contains "not read", any case), `inherited from open source only` (the row cites at least one evidence id and every cited row has `inherited_from_oss: true`);
   - an item with at least one reason is kept with `kind` requirement, `id` the requirement id, `option_id`, `reasons`, `score` and `priority` = `worth` x (`spread` + 1) rounded to 2 decimals.
4. Order all items by `priority` descending, then `id` ascending, then `option_id` ascending.
5. Report the total number of items and the first N (15 unless the user asks for another limit).

## 8. Rendering `features.md` from `features.json`

Use at the end of eval-compare and whenever `features.json` changes. The table is descriptive only: it never changes a score and a score never changes it.

1. Needs `eval/features.json` (a list) and `eval/options.json`; if `features.json` is missing or invalid, stop. Check each feature has `id`, `category`, `name`, `cells`, ids are unique, each cell `status` is `included`, `partial` or `missing`, each `scope_tags` entry is one of `saas`, `separate_product`, `unassessed_release`, `third_party`, `external_service`, `latest_only`, `preview`, each cited evidence id exists in `evidence.json`, and every cell cites evidence about the option of that cell.
2. Columns: the options that are not `excluded` and not `not_profiled`, in the order of `options.json`, headed by the option `name`.
3. Escaping, applied to every cell text, name and heading: replace `|` with `\|` and each newline with a space.
4. Header lines, then a blank line after each of the three: `# Feature comparison`, blank, `Generated from `eval/features.json`. Do not edit by hand. This table describes what each option offers; it has no effect on the scores.`, blank. (The generator's name in the original wording is dropped.)
5. One section per category, in order of first appearance in `features.json`:
   - `## <category>`, blank line;
   - header row `| ID | Feature | <option name> | ... |` and separator `| --- | --- | --- | ... |` (one `---` per column);
   - one row per feature of that category, in file order: `| <id> | <name>[: <description>] | <cell> | ... |`; the description is appended after `: ` only if it is present and not empty;
   - a blank line after the table.
6. A cell, for the feature and the option: if the feature has no cell for the option, it is `missing`. Otherwise the text is built from the parts below, joined with no extra separators, each only when present:
   - `status` (`included`, `partial` or `missing`);
   - ` {tag1, tag2}` when `scope_tags` is not empty (a space, braces, tags joined by `, `);
   - ` - <note>` when `note` is not empty;
   - ` [E-001, E-002]` when `evidence_ids` is not empty.
   Example: `partial {preview} - beta only [E-014]`.
7. There is no summary row in this table. (A "Must-have summary" exists only in the older table in step 9.)
8. Cost section, only if `scores.json` holds a `cost_summary` (or the step that wrote the scores just computed one). It has `currency`, `horizon_months`, `options` (option id to `tco`, `monthly`, `one_time`, `incomplete`, ...). Append, directly after the last blank line:
   - `## Cost (total cost of ownership over <horizon_months> months, <currency>)`, blank line;
   - `| Option | Monthly | One-time | Total |` and `| --- | --- | --- | --- |`;
   - one row per shown option that has an entry in `cost_summary.options`, in column order: `| <name> | <monthly> | <one_time> | <total> |`;
   - numbers are written with thousands separators and two decimals (`12,345.60`); `<total>` is the `tco` formatted that way, but if `incomplete` is true it is `quote needed` when `tco` is 0 and `<tco> + quote needed` otherwise.
   If there is no `cost_summary`, leave the section out. Totals come from the cost model of `cost.json` (computed outside this procedure); never invent them.
9. End the file with exactly one newline. Write it to `eval/features.md`.
10. Older evaluations with no `features.json` that use the `cell_midpoint` scoring model had a table built from the requirements instead (columns `ID`, `Requirement`, `Priority` and one per option, cell text `<value> - <note> [ids]`, then a "Must-have summary" table of counts per cell value, a cost table with a Notes column, and a "Not compared" list). That layout is not produced here: say so and ask the user to rerun eval-compare to create `features.json`.

## 9. Reconcile with an earlier assessment, and matrix stress test

### Reconcile

Compares our evaluation with another team's score table. Needs a scored evaluation on the anchored model (`requirement_scores` present); if not, say so and stop.

Inputs: the other table (columns `Criterion`, `Weight`, then one numeric column per option) and a mapping table (columns `Criterion` and `Requirements`: our requirement ids separated by `;`). Scale maximum of the other table: 5 unless told otherwise.

1. Match each option column to one of our scored options: the column heading (trimmed) equals our `option_id`, our `name`, or our `name` up to the first ` (`. Columns with no match are ignored; if none match, stop.
2. A criterion of theirs with no mapping is left out (list it as a warning). A mapping naming an unknown requirement id is an error: stop.
3. Our rating for their criterion and an option = (sum over the mapped requirements of priority points x our `score`, a missing score counting 0) / (sum of the priority points of the mapped requirements) x scale maximum / 5, rounded to 2 decimals. Priority points are `priority_points` of `scores.json`, default `must` 5, `should` 3, `could` 1. The difference is ours minus theirs, rounded to 2 decimals.
4. Per option: `their_total` = sum of (their weight x their rating) over the mapped criteria / sum of their weights over the mapped criteria / scale maximum x 100; `our_ratings_under_their_weights` = the same with our ratings; both rounded to 1 decimal. Also give our own total from `scores.json` `totals`.
5. Show the criteria where the difference is large and say which requirements explain it.

### Matrix stress test

Stress-tests a score table from outside the evaluation. Inputs: columns `Criterion`, `Weight` and one numeric column per option (a column counts as an option only if every row is a number; at least two are needed, otherwise stop). Scale maximum 5 unless told otherwise.

1. Total of an option for a weight set `w` = sum of (`w` x score) / scale maximum / sum of `w` x 100, rounded to 1 decimal.
2. Base totals use the given weights; the ranking is by total descending (ties keep the column order). The leader is the first.
3. Single-weight test: for each criterion with a weight above 0 and below the sum of all weights, and for each change of +5 and -5: the new weight is the old plus the change, but not below 0; every other weight is multiplied by (sum of weights - new weight) / (sum of weights - old weight), so the sum stays the same. Recompute the totals. Record the number of tests; record a flip (criterion, change, new leader) whenever the top option differs from the leader (ties go to the first column); track the smallest lead (top minus second, rounded to 1 decimal) with its criterion and change; the first smallest wins ties.
4. Equal-weights test: every weight 1; give the totals and ranking.
5. Report: option names, base totals and ranking, number of single-weight tests, the leader changes, the smallest lead, equal-weights totals and ranking.
