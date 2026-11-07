# Contributing

Thanks for trying eval-skills. The most useful contribution is a report from a real evaluation: open an issue with the step you ran, what you expected, what happened, and the line of skill text that misled the agent.

## Change the skills

1. Fork, branch, and keep one change per pull request.
2. Edit shared sources in `shared/` (the script, exporter and `workspace-contract.md`), never the copies inside `skills/*/`. Then run `python scripts/sync_shared.py`. CI runs `sync_shared.py --check`.
3. Keep each `SKILL.md` frontmatter to `name` and a one-line `description` (at most 1024 characters, valid YAML: avoid `: ` inside an unquoted description). `tests/test_repo.py` checks it.
4. A change to `eval_calc.py` or the contract adds tests in `tests/` and keeps `examples/task-queue/` valid (`python shared/export_report.py examples/task-queue/eval --check`).
5. Run `python -m unittest discover -s tests -v` and `python scripts/scorecard.py --skip-tests --min 98`.
6. `skills/eval-deep-research/` is a self-contained package with its own tests and checksums; after editing it, rebuild `package-manifest.json` and `SHA256SUMS` as its README describes.
7. Bump the version in `.claude-plugin/plugin.json` and `.codex-plugin/plugin.json` together for a user-visible change (Codex caches an install by version; a test checks they match).

Be kind in issues and reviews.
