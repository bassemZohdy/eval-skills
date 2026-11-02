import os
import re
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))
import export_report  # noqa: E402
import report_draft  # noqa: E402

SAMPLE = os.path.join(ROOT, "examples", "task-queue", "eval")


class ReportOrder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(SAMPLE, self.d)
        self.path = os.path.join(self.d, "report.md")
        report_draft.draft(self.d, {"recommendation": "Alpha Queue leads Beta Queue in a near-tie, so the choice is not clear-cut.", "confidence": "medium", "confidence_why": "The lead is under the meaningful gap.", "options": {"opt-a": ["s1", "g1"], "opt-b": ["s2", "g2"]}, "bias": "b", "cost": "c",
                                    "sensitivity": "s", "next_steps": ["n"], "risks": ["r"], "excluded": "e"})
        self.text = open(self.path, encoding="utf-8").read()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def problems(self, text=None):
        if text is not None:
            open(self.path, "w", encoding="utf-8").write(text)
        return report_draft.check(self.d)

    def test_draft_is_in_decision_order(self):
        titles = re.findall(r"(?m)^## (.+)$", self.text)
        self.assertEqual(titles[:2], ["Eligibility", "Decision recommendation"])
        self.assertLess(titles.index("Gates"), titles.index("Criteria and weights"))
        self.assertLess(titles.index("Criteria and weights"), titles.index("Feature-by-feature comparison"))
        self.assertEqual(titles[-1], "Sources")
        self.assertEqual(self.problems(), [])

    def test_check_flags_sections_out_of_order(self):
        text = self.text.replace("## Gates", "## Zzz").replace("## Sources", "## Gates") + "\n## Sources\n"
        self.assertTrue(any("out of decision order" in p for p in self.problems(text)))

    def test_exporter_puts_sections_in_order(self):
        shuffled = ["Sources", "Gates", "Eligibility", "Decision recommendation"]
        got = export_report.order_sections(shuffled)
        self.assertEqual(got, ["Eligibility", "Decision recommendation", "Gates", "Sources"])

    def test_unknown_section_stays_after_its_neighbour(self):
        got = export_report.order_sections(["Sources", "Gates", "Notes on gates"])
        self.assertEqual(got, ["Gates", "Notes on gates", "Sources"])

    def test_process_words_are_flagged(self):
        self.assertTrue(any("process wording" in p for p in self.problems(self.text + "\nThis round we re-checked the pricing.\n")))
        self.assertEqual(self.problems(self.text + "\nThe vendor operates around 5 sites.\n"), [])

    def test_more_than_ten_caveats_are_flagged(self):
        text = self.text.replace("## Sources", "".join("- extra caveat %d\n" % i for i in range(11)) + "\n## Sources", 1)
        self.assertTrue(any("keep at most 10" in p for p in self.problems(text)))

    def test_caveat_repeating_gate_text_is_flagged(self):
        text = self.text.replace("## Sources", "- At-most-once delivery only\n\n## Sources", 1)
        self.assertTrue(any("repeats gate text" in p for p in self.problems(text)))


if __name__ == "__main__":
    unittest.main()
