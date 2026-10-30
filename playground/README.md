# Playground

A scratch folder for trying the skills. Everything in here except this README is git-ignored, so evaluations and experiments never reach the repo.

## Use it

1. From the repo root, install the skills into the playground:

   ```bash
   python scripts/setup_playground.py
   ```

2. Open Claude Code in this `playground/` folder.
3. Say what you want to decide, for example "help me choose between X and Y". The `eval-orchestrator` skill starts the chain and writes the evaluation to `playground/eval/`.

Run step 1 again whenever you change a skill under `skills/`; it replaces the installed copies.

## Notes

- The skills bundle their own scripts (`scripts/eval_calc.py`, `scripts/export_report.py`), so nothing else needs installing beyond Python 3.
- A finished evaluation stays in `eval/` until you start a new one; the old one is moved to `eval-archive/` first. Both folders are ignored here.
- To keep a result, copy it somewhere outside `playground/`, for example `examples/`.
