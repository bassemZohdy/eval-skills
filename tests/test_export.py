import json
import os
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))
import export_report  # noqa: E402

SAMPLE = os.path.join(ROOT, "tests", "fixtures", "task-queue-legacy")
EXAMPLE = os.path.join(ROOT, "examples", "task-queue", "eval")
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


class ExportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.out = os.path.join(cls.tmp, "export")
        export_report.main([SAMPLE, "--out", cls.out, "--formats", "html,xlsx"])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_html_contents(self):
        with open(os.path.join(self.out, "report.html"), encoding="utf-8") as f:
            h = f.read()
        for needle in ("Beta Queue", "Alpha Queue", "78.0", "76.0", "Gamma Queue", "E-008", "near-tie", "<!doctype html>", "prefers-color-scheme", "<h2>Cost</h2>", "45,360.00", "pilot (100k jobs/month)", "unverified", "Best case if unknowns are provided"):
            self.assertIn(needle, h)

    def test_html_escapes_content(self):
        d = tempfile.mkdtemp()
        try:
            shutil.copytree(SAMPLE, os.path.join(d, "eval"))
            p = os.path.join(d, "eval", "options.json")
            s = open(p, encoding="utf-8").read().replace("Alpha Queue", "Alpha <script>x</script>")
            open(p, "w", encoding="utf-8").write(s)
            export_report.main([os.path.join(d, "eval"), "--out", os.path.join(d, "o"), "--formats", "html"])
            h = open(os.path.join(d, "o", "report.html"), encoding="utf-8").read()
            self.assertNotIn("<script>x</script>", h)
            self.assertIn("&lt;script&gt;", h)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_xlsx_is_wellformed_with_live_formulas(self):
        path = os.path.join(self.out, "report.xlsx")
        with zipfile.ZipFile(path) as z:
            self.assertIsNone(z.testzip())
            names = z.namelist()
            for part in names:
                ET.fromstring(z.read(part))  # every part parses
            wb = z.read("xl/workbook.xml").decode()
            for sheet in ("Ranking", "Scores", "Features", "Cost", "Evidence", "Sensitivity"):
                self.assertIn('name="%s"' % sheet, wb)
            scores = ET.fromstring(z.read("xl/worksheets/sheet2.xml"))
        formulas = [f.text for f in scores.iterfind(".//m:f", NS)]
        self.assertTrue(any(f.startswith("SUMPRODUCT") for f in formulas))
        self.assertIn("SUM(B2:B4)", formulas)
        cached = {c.get("r"): c.find("m:v", NS).text for c in scores.iterfind(".//m:c", NS) if c.find("m:f", NS) is not None}
        self.assertEqual(cached["C6"], "78.0")
        self.assertEqual(cached["D6"], "76.0")

    def test_xlsx_ranking_formulas_reference_scores_sheet(self):
        with zipfile.ZipFile(os.path.join(self.out, "report.xlsx")) as z:
            ranking = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        formulas = [f.text for f in ranking.iterfind(".//m:f", NS)]
        self.assertIn("Scores!C6", formulas)
        self.assertTrue(any(f.startswith("RANK(") for f in formulas))

    def test_xlsx_cost_sheet_has_editable_horizon_and_live_totals(self):
        with zipfile.ZipFile(os.path.join(self.out, "report.xlsx")) as z:
            cost = ET.fromstring(z.read("xl/worksheets/sheet4.xml"))
        cells = {c.get("r"): c for c in cost.iterfind(".//m:c", NS)}
        self.assertEqual(cells["D2"].find("m:f", NS).text, "C2+B2*$B$5")
        self.assertEqual(cells["D2"].find("m:v", NS).text, "15680.0")
        self.assertEqual(cells["B5"].find("m:v", NS).text, "36")

    def test_bias_section_is_in_the_html(self):
        with open(os.path.join(self.out, "report.html"), encoding="utf-8") as f:
            h = f.read()
        self.assertIn("<h2>Bias and assumptions</h2>", h)
        self.assertIn("No requirement is marked as an assumption.", h)
        self.assertIn("Findings by source:", h)

    def test_assumed_components_are_labelled_assumed(self):
        import eval_calc
        d = tempfile.mkdtemp()
        try:
            shutil.copytree(SAMPLE, os.path.join(d, "eval"))
            p = os.path.join(d, "eval", "cost.json")
            c = json.load(open(p, encoding="utf-8"))
            c["options"]["opt-b"]["components"].append({"id": "b-ops", "name": "Operations time", "kind": "fixed_monthly", "amount": 100, "quantity": 4,
                                                        "assumed": True, "assumption_note": "placeholder"})
            json.dump(c, open(p, "w", encoding="utf-8"))
            rep, out = eval_calc.compute(os.path.join(d, "eval"))
            self.assertEqual(rep.errors, [])
            export_report.main([os.path.join(d, "eval"), "--out", os.path.join(d, "o"), "--formats", "html"])
            h = open(os.path.join(d, "o", "report.html"), encoding="utf-8").read()
            self.assertIn("<td>assumed</td>", h)
            self.assertIn("assumed: b-ops", h)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_requires_computed_scores(self):
        d = tempfile.mkdtemp()
        try:
            shutil.copytree(SAMPLE, os.path.join(d, "eval"))
            open(os.path.join(d, "eval", "scores.json"), "w").write('{"cell_values": {}}')
            with self.assertRaises(SystemExit):
                export_report.main([os.path.join(d, "eval"), "--out", os.path.join(d, "o"), "--formats", "html"])
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_unknown_format_rejected(self):
        with self.assertRaises(SystemExit):
            export_report.main([SAMPLE, "--out", self.out, "--formats", "docx"])

    def test_markdown_converter(self):
        h = export_report.md_to_html("# T\n\nSome **bold** and `code` <b>.\n\n- a\n- b\n\n| x | y |\n| --- | --- |\n| 1 | 2 |\n")
        self.assertIn("<h1>T</h1>", h)
        self.assertIn("<strong>bold</strong>", h)
        self.assertIn("&lt;b&gt;", h)
        self.assertIn("<li>a</li>", h)
        ordered = export_report.md_to_html("1. first\n2. second\n")
        self.assertEqual(ordered, "<ol><li>first</li><li>second</li></ol>")
        self.assertIn("<th>x</th>", h)
        self.assertIn("<td>2</td>", h)

    @unittest.skipUnless(export_report.find_browser(), "no Edge or Chrome installed")
    def test_pdf_is_produced(self):
        out = os.path.join(self.tmp, "pdf")
        self.assertEqual(export_report.main([SAMPLE, "--out", out, "--formats", "pdf"]), 0)
        with open(os.path.join(out, "report.pdf"), "rb") as f:
            self.assertEqual(f.read(5), b"%PDF-")
        self.assertFalse(os.path.exists(os.path.join(out, "report.html")))


if __name__ == "__main__":
    unittest.main()
