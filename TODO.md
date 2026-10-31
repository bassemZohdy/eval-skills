# TODO — improvements learned from a real evaluation

These tasks come from a long, real three-vendor evaluation (AI/agent gateways for an air-gapped, multi-site Kubernetes/OpenShift platform, extending an existing LLM proxy). That work went through 10+ rounds of rework. Each task below names the problem that caused rework, the change to make, the files involved and how to tell it is done.

Conventions:
- Edit `shared/` sources, then run `python scripts/sync_shared.py`; CI runs `sync_shared.py --check` and the tests.
- Every task that changes `eval_calc.py` or the contract adds tests in `tests/` and updates `examples/task-queue/` so the sample still validates.
- Tick a task only when its acceptance checks pass.

Priority: **P1** fixes a wrong result or a rule the user insisted on. **P2** prevents a class of rework. **P3** improves quality or ergonomics.

---

## A. Scoring model

### [x] A1 (P1) Separate the feature table from the score
**Problem.** `eval-compare` step 7 builds the feature table from the same `cell_values` that produce the criterion scores ("one shared mapping so the table and the scores never disagree"). The user's rule is the opposite: scores come only from weighted requirements → weighted categories → criteria. The feature table is a separate, descriptive inventory of what each option gives that another does not. Features and requirements can look alike but serve different purposes, and neither may change the other.
**Change.**
- Contract: add `eval/features.json`, a list of features (id, category, name, short description) with one cell per option: `status` of included, partial or missing; `note`; `evidence_ids`; optional `scope_tags` (see A6).
- `eval/features.md` is generated from `features.json`, no longer from `cell_values`.
- Requirement scoring keeps its own records (see A2). Remove the "table and scores must agree" quality rule and the "summary row per option for must-haves" coupling.
- `eval-discover` collects feature evidence as it profiles; `eval-compare` writes `features.json`; the scorer never reads it.
- The report shows the two tables in separate sections, each labelled with what it is for.
**Files.** `shared/workspace-contract.md`, `shared/eval_calc.py` (`score` stops writing features.md from cells; new `features` command renders features.md), `skills/eval-compare/SKILL.md`, `skills/eval-discover/SKILL.md`, `skills/eval-report/SKILL.md`, `shared/export_report.py`, example files, tests.
**Done when.** A test changes a feature cell and the totals stay byte-identical, and changes a requirement score while `features.md` stays unchanged. Validation fails when the scorer is fed `features.json`.

### [x] A2 (P1) Score each requirement 0–5 against written anchors
**Problem.** The scorer maps cell values to range midpoints (provided 4.5, partial 2.5 …) and averages them per criterion. Between rounds this made scores move for reasons nobody could explain, and it cannot express "GA but with limits" or "only through a third-party add-on". The scheme that held up scores every requirement 0–5 against fixed anchors, each with a rationale of at most 40 words, a confidence and source ids.
**Change.**
- Default anchors in `criteria.json` (user-editable):
  - 5 exceeds the requirement
  - 4 fully meets it, generally available
  - 3 core is met, with limits
  - 2 partial, preview or beta
  - 1 only via custom build, a third-party add-on or a component outside the package
  - 0 not met
- `scores.json`: `requirement_scores[option][requirement] = {score, confidence, rationale, evidence_ids}`.
- Criterion attainment is the priority-weighted mean of its requirement scores divided by 5. The total is Σ(category weight × attainment), shown out of 100 with one decimal.
- Default priority points: must 5, should 3, could 1. The current 3/2/1 under-weights musts; keep it configurable in the mapping.
- Keep `overrides` (with reason) at requirement level.
- Keep backward compatibility: a `scoring_model: "cell_midpoint" | "anchored"` key, defaulting to `anchored` for new evaluations.
**Files.** `shared/eval_calc.py` (`compute`), contract, `eval-analyze` step 5 (anchors), `eval-compare` steps 3–7, export, example, tests.
**Done when.** The example rescored under `anchored` reproduces a hand-checked total. Priority points and anchors come from the mapping. Each rationale is at most 40 words (validator warning).

### [x] A3 (P1) Weighted categories hold weighted requirements
**Problem.** "One criterion per category" was right, but users talk about category weights and priority-weighted requirements inside them. Weights did not sum to 100 at one point, the per-criterion results were not shown out of 100, and global rounding made category subtotals come out at 8.99%.
**Change.**
- Make the hierarchy explicit in the contract: criterion = category, with a weight; requirement, with a priority; score.
- Validator: category weights are whole numbers summing to exactly 100 (excluding cost when `cost_mode` is separate); every scored requirement belongs to exactly one category; each category holds at least two requirements.
- Show requirement weight shares (category weight × priority share) using largest-remainder rounding within each category, so displayed shares sum to the category weight.
**Done when.** Tests cover sums, membership and per-category rounding, and the report shows each category's attainment and contribution.

### [x] A4 (P2) Sensitivity that matches how people challenge a result
**Problem.** The ±5 test on the top three weights was not enough. Reviewers asked "what if all categories were equal?" and "what if only musts counted?", and the ranking flipped. A 3-point tie margin also proved too tight for a 0–100 total built from judgement scores.
**Change.**
- `score` computes and stores these scenarios: base weights; equal category weights; must-only; ±5 points moved between the two largest categories; low-confidence scores lowered by one.
- Add a `meaningful_gap` setting (default 5 points), used for ties instead of the 3-point margin.
- Store `order_changes: "N of M scenarios"` and the leader per scenario.
- The report's confidence rule uses these values: high only if no scenario changes the leader and the gap is at least `meaningful_gap`.
**Done when.** The example's `scores.json` holds all scenarios, and a test where equal weights flip the leader yields report confidence "low".

### [x] A5 (P2) Lock weights before scoring, and say so when they move
**Problem.** Weights changed after scores existed, including one change to match another assessment. A reviewer can fairly call that tuning toward a result. The user wants weights tunable, with no history of tuning kept.
**Change.**
- `status.json` gets `weights_locked_on` (set when analyze completes).
- If weights change after compare has run, `eval-analyze` asks for a one-line reason. `status.json` keeps only the latest reason and a `post_scoring_weight_change: true` flag (no history), and the report states this in its provenance line.
- `eval-analyze` suggests that stakeholders, not the evaluator, sign off the weights.
**Done when.** A test changes weights after compare; validation then requires the reason, and the report includes the flag.

### [x] A6 (P2) Package scope tags and a strict-scope view for features
**Problem.** Feature cells mixed "in the package" with "needs the vendor's SaaS", "separate product", "preview", "latest release only" and "third-party". Readers could not tell what they would actually get.
**Change.**
- `scope_tags` on feature cells: `saas` (vendor-hosted service), `separate_product`, `unassessed_release`, `third_party`, `external_service`, `latest_only`, `preview`.
- The exporter adds a strict-scope toggle that greys out tagged cells. The toggle affects the feature view only, never scores (test it).
- A "stands alone" summary (features only one option has) leaves out negative-evidence and tagged rows.
**Done when.** The export has the toggle, and a test shows `SCORE` is unchanged when it is switched.

### [x] A7 (P3) Retire or merge overlapping requirements
**Problem.** Adding requirements late (skills management, prompt management) left an older combined requirement double-counting the same capability.
**Change.** When requirements are added, `eval-define` lists near-duplicates (same category, overlapping keywords) and asks whether to retire or merge them. Retired requirements keep their id with `retired: true` and are never renumbered.
**Done when.** The validator rejects a reused id, and the scorer ignores retired requirements.

---

## B. Gates (mandatory requirements)

### [x] B1 (P1) One uniform gate rubric applied to every option
**Problem.** Gate verdicts were uneven: the same evidence passed one vendor and failed another. The user had to ask for every NOT MET to be revalidated. Fixing it needed a written rubric per gate with explicit clauses.
**Change.**
- `criteria.json` `gates[]`: id, requirement_id, `pass_clauses` (a list; all must hold), `evidence_needed`, `package_rule` (every component of the package must satisfy it), and `verdicts` per option: PASS, NOT MET or UNVERIFIED, with clause-by-clause notes and evidence ids.
- `eval-analyze` writes the rubric; `eval-discover` and `eval-compare` judge every option clause by clause.
- Gates are not scored and never add points.
**Done when.** The validator requires clause notes for each verdict. A test with one clause missing for one option forces UNVERIFIED.

### [x] B2 (P1) Name what each PASS rests on
**Problem.** Every PASS rested on documentation, and tests and vendor confirmations were still missing. Readers took PASS as proven.
**Change.** Each verdict carries a `basis` of `documented`, `vendor_confirmed` or `tested`. A `documented` PASS must name the POC test or vendor question that would confirm it, and the report shows the basis next to the verdict.
**Done when.** The validator errors on a `documented` PASS that names no confirming test or question.

### [x] B3 (P1) Headline eligibility before scores
**Problem.** Every option failed at least one gate, yet the report led with the top score.
**Change.** If any profiled option fails or has an unverified gate, `eval-report` opens with "Eligibility: N of M options pass every gate", lists the blockers per option, and only then gives scores. If no option passes, the recommendation becomes "shortlist and close the blockers", never "choose X".
**Done when.** A test where every option has a NOT MET produces report text with no "recommended option" sentence.

### [x] B4 (P2) Gate prompts for regulated and air-gapped work
**Problem.** Important gates surfaced late: GA of the protocol in a supported release, every package component on the target platform, local support coverage in the customer's country, a licence and entitlement map, independent operation per site.
**Change.** Extend `eval-define` step 5 with a checklist to ask about:
- protocol or standard GA in a vendor-supported release
- platform support for *every* package component
- local or regional support coverage
- licensing and entitlement clarity (what SKU covers what)
- offline install, upgrade and licence validation
- per-site independence (control plane loss, cold start)
**Done when.** The SKILL.md has the checklist and the example has at least one such gate.

---

## C. Evidence

### [x] C1 (P1) Inheriting open-source evidence, applied to every option
**Problem.** Contract rule 12 treats open-source docs as evidence only for the open-source edition. When a vendor's enterprise edition is built on the project, though, OSS capabilities usually carry over. The rule we settled on was applied to one vendor only, which a reviewer flagged as unfair, because the other vendors also had open-source cores.
**Change.** Add an inheritance rule to the contract. An OSS capability counts for the enterprise package when all of these hold:
- (a) its code is at or before the OSS commit or tag that the enterprise release is built on
- (b) it is configurable through the enterprise product's own configuration and is not excluded by the vendor's docs
- (c) the evidence is from the deployment mode being evaluated
- (d) the vendor's maturity label wins; otherwise the OSS label is the upper bound
- (e) it does not depend on a component the vendor excludes from support

Capabilities that rely only on inherited evidence are capped at medium confidence.
- `options.json` gains `oss_base` per option: project, commit or tag, and source.
- `eval-discover` must check, for every option, whether it has an OSS base, and apply the rule to all of them or to none.
- Gaps the OSS also has, and the vendor's own commercial duties (support, local presence, licensing, certifications), are never closed by OSS evidence.
- Evidence gets `inherited_from_oss: true`.
**Done when.** The scorer caps confidence on inherited-only cells, and `bias_checks` warns when `oss_base` is set for one option and unchecked for another.

### [x] C2 (P1) Pin every source to a version
**Problem.** Many claims cited "latest" pages that changed between rounds. Reference clean-up took three full passes: duplicates, `/main/` links, mixed versions, sources nothing cited.
**Change.**
- Evidence rows get `pin`: release, tag, commit or a dated snapshot. `latest` is allowed only with `source_date`.
- They also get `source_class`: primary, company-level or secondary.
- `validate` warns on `/main/` or `/master/` URLs and on the same document cited at different pins. It errors on evidence rows that no score, gate or feature cites in a finished evaluation.
- The exporter numbers sources 1..N by first citation and keeps one entry per document.
**Done when.** Tests cover the duplicate, unpinned, uncited and numbering cases.

### [x] C3 (P2) Source code as evidence
**Problem.** Several decisive facts came only from reading upstream source code (for example, whether a data plane keeps its last config when the control plane is lost).
**Change.** Add `source_kind: source_code`, citing `path@commit` with a line range. A finding from reading code is PROBABLE at best, unless a test proves it, and is listed as a POC candidate.
**Done when.** The contract and the scorer accept it, and the report shows "from source code" next to such findings.

### [x] C4 (P2) Release and support-matrix checks per package
**Problem.** Late findings caused rework:
- an evaluated build sat outside the vendor's support matrix
- a release was documented but not yet tagged
- one component was tested only with an older version of another
- a long-term-support line lacked fixes present in "latest"
**Change.** `eval-discover` step 5 must record, per package component:
- the version evaluated, its release date and its support-lifecycle status (supported, LTS, outside the matrix)
- compatibility between the package's components
- the newest release on the evaluation date

`options.json` `package` becomes structured: `components[]` with name, version, lifecycle and compatibility notes.
**Done when.** The validator requires the lifecycle status per component, and the report has a "Packages scored" table.

### [x] C5 (P2) A freshness sweep before reporting
**Problem.** Between scoring and reporting, new versions of the standards appeared (a protocol spec, a release candidate), a vendor shipped a release with breaking changes, and a security fix raised the incumbent's minimum version.
**Change.** Before writing, `eval-report` runs a bounded sweep (up to 5 look-ups) for each must-have standard and each package component. Anything new goes under risks, and scores are not changed without `eval-compare`.
**Done when.** The SKILL.md has the step, and the report has a "Changes since evidence was gathered" subsection.

### [x] C6 (P2) Re-verify medium and low confidence, with a budget
**Problem.** Many rounds were spent re-checking scores of 2 or below that rested on medium confidence, unread pages or inferences.
**Change.**
- New command `eval_calc.py verify-queue eval`: it lists requirement scores and gate verdicts with low or medium confidence, "not read" notes, inherited-only evidence or `documented` gate PASSes, sorted by weight × score gap between options.
- `eval-compare` works the top of the queue within its look-up budget and records the rest as open items (C7).
**Done when.** The command exists, has tests, and its output is in the example.

### [x] C7 (P2) Open verification items with owners
**Problem.** What remained unverified was scattered across caveats, a ledger, gate text and profiles.
**Change.**
- Add `eval/open_items.json`: id, option, linked requirement or gate, question, owner_type (`vendor_question`, `poc_test` or `contract_term`), test id, and status.
- POC tests get ids (P1..Pn) and are linked from gates and requirements.
- The report has one "Open verification items" section, and caveats must not repeat it.
**Done when.** The validator checks that every linked id resolves and every item has an owner.

### [x] C8 (P3) Research tips for restricted environments
**Problem.** Subagents lost time on blocked fetches.
**Change.** Add to `eval-discover`:
- open URLs only after they appear in search results or fetched pages
- if docs sites are blocked, clone the vendor's public docs repos and source repos with git and cite `path@commit`
- retry once on a sibling page before marking a fact unknown
**Done when.** The SKILL.md has the tips.

### [x] C9 (P3) Requirements found during research
**Problem.** Research surfaced 16 decision-relevant requirements nobody had listed (for example, reconciling token counts with the incumbent's ledger, minimum incumbent version, licence expiry behaviour).
**Change.**
- `eval-discover` and `eval-compare` record them as `candidate_requirements` (suggested priority and category, why, source) and never score them.
- `eval-report` lists them.
- Accepting one routes to `eval-define`, which marks the later steps stale.
**Done when.** The contract has the key and the example has one candidate.

---

## D. Report

### [x] D1 (P1) Report structure in decision order, without duplication
**Problem.** The report grew to more than 37,000 words, with a verification ledger, method history, 19 caveats, profiles that repeated the tables, and 452 sources. Cleaning it up removed whole sections.
**Change.** The `eval-report` order becomes:
1. Eligibility and decision summary: bottom line, scores, blockers, next steps.
2. Gates.
3. Requirements, weights and scores: final scores, category view, sensitivity, per-requirement table.
4. Option profiles: strengths, blockers, risks only.
5. POC tests.
6. Open items.
7. Feature comparison.
8. Caveats: at most 10, none repeating gates or open items.
9. Sources.

Method history lives in `status.json`, not in the report. Process words such as "this round" or "re-checked" are banned. Each fact is stated in one place.
**Done when.** The exporter enforces the section order. A validator lints caveats against open items and gate text for near-duplicates and warns on banned words.

### [x] D2 (P2) Reconciling with an earlier or external assessment
**Problem.** The user asked twice to check against an earlier report and saw "a big difference". The useful answer separated method from evidence: map the other assessment's criteria onto ours, recompute its totals with our ratings, then list factual disagreements and which side the evidence supports.
**Change.**
- New command `eval_calc.py reconcile eval OTHER.csv`: OTHER.csv holds the other assessment's criteria, weights and per-option ratings, plus a mapping file from its criteria to our requirement ids.
- It outputs both totals, our ratings under their weights, and the per-criterion differences.
- `eval-report` gets an optional "Comparison with an earlier assessment" section. It must not link to other reports (independence rule).
**Done when.** The command is tested with a small fixture.

### [x] D3 (P2) Human spot-check list
**Problem.** The research was done by agents. Before relying on it, a person should verify the cells that decide the result.
**Change.** `score` outputs `deciding_cells`: all gate verdicts, plus the must-have requirements with the largest score spread between the top two options, adding up to 80% of the gap. The report lists them as "verify before deciding".
**Done when.** The example output has the list.

### [x] D4 (P2) Decision factors outside the score
**Problem.** The review found missing cost and commercial terms, operating effort and team skills, lock-in and exit cost, and roadmap commitments. These usually decide a close call.
**Change.** `eval-define` asks whether each is in scope (cost already exists). If one is not scored, `eval-report` adds a "Not assessed" line naming it, and the recommendation confidence cannot be "high" while one is unassessed and the gap is under `meaningful_gap`.
**Done when.** The SKILL.md and the report template are updated.

### [x] D5 (P2) Export quality checks
**Problem.** Pages broke at phone width, the sticky nav covered a quarter of the screen, displayed numbers went stale after re-scoring, and constants were left unused.
**Change.** `export_report.py --check` uses headless Chromium when available to check:
- no JS errors at 1400 and 390 px
- no horizontal scroll at 390 px
- the nav uses at most 10% of the viewport height
- the totals embedded in the page equal `scores.json`
- no number in the page text matches a total from an earlier run (kept in `status.json`)
**Done when.** CI runs it when Chromium is present and skips cleanly otherwise.

### [x] D6 (P3) Interactive what-if on weights in the HTML
**Problem.** Stakeholders wanted to try weights live. The spreadsheet does this, but the HTML did not.
**Change.** The HTML export lets users edit category weights and priority points, rebalances to 100, offers reset, and shows a meaningful-gap marker. Gates and features are unaffected.
**Done when.** A test checks that the page's recompute equals the scorer's.

---

## E. Coexistence with an incumbent

### [x] E1 (P2) Extending or replacing an incumbent
**Problem.** The real objective was to *extend* an incumbent (the existing proxy keeps routing, keys and spend), not to replace it. Scoring overlap as value was wrong, and the incumbent's minimum version and security fixes mattered.
**Change.**
- `solution.md` records `incumbent_role`: replace, extend or coexist.
- When it is extend or coexist, `eval-define` adds a coexistence category: integration as an upstream, no duplicate ownership of shared functions, reconciling shared records, and the incumbent's minimum version.
- `eval-compare` does not credit functions the incumbent keeps.
**Done when.** The example has the field, and the SKILL.md text is updated.

---

## F. Tooling and tests

### [x] F1 (P2) Independent recomputation in CI
Add a small second implementation of the total (written separately, in `tests/`) that recomputes the example from the JSON and asserts it equals `scores.json`. This would have caught the 8.99% rounding bug and stale totals early.

### [x] F2 (P3) Fixture for a multi-component, gated evaluation
Add `examples/gateway-like/`, an anonymised three-option, two-component-package example with:
- six gates, including a documented-only PASS and a NOT MET
- OSS inheritance for two options
- scope-tagged features
- open items and POC ids
- candidate requirements

Use it in tests for A–E.

### [x] F3 (P3) Keep the README in sync
Update the README's file table, script list and "Scope and packages" section for every contract change above, and keep the `sync_shared.py --check` CI step.
