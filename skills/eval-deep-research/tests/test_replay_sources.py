import json
from pathlib import Path
import unittest

from replay_sources import replay, source_for


class ReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(
            (Path(__file__).parent / "replay-sources.json").read_text()
        )["cases"]

    def test_discovery_does_not_expose_decisive_content(self):
        results = replay(self.cases["counter-evidence"], "search", "", "benchmark", [])["results"]
        self.assertTrue(results)
        self.assertTrue(all("content" not in source for source in results))
        opened = replay(self.cases["counter-evidence"], "open", results[0]["id"], "", [])
        self.assertIn("median runtime", opened["content"])

    def test_copies_preserve_dependency_family(self):
        case = self.cases["false-corroboration"]
        results = replay(case, "search", "", "performance", [])["results"]
        self.assertEqual(len(results), 11)
        self.assertEqual({source["origin"] for source in results}, {"one-release"})
        self.assertIn("no independent evidence", source_for(case, "copy-10")["content"])

    def test_unknown_or_out_of_range_source_is_rejected(self):
        for source in ("missing", "copy-0", "copy-11", "copy-invalid"):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    source_for(self.cases["false-corroboration"], source)

    def test_partial_and_blocked_access_stay_explicit(self):
        partial = replay(self.cases["partial-access"], "open", "study-page", "", [])
        blocked = replay(self.cases["no-fabrication"], "open", "blocked-record", "", [])
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(blocked["status"], "blocked")
        self.assertNotIn("30%", partial["content"])
        self.assertIn("No decisive content", blocked["content"])

    def test_clarification_is_ordered_and_bounded(self):
        case = self.cases["clarification"]
        first = replay(case, "clarify", "", "Which jurisdiction, version, and use?", [])
        second = replay(case, "clarify", "", "What retention period?", [{"action": "clarify"}])
        self.assertIn("Jurisdiction J", first["reply"])
        self.assertIn("not decided", second["reply"])
        with self.assertRaises(ValueError):
            replay(case, "clarify", "", "More questions?",
                   [{"action": "clarify"}, {"action": "clarify"}])

    def test_empty_queries_are_rejected(self):
        for action in ("search", "clarify"):
            with self.subTest(action=action):
                with self.assertRaises(ValueError):
                    replay(self.cases["current-status"], action, "", " ", [])


if __name__ == "__main__":
    unittest.main()
