"""Combine actual answers, replay events, and separate reviewer judgments.

This records a review; it does not generate answers or infer passing judgments.
Reviews are a JSON mapping: case ID -> check ID -> {passed: bool, evidence: str}.
The existing evaluator then decides whether the complete reviewed run passes.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from check_skill import CASES_PATH, ROOT, evaluate, load_cases, read_json, skill_hash


def build_observation(cases, answers, events, reviews, metadata):
    expected_ids = {case["id"] for case in cases}
    if not isinstance(answers.get("cases"), dict) or set(answers["cases"]) != expected_ids:
        raise ValueError("Answers must contain exactly the required cases")
    if not isinstance(reviews, dict) or set(reviews) != expected_ids:
        raise ValueError("Reviews must contain exactly the required cases")
    if not events or any(not isinstance(event, dict) or
                         event.get("case") not in expected_ids | {"setup"} for event in events):
        raise ValueError("Missing replay events or unexpected case ID")
    records = {}
    for case in cases:
        case_id = case["id"]
        answer = answers["cases"][case_id]
        if not isinstance(answer, dict):
            raise ValueError(f"{case_id}: answer must be an object")
        response = answer.get("response")
        if not isinstance(response, str) or not response.strip():
            raise ValueError(f"{case_id}: actual response is required")
        if not isinstance(reviews[case_id], dict) or set(reviews[case_id]) != set(case["checks"]):
            raise ValueError(f"{case_id}: reviews must cover exactly the required checks")
        case_events = [event for event in events if event["case"] == case_id]
        if not any(event.get("action") == "prompt" for event in case_events):
            raise ValueError(f"{case_id}: no actual prompt retrieval recorded")
        records[case_id] = {
            "response": response,
            "tool_trace": [json.dumps(event, sort_keys=True) for event in case_events],
            "checks": reviews[case_id],
        }
    return {"run": metadata, "cases": records}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("answers", "trace", "reviews", "skill", "output"):
        parser.add_argument(f"--{option}", required=True, type=Path)
    parser.add_argument("--reviewer", required=True)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("Output already exists; choose a new observation filename")
        answers = read_json(args.answers)
        if not isinstance(answers, dict):
            raise ValueError("Answers must be an object")
        for key in ("model", "configuration"):
            if not isinstance(answers.get(key), str) or not answers[key].strip():
                raise ValueError(f"Answer artifact lacks actual run metadata: {key}")
        events = [json.loads(line) for line in args.trace.read_text().splitlines()]
        if any(not isinstance(event, dict) for event in events):
            raise ValueError("Replay events must be objects")
        cases = load_cases(CASES_PATH)
        hashes = {"skill_sha256": skill_hash(args.skill),
                  "cases_sha256": hashlib.sha256(CASES_PATH.read_bytes()).hexdigest()}
        metadata = {
            **hashes, "model": answers["model"], "configuration": answers["configuration"],
            "reviewer": args.reviewer,
            "executed_at": events[0]["timestamp"] if events else "",
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "replay_sha256": hashlib.sha256(
                (ROOT / "tests" / "replay-sources.json").read_bytes()
            ).hexdigest(),
            "adapter_sha256": hashlib.sha256(
                (ROOT / "tests" / "replay_sources.py").read_bytes()
            ).hexdigest(),
        }
        observation = build_observation(cases, answers, events, read_json(args.reviews), metadata)
        errors = evaluate(cases, observation, hashes)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x") as stream:
            stream.write(json.dumps(observation, indent=2) + "\n")
        print(json.dumps({"output": str(args.output),
                          "reviewed_run": "FAIL" if errors else "PASS",
                          "errors": errors}, indent=2))
        return 1 if errors else 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
