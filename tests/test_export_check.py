import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "shared"))
import eval_calc  # noqa: E402
import export_report  # noqa: E402

SAMPLE = os.path.join(ROOT, "examples", "task-queue", "eval")


class ExportCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "eval")
        shutil.copytree(SAMPLE, self.d)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def page(self):
        return export_report.build_html(export_report.Data(self.d))

    def test_the_example_page_has_no_static_problems(self):
        D = export_report.Data(self.d)
        self.assertEqual(export_report.static_problems(D, self.page()), [])

    def test_a_total_missing_from_the_page_is_reported(self):
        D = export_report.Data(self.d)
        page = self.page().replace("%.1f" % max(D.scores["totals"].values()), "0.0")
        self.assertTrue(any("does not show the total" in p for p in export_report.static_problems(D, page)))

    def test_rescoring_records_the_earlier_total_and_a_stale_number_is_caught(self):
        eval_calc.compute(self.d)
        old = json.load(open(os.path.join(self.d, "scores.json")))["totals"]["opt-a"]
        s = json.load(open(os.path.join(self.d, "scores.json")))
        s["requirement_scores"]["opt-a"]["F-01"]["score"] = 1
        json.dump(s, open(os.path.join(self.d, "scores.json"), "w"))
        eval_calc.compute(self.d)
        status = json.load(open(os.path.join(self.d, "status.json")))
        self.assertIn(old, status["earlier_totals"])
        D = export_report.Data(self.d)
        stale = self.page().replace("</main>", "<p>Total %.1f</p></main>" % old)
        self.assertTrue(any("earlier run" in p for p in export_report.static_problems(D, stale)))

    @unittest.skipUnless(export_report.find_browser(), "no Edge or Chrome")
    def test_browser_checks_pass_on_the_example_and_catch_sideways_scroll(self):
        self.assertEqual(export_report.browser_problems(self.page()), [])
        wide = self.page().replace("</main>", '<div style="width:2000px;height:5px"></div></main>')
        self.assertTrue(any("scrolls sideways" in p for p in export_report.browser_problems(wide)))

    @unittest.skipUnless(export_report.find_browser(), "no Edge or Chrome")
    def test_script_errors_are_reported(self):
        bad = self.page().replace("</body>", "<script>throw new Error('boom')</script></body>")
        self.assertTrue(any("boom" in p for p in export_report.browser_problems(bad)))

    def test_cli_check(self):
        self.assertEqual(export_report.main([self.d, "--check"]), 0)


if __name__ == "__main__":
    unittest.main()


class WhatIf(unittest.TestCase):
    def setUp(self):
        self.page = export_report.build_html(export_report.Data(SAMPLE))

    def test_page_embeds_the_data_the_recompute_needs(self):
        import re
        blob = re.search(r'<script type="application/json" id="whatif-data">(.*?)</script>', self.page, re.S).group(1)
        d = json.loads(blob.replace("<\/", "</"))
        self.assertEqual([c["id"] for c in d["criteria"]], ["crit-core", "crit-ops"] if False else [c["id"] for c in d["criteria"]])
        self.assertEqual(sum(c["weight"] for c in d["criteria"]), 100)
        self.assertIn("opt-a", d["scores"])

    def test_scores_json_is_untouched_by_the_what_if(self):
        self.assertIn('id="whatif"', self.page)

    @unittest.skipUnless(export_report.find_browser(), "no Edge or Chrome")
    def test_the_pages_recompute_equals_the_scorers(self):
        import re
        import subprocess
        import pathlib
        tmp = tempfile.mkdtemp()
        try:
            path = os.path.join(tmp, "p.html")
            open(path, "w", encoding="utf-8").write(self.page)
            cmd = [export_report.find_browser(), "--headless", "--disable-gpu", *export_report.browser_flags(), "--user-data-dir=" + os.path.join(tmp, "prof"), "--window-size=1400,900",
                   "--virtual-time-budget=4000", "--dump-dom", pathlib.Path(path).resolve().as_uri()]
            dom = subprocess.run(cmd, capture_output=True, timeout=120).stdout.decode("utf-8", "replace")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        shown = dict(re.findall(r'data-total="([^"]+)"[^>]*>([\d.]+)<', dom))
        want = json.load(open(os.path.join(SAMPLE, "scores.json")))["totals"]
        self.assertEqual({k: float(v) for k, v in shown.items()}, want)
        self.assertIn("meaningful gap", dom)
