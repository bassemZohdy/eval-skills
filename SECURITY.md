# Security

## What the skills can do

The skills are Markdown instructions plus Python scripts that use only the standard library. `shared/eval_calc.py` reads and writes the evaluation files under `eval/` in your project (scores, weights, evidence, cost). It parses URLs but opens no network connection. `shared/export_report.py` renders `eval/report.html`, a spreadsheet and, when Edge or Chrome is installed, a PDF: it starts that browser headless on a local file (`file://`) with a throwaway profile, with a 120 second timeout. `scripts/scorecard.py` and `scripts/sync_shared.py` are maintainer tools that read and write files in this repository.

The skills do research with the host agent's own search and fetch tools (or `eval-deep-research`). What those tools fetch is untrusted: the skills record a source only after opening it and treat page text as evidence, never as instructions. Review `eval/` files from an untrusted source the way you review code, since they steer an agent.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting on this repository ("Security" tab, "Report a vulnerability"). Include what you ran, what happened, and the skill text or script involved. You can expect an acknowledgement within a week.
