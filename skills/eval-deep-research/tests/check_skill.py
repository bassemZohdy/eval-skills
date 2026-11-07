"""Check packaging or evaluate recorded, reviewed research runs; never invoke a model.

Commands:
  python3 -B tests/check_skill.py --check-fixtures
  python3 -B tests/check_skill.py --self-test
  python3 -B tests/check_skill.py --observations run.json [--skill baseline/SKILL.md]

Observation format:
  {
    "run": {
      "skill_sha256": "<hash of the tested SKILL.md and its references>",
      "cases_sha256": "<hash of research-cases.json>",
      "model": "<actual model>", "configuration": "<tools and limits>",
      "reviewer": "<actual reviewer>", "executed_at": "<run timestamp>"
    },
    "cases": {
      "<case id>": {
        "response": "<actual response>", "tool_trace": ["<actual trace entry>"],
        "checks": {
          "<check id>": {"passed": true, "evidence": "<response or trace location>"}
        }
      }
    }
  }

Use actual runs, not synthetic self-test records, for behavioral evaluation. Reviewers
judge each fixture criterion and cite response/trace evidence; this checker verifies
record completeness and reviewed assertions, not their semantic truth or independence.
For baseline/candidate comparisons, run both with the same model, tools, and limits.
Hashes printed by --check-fixtures identify the evaluated inputs. A FAIL may mean a
failed criterion or incomplete observations; inspect the errors rather than assuming
the model failed. Fixture validation and self-tests are not model-behavior passes.
"""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = ROOT / "tests" / "research-cases.json"


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    return json.loads(path.read_text(), object_pairs_hook=unique_object)


def load_cases(path):
    data = read_json(path)
    if not isinstance(data, dict) or data.get("schema") != "eval-deep-research-cases/1":
        raise ValueError("Unsupported fixture schema")
    if not isinstance(data.get("instructions"), str) or not data["instructions"].strip():
        raise ValueError("Fixture execution instructions are required")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Fixtures require a nonempty cases list")
    ids = set()
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Each fixture must be an object")
        case_id = case.get("id")
        if not isinstance(case_id, str) or not re.fullmatch(r"[a-z]+(?:-[a-z]+)*", case_id):
            raise ValueError("Fixture IDs must be kebab-case")
        if case_id in ids:
            raise ValueError(f"Duplicate fixture ID: {case_id}")
        ids.add(case_id)
        if not isinstance(case.get("input"), str) or not case["input"].strip():
            raise ValueError(f"{case_id}: missing input")
        checks = case.get("checks")
        if not isinstance(checks, dict) or not checks:
            raise ValueError(f"{case_id}: missing acceptance criteria")
        if any(not isinstance(key, str) or not key.strip() or
               not isinstance(value, str) or not value.strip()
               for key, value in checks.items()):
            raise ValueError(f"{case_id}: invalid acceptance criterion")
    return cases


def skill_hash(skill_path):
    text = skill_path.read_text()
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise ValueError("SKILL.md must have a delimited frontmatter block")
    frontmatter = text.split("---\n", 2)[1]
    if not re.search(r"^name: eval-deep-research$", frontmatter, re.MULTILINE):
        raise ValueError("Unexpected skill name")
    if not re.search(r"^description: >-\n\s+\S", frontmatter, re.MULTILINE):
        raise ValueError("Missing folded description")
    if text.count("```") % 2:
        raise ValueError("Unclosed fenced code block")
    links = re.findall(r"\]\(([^)]+)\)", text)
    digest = hashlib.sha256(skill_path.read_bytes())
    references = set()
    for link in links:
        relative = Path(link)
        if relative.is_absolute() or ".." in relative.parts or ":" in link:
            raise ValueError(f"Expected skill-relative link: {link}")
        linked_path = skill_path.parent / relative
        if not linked_path.is_file():
            raise ValueError(f"Missing linked file: {link}")
        if relative.parts[0] == "references":
            references.add(link)
    for link in sorted(references):
        digest.update(b"\0" + link.encode() + b"\0")
        digest.update((skill_path.parent / link).read_bytes())
    return digest.hexdigest()


def evaluate(cases, observation, expected_hashes):
    errors = []
    if not isinstance(observation, dict):
        return ["Observation must be an object"]
    run = observation.get("run")
    if not isinstance(run, dict):
        return ["Missing run metadata"]
    for key in ("model", "configuration", "reviewer", "executed_at"):
        if not isinstance(run.get(key), str) or not run[key].strip():
            errors.append(f"Missing run metadata: {key}")
    for key, expected in expected_hashes.items():
        if run.get(key) != expected:
            errors.append(f"Run does not match evaluated input: {key}")
    observed_cases = observation.get("cases")
    if not isinstance(observed_cases, dict):
        return errors + ["Missing case observations"]
    expected_ids = {case["id"] for case in cases}
    for extra in sorted(set(observed_cases) - expected_ids):
        errors.append(f"Unknown case: {extra}")
    for case in cases:
        case_id = case["id"]
        record = observed_cases.get(case_id)
        if not isinstance(record, dict):
            errors.append(f"{case_id}: unexecuted or missing observation")
            continue
        if not isinstance(record.get("response"), str) or not record["response"].strip():
            errors.append(f"{case_id}: missing actual response")
        trace = record.get("tool_trace")
        if not isinstance(trace, list) or any(
                not isinstance(entry, str) or not entry.strip() for entry in trace):
            errors.append(f"{case_id}: tool_trace must be a list of actual trace entries")
        checks = record.get("checks")
        if not isinstance(checks, dict):
            errors.append(f"{case_id}: missing reviewed checks")
            continue
        for extra in sorted(set(checks) - set(case["checks"])):
            errors.append(f"{case_id}: unknown check {extra}")
        for check_id in case["checks"]:
            result = checks.get(check_id)
            if not isinstance(result, dict) or result.get("passed") is not True:
                errors.append(f"{case_id}/{check_id}: failed or unreviewed")
            elif not isinstance(result.get("evidence"), str) or not result["evidence"].strip():
                errors.append(f"{case_id}/{check_id}: missing review evidence")
    return errors


class EvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.cases = [{"id": "synthetic", "checks": {"no_leak": "No synthetic marker leaks"}}]
        self.hashes = {"skill_sha256": "test-skill", "cases_sha256": "test-cases"}
        self.record = {
            "run": dict(self.hashes, model="synthetic", configuration="none",
                        reviewer="synthetic", executed_at="synthetic"),
            "cases": {"synthetic": {
                "response": "Synthetic evaluator test, not a model run.",
                "tool_trace": [],
                "checks": {"no_leak": {"passed": True, "evidence": "Synthetic response"}},
            }},
        }

    def test_complete_synthetic_record(self):
        self.assertEqual(evaluate(self.cases, self.record, self.hashes), [])

    def test_missing_run_is_not_pass(self):
        self.assertTrue(evaluate(self.cases, {}, self.hashes))

    def test_missing_case_is_not_pass(self):
        self.record["cases"].clear()
        self.assertTrue(evaluate(self.cases, self.record, self.hashes))

    def test_failed_or_nonboolean_result_is_not_pass(self):
        for value in (False, None, 1, "true"):
            with self.subTest(value=value):
                record = copy.deepcopy(self.record)
                record["cases"]["synthetic"]["checks"]["no_leak"]["passed"] = value
                self.assertTrue(evaluate(self.cases, record, self.hashes))

    def test_unsupported_assertion_is_not_pass(self):
        self.record["cases"]["synthetic"]["checks"]["no_leak"]["evidence"] = ""
        self.assertTrue(evaluate(self.cases, self.record, self.hashes))

    def test_input_mismatch_is_not_pass(self):
        self.record["run"]["skill_sha256"] = "different"
        self.assertTrue(evaluate(self.cases, self.record, self.hashes))

    def test_invalid_trace_is_not_pass(self):
        self.record["cases"]["synthetic"]["tool_trace"] = "claimed tool execution"
        self.assertTrue(evaluate(self.cases, self.record, self.hashes))

    def test_unknown_case_or_check_is_not_pass(self):
        self.record["cases"]["unknown"] = {}
        self.record["cases"]["synthetic"]["checks"]["unknown"] = {"passed": True}
        self.assertTrue(evaluate(self.cases, self.record, self.hashes))

    def test_duplicate_keys_cannot_hide_failure(self):
        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            json.loads('{"passed": false, "passed": true}', object_pairs_hook=unique_object)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check-fixtures", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--observations", type=Path)
    parser.add_argument("--skill", type=Path, default=ROOT / "SKILL.md")
    args = parser.parse_args()
    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(EvaluatorTests)
        return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1
    try:
        cases = load_cases(CASES_PATH)
        hashes = {"skill_sha256": skill_hash(args.skill),
                  "cases_sha256": hashlib.sha256(CASES_PATH.read_bytes()).hexdigest()}
        if args.check_fixtures:
            print(json.dumps({"packaging_and_fixtures": "PASS",
                              "model_behavior": "UNEXECUTED",
                              "case_count": len(cases), **hashes}, indent=2))
            return 0
        errors = evaluate(cases, read_json(args.observations), hashes)
        print(json.dumps({"reviewed_run": "FAIL" if errors else "PASS",
                          "errors": errors, **hashes}, indent=2))
        return 1 if errors else 0
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
