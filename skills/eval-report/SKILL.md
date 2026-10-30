---
name: eval-report
description: Writes the final options evaluation report with the weighted score ranking, the feature-by-feature comparison, a decision recommendation, risks, and sources, and saves the evaluation record. Use after eval-compare when the user wants the final report, an export, or the recommendation from a completed evaluation, or asks "so which one do we pick" about options already scored. Do not use before scoring is complete, and do not use to start a new evaluation (eval-define).
---

# eval-report

Final step of the eval chain: define, analyze, discover, compare, report. Reads every eval file and writes the report that supports the decision. Start the report with a short provenance line: the evaluation date, the scale used, the cost mode, and which steps were rerun after weights or evidence changed. Follow the workspace contract in references/workspace-contract.md.

## Process

1. **Check status.** Read `eval/status.json`. Run `python scripts/eval_calc.py validate eval --before report` and, if it reports a problem, stop and follow its message. If compare is not complete or any step is stale, stop and say which skill to rerun.
2. **Read everything.** Solution, requirements, criteria, options, evidence, scores, features, and the staleness flags in `eval/status.json`.
3. **Write the report** to `eval/report.md` in this order:
   - **Decision recommendation:** the recommended option, in one or two sentences, with the confidence level, stated as high, medium, or low and never as a percentage, and the main condition under which the recommendation would change. High means a clear margin that holds under every sensitivity test and the key scores rest on independent evidence, medium means the margin holds but some key scores are low-confidence, and low means a near-tie, a flip under sensitivity, more than half of the total weight resting on low-confidence scores, or unknown requirements that could let another option overtake the leader (`could_overtake_leader` in `eval/scores.json`).
   - **Decision table:** options ranked by weighted score, with gate status, low-confidence flags, and one line on each option's main strength and main gap.
   - **Context:** the solution, who it is for, and the date of the evaluation.
   - **Criteria and weights:** the table the user approved.
   - **Weighted score matrix:** scores per criterion, contributions, and totals.
   - **Bias and assumptions:** from `bias_checks` in `eval/scores.json`: the providers behind the candidates, any requirement based on an assumption, how many findings are vendor-published against independent, and how many options the cost comparison covers. Say plainly what these limit about the recommendation.
   - **Cost:** the assumptions, the total cost of ownership per option over the horizon, the volume scenarios and which option is cheapest in each, and any component priced from unverified or missing evidence.
   - **Feature-by-feature comparison:** the side-by-side table, grouped by category, with the must-have summary row.
   - **Sensitivity:** whether the ranking holds when influential weights move.
   - **Recommended next steps:** two to four concrete actions that follow from the decision, such as a proof of concept on the riskiest requirement, questions to put to the vendor, or evidence to refresh before committing.
   - **Risks and open questions:** unverified claims that touch the recommendation, gaps, assumptions, and any evidence flagged stale, with its gathered date.
   - **Excluded options:** each with the gate it failed and the evidence.
   - **Sources:** every source used, with date and confidence label, and the date evidence was gathered.
4. **Be honest about the recommendation.** If the top two options are within the tie margin, or the result flips under sensitivity, say the choice is not clear-cut and name what would settle it. Never present a narrow win as decisive.
5. **Review with the user.** Present the recommendation and the decision table. Apply requested edits to wording; changes to scores or weights go back through eval-analyze or eval-compare.
6. **Save the record.** Run `python scripts/eval_calc.py complete eval report`, which records the report date in `eval/status.json`. The evaluation stays active in `eval/` until a new evaluation starts, at which point it is archived to `eval-archive/<solution-slug>-<YYYY-MM-DD>/`.
7. **Export.** Offer HTML, a spreadsheet, and PDF. On a yes, run `python scripts/export_report.py eval --formats html,xlsx,pdf` (drop the formats the user did not ask for). It writes `eval/export/report.html`, `report.xlsx`, and `report.pdf` from the computed files. The spreadsheet keeps the weights as editable cells and the totals as live formulas, so the user can retune the ranking. The PDF is printed from the HTML by Edge or Chrome; if neither is installed the script says so, and you tell the user to open the HTML and print it to PDF. Report which files were written. Exports are generated from the evaluation files and are not edited by hand.

## Quality rules

- The report adds no facts that are not in the evidence file, apart from context the user supplied in the solution file.
- Keep the recommendation and the evidence consistent. Anything marked UNVERIFIED that the recommendation depends on appears under risks.
- Quote sources briefly. Do not reproduce long passages.

## Output

Reply in a few sentences: the recommendation, how confident it is, the single biggest risk, and where the report is saved.
