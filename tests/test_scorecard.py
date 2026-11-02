"""The scorecard's defect cases are regression tests: every injected defect must be caught and both samples must stay clean."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import scorecard  # noqa: E402


class Scorecard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.det = scorecard.detection()
        cls.lint = scorecard.lint()

    def test_every_injected_defect_is_caught(self):
        missed = ["%s (%s): %s" % (c["id"], c["rule"], c["detail"]) for c in self.det["cases"] if not c["caught"]]
        self.assertEqual(missed, [])

    def test_the_clean_samples_pass(self):
        clean = [c for c in self.det["cases"] if c["id"].startswith("clean-")]
        self.assertEqual(len(clean), len(scorecard.EXAMPLES))
        self.assertTrue(all(c["caught"] for c in clean), clean)

    def test_instruction_lint_passes(self):
        self.assertEqual([c["check"] + " " + c["detail"] for c in self.lint["checks"] if not c["ok"]], [])

    def test_case_ids_are_unique(self):
        ids = [c[0] for c in scorecard.CASES]
        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
