import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))
import report_draft  # noqa: E402

SAMPLE = os.path.join(ROOT, "tests", "fixtures", "task-queue-legacy")
EXAMPLE = os.path.join(ROOT, "examples", "task-queue", "eval")
PROSE = {
    "recommendation": "The choice between Beta Queue and Alpha Queue is not clear-cut: Beta Queue leads by 2.0 points, inside the tie margin.",
    "confidence": "low", "confidence_why": "Near-tie that flips when low-confidence scores drop.",
    "options": {"opt-b": ["Strong core", "Operability claims unverified"], "opt-a": ["Documented operations", "Slower core"]},
    "bias": "Two candidates.", "cost": "Beta is cheaper.", "sensitivity": "Holds on weights, flips on confidence.",
    "next_steps": ["Verify Beta metrics support."], "risks": ["Operability claims are vendor-only."], "excluded": "Gamma Queue fails the delivery gate.",
}


class ReportDraftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(SAMPLE, self.d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_draft_without_prose_fails_the_check(self):
        report_draft.draft(self.d)
        problems = report_draft.check(self.d)
        self.assertTrue(any("TODO(prose): recommendation" in p for p in problems))

    def test_draft_with_prose_passes_the_check(self):
        report_draft.draft(self.d, PROSE)
        self.assertEqual(report_draft.check(self.d), [])
        text = open(os.path.join(self.d, "report.md"), encoding="utf-8").read()
        for needle in ("78.0", "76.0", "## Sources", "Gamma Queue", "Near-tie"):
            self.assertIn(needle, text)

    def test_check_catches_wrong_leader_and_percentage_confidence(self):
        report_draft.draft(self.d, dict(PROSE, recommendation="Choose Alpha Queue. Confidence 90%."))
        problems = "\n".join(report_draft.check(self.d))
        self.assertIn("does not name the top-ranked option", problems)
        self.assertIn("percentage", problems)

    def test_check_reports_a_missing_report(self):
        os.remove(os.path.join(self.d, "report.md"))
        self.assertEqual(report_draft.check(self.d), ["eval/report.md is missing or empty"])

    def test_cli_exit_codes(self):
        self.assertEqual(report_draft.main(["draft", self.d]), 0)
        self.assertEqual(report_draft.main(["check", self.d]), 1)


if __name__ == "__main__":
    unittest.main()
