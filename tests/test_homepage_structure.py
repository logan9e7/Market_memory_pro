"""Guard the research-desk homepage and preserve existing workflow selectors."""
import unittest
from html.parser import HTMLParser
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"

class IdParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.tabs = set()
        self.views = set()
        self.go = set()
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if "data-tab" in attrs:
            self.tabs.add(attrs["data-tab"])
        if "data-view" in attrs:
            self.views.add(attrs["data-view"])
        if "data-goto" in attrs:
            self.go.add(attrs["data-goto"])

class HomepageContract(unittest.TestCase):
    def test_all_workflow_ids_are_preserved_without_duplicates(self):
        p = IdParser()
        p.feed((WEB / "index.html").read_text())
        self.assertEqual(len(p.ids), len(set(p.ids)), "Duplicate HTML id")
        for name in ("auth","auth-dialog","auth-form","workspace","identity","metrics",
                     "recent-activity","pending-count","quote-form","snapshot-form",
                     "decision-form","alert-form","password-form","quant-option",
                     "quant-trades","market-form","lab-form","analyze-memory","notice"):
            self.assertIn(name, p.ids, name)
        expected = {"overview","discovery","memory","strategies","lab","quant",
                    "intelligence","opportunities","account"}
        self.assertEqual(p.views, expected)
        self.assertEqual(p.tabs, expected)
        self.assertEqual(p.go, {"discovery","memory","lab"})

    def test_homepage_has_no_invented_feed_or_remote_dependency(self):
        html = (WEB / "index.html").read_text()
        self.assertIn("FIELD NOTE", html)
        self.assertIn("EXAMPLE", html)
        self.assertIn("PAPER EXECUTION ONLY", html)
        self.assertNotIn("cdn.jsdelivr.net", html)
        self.assertNotIn("fonts.googleapis.com", html)

if __name__ == "__main__":
    unittest.main()
