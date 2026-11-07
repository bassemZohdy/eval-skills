# Deep Researcher

A portable Agent Skill for evidence-led research, fact-checking, current-status checks,
and decision comparisons. It prioritizes inspected sources, independent evidence origins,
counter-evidence, calibrated qualitative conclusions, and claim-level citations.

This package preserves the tested skill instructions. The latest proposed refinements
to unresolved-requirement wording and within-case source reuse have not been applied.

## Package contents

| Path | Purpose |
|---|---|
| `SKILL.md` | The only discoverable skill entry point |
| `references/` | Claim-specific checks, numeric-confidence guidance, delegation contract, and the eval-skills handoff |
| `tests/` | Twenty regression cases, synthetic source replay, evaluator, recording tool, and unit tests |
| `tests/TESTING.md` | Behavioral test procedure, quality gates, and limitations |
| `tests/results/skill-smoke-2026-11-01/` | Recorded answers, source traces, reviews, observations, and evaluation |
| `tests/results/skill-smoke-2026-11-01/baseline-source.md` | Historical baseline text; deliberately not named `SKILL.md` |
| `scripts/package_skill.py` | Rebuilds the ZIP, manifest, and checksum using Python's standard library |
| `package-manifest.json`, `SHA256SUMS` | Included-file inventory and integrity checks |

Do not install only `SKILL.md`. Keep the complete `eval-deep-research/` directory together.
Tests and historical evidence are for maintenance, not ordinary research context.

## Requirements

- An Agent Skills-compatible host. Installation locations and discovery behavior depend
  on the host and version.
- Source-reading/search tools supplied by the host for live research. The skill includes
  no API credentials, model client, MCP server, or automatic tool configuration.
- Python **3.9 or newer** for optional packaging and test tools. No third-party Python
  packages are required. Normal skill use does not require Python.

The Python tools do not invoke an LLM. Model-behavior testing needs a separate model harness
and evidence-backed review. No tools are pre-approved by the skill.

## Install in GitHub Copilot CLI

Verify and extract the shared ZIP into a new directory:

```bash
shasum -a 256 -c eval-deep-research.zip.sha256
unzip eval-deep-research.zip
```

On Linux, `sha256sum -c eval-deep-research.zip.sha256` is an alternative checksum command.
Do not extract over an existing installation.

Choose **one** installation scope. These commands stop if the target skill already exists;
review or back up an earlier installation before replacing it.

Personal skill, shared across projects:

```bash
mkdir -p "$HOME/.copilot/skills" &&
  test ! -e "$HOME/.copilot/skills/eval-deep-research" &&
  cp -R eval-deep-research "$HOME/.copilot/skills/"
```

Project skill, from the target repository root:

```bash
mkdir -p .github/skills &&
  test ! -e .github/skills/eval-deep-research &&
  cp -R /path/to/extracted/eval-deep-research .github/skills/
```

In a Copilot CLI session, run:

```text
/skills reload
/skills info eval-deep-research
```

Example request:

```text
Use the /eval-deep-research skill to verify whether this product capability is generally
available for the specified version and region. Cite the deciding records, check for
supersession, and distinguish documented capability from observed operation.
```

Other supported Copilot locations include `.agents/skills` and `~/.agents/skills`; consult
the setup guide for your surface. For other hosts, install the same complete directory
according to that host's Agent Skills documentation.

Official references:
- [Agent skills](https://docs.github.com/en/copilot/concepts/customizations/agent-skills)
- [Adding agent skills for Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills)

## Verify the extracted package

Run these commands from inside the extracted `eval-deep-research/` directory:

```bash
shasum -a 256 -c SHA256SUMS
python3 -B tests/check_skill.py --check-fixtures
python3 -B tests/check_skill.py --self-test
python3 -B -m unittest discover -s tests -p 'test_*.py'
```

Validate the included reviewed observations:

```bash
python3 -B tests/check_skill.py \
  --observations tests/results/skill-smoke-2026-11-01/candidate-observations.json

python3 -B tests/check_skill.py \
  --observations tests/results/skill-smoke-2026-11-01/baseline-observations.json \
  --skill tests/results/skill-smoke-2026-11-01/baseline-source.md
```

Checksums establish integrity relative to this archive, not publisher authenticity.
Packaging checks, evaluator unit tests, and reviewed model behavior are separate results.
Read [the testing guide](tests/TESTING.md) before interpreting a pass.

## Use from the eval skills

The eval skills in this repository (`eval-define` to `eval-report`) use this skill first for
research, fall back to `deep-research` when it is not installed, and research directly under
the same rules when neither is. When called that way, section 8.3 loads
[`references/eval-handoff.md`](references/eval-handoff.md): the caller supplies the option,
requirements, scope and budget, and this skill returns findings as `evidence.json` rows with
its verdicts mapped to the eval labels. The eval skill keeps the labels, budgets and scores.

## Included evidence and known limitations

The recorded smoke comparison predates section 8.3 and the eval handoff reference, so the
current `SKILL.md` hash differs from the recorded candidate. The 20 cases do not exercise
the handoff; it is covered only by the eval skills' packaging checks.


The recorded synthetic smoke comparison passed **20 scenarios and 35 reviewed criteria
per arm**. Revised answers used 1,696 words versus 2,271 for the baseline, but made
89 searches/source opens versus 81. A speed improvement was not established.

The verdict is **conditional smoke pass**, not a certification or production-readiness
claim: each arm used one context containing all cases, model IDs were unavailable,
review was not blinded, and sources were synthetic. Live retrieval, automatic host
activation, held-out behavior, repeated-run reliability, and latency remain unverified.
Synthetic fixture markers are not real credentials.

The baseline is retained as inert evidence text; duplicate historical skill directories,
machine-specific paths, host metadata, and caches are excluded from the archive.

## Rebuild

From a source checkout or the complete extracted package:

```bash
python3 -B scripts/package_skill.py
```

This writes `dist/eval-deep-research.zip` and `dist/eval-deep-research.zip.sha256`. It uses an
explicit file allowlist, sorted paths, fixed ZIP timestamps, and per-file SHA-256 hashes.
Rebuilds are byte-repeatable with the same inputs and Python/compression environment.
Existing output is refused unless replacement is explicitly requested with `--replace`.

## License

No distribution license has been assigned, and no `LICENSE` file is included. The content
owner should choose an appropriate license before public redistribution. Packaging does
not itself grant additional licensing rights.
