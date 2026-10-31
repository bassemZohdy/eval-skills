"""Closed synthetic research replay; no network, source mutation, or model invocation.

Each call appends its actual action and result metadata to a named run log under
tests/results/. Prompts do not expose acceptance criteria. Skill/reference reads
are logged separately from source discovery and source opens.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests" / "replay-sources.json"
RESULTS = ROOT / "tests" / "results"


def source_for(case, source_id):
    if source_id in case["sources"]:
        return dict(case["sources"][source_id])
    copies = case.get("copies")
    if copies and source_id.startswith("copy-"):
        suffix = source_id.removeprefix("copy-")
        if suffix.isdigit() and 1 <= int(suffix) <= copies["count"]:
            original = dict(case["sources"][copies["of"]])
            original["title"] = f"Copy {int(suffix)} of {original['title']}"
            original["content"] = (
                f"This is a restatement of {copies['of']}, with no independent evidence. "
                + original["content"]
            )
            return original
    raise ValueError(f"Unknown source: {source_id}")


def replay(case, action, source, query, prior_events):
    if action == "prompt":
        return {"input": case["prompt"]}
    if action == "search":
        if not query.strip():
            raise ValueError("Search requires a nonempty query")
        ids = list(case["sources"])
        ids += [f"copy-{index}" for index in range(1, case.get("copies", {}).get("count", 0) + 1)]
        entries = []
        for source_id in ids:
            record = source_for(case, source_id)
            entries.append({"id": source_id, "title": record["title"],
                            "publisher": record["publisher"], "date": record["date"],
                            "origin": record["origin"], "snippet": record.get("snippet", "")})
        return {"scope": "complete index for this synthetic case only", "results": entries}
    if action == "open":
        record = source_for(case, source)
        return {"id": source, "status": record.get("access", "full"), **record}
    if action == "clarify":
        if not query.strip():
            raise ValueError("Clarify requires the actual question")
        replies = case.get("clarifications", [])
        index = sum(event["action"] == "clarify" for event in prior_events)
        if index >= len(replies):
            raise ValueError("No further synthetic user reply is available")
        return {"reply": replies[index]}
    raise ValueError(f"Unsupported replay action: {action}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", required=True, type=Path)
    parser.add_argument("--log", required=True, type=Path)
    parser.add_argument("--case", default="setup")
    parser.add_argument("--action", required=True,
                        choices=("skill", "reference", "prompt", "search", "open", "clarify"))
    parser.add_argument("--source", default="")
    parser.add_argument("--query", default="")
    args = parser.parse_args()
    try:
        log = args.log.resolve()
        if RESULTS.resolve() not in log.parents:
            raise ValueError("Log must be below tests/results/")
        prior = []
        if log.exists():
            prior = [json.loads(line) for line in log.read_text().splitlines()]
        if args.action == "skill":
            response = {"text": args.skill.read_text()}
        elif args.action == "reference":
            name = Path(args.source)
            if name.name != args.source or name.suffix != ".md":
                raise ValueError("Reference must be a Markdown basename")
            response = {"text": (args.skill.parent / "references" / name).read_text()}
        else:
            data = json.loads(DATA.read_text())
            if data.get("schema") != "deep-researcher-replay/1":
                raise ValueError("Unsupported replay schema")
            if args.case not in data["cases"]:
                raise ValueError(f"Unknown case: {args.case}")
            response = replay(data["cases"][args.case], args.action, args.source, args.query,
                              [event for event in prior if event["case"] == args.case])
            response["notice"] = data["notice"]
        event = {"timestamp": datetime.now(timezone.utc).isoformat(), "case": args.case,
                 "action": args.action, "source": args.source, "query": args.query,
                 "status": response.get("status", "ok"),
                 "response_bytes": len(json.dumps(response).encode())}
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as stream:
            stream.write(json.dumps(event) + "\n")
        print(json.dumps(response, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({"status": "ERROR", "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
