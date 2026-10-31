import unittest

from record_observations import build_observation


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.cases = [{"id": "synthetic", "checks": {"verified": "Actually reopen source"}}]
        self.answers = {"cases": {"synthetic": {"response": "Synthetic response, not a model run."}}}
        self.events = [{"case": "synthetic", "action": "prompt"}]
        self.reviews = {"synthetic": {
            "verified": {"passed": False, "evidence": "No source reopen in actual trace"}
        }}

    def test_failed_judgment_is_preserved_not_upgraded(self):
        result = build_observation(self.cases, self.answers, self.events, self.reviews, {})
        self.assertIs(result["cases"]["synthetic"]["checks"]["verified"]["passed"], False)
        self.assertEqual(len(result["cases"]["synthetic"]["tool_trace"]), 1)

    def test_missing_prompt_cannot_be_inferred_from_answer(self):
        with self.assertRaisesRegex(ValueError, "no actual prompt"):
            build_observation(self.cases, self.answers,
                              [{"case": "synthetic", "action": "search"}], self.reviews, {})

    def test_missing_or_unexpected_cases_are_rejected(self):
        for answers in ({}, {"synthetic": self.answers["cases"]["synthetic"], "extra": {}}):
            with self.subTest(answers=answers):
                with self.assertRaises(ValueError):
                    build_observation(self.cases, {"cases": answers},
                                      self.events, self.reviews, {})

    def test_unreviewed_checks_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "exactly the required checks"):
            build_observation(self.cases, self.answers, self.events, {"synthetic": {}}, {})

    def test_malformed_answers_and_events_are_rejected(self):
        with self.assertRaises(ValueError):
            build_observation(self.cases, {"cases": {"synthetic": 1}},
                              self.events, self.reviews, {})
        with self.assertRaises(ValueError):
            build_observation(self.cases, self.answers, [None], self.reviews, {})


if __name__ == "__main__":
    unittest.main()
