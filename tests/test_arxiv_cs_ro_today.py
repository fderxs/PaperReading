import unittest
from datetime import date
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from arxiv_cs_ro_today import build_payload, scrape_papers


SAMPLE_HTML = """
<html>
  <body>
    <h3>Thu, 26 Feb 2026 (showing 2 of 2 entries )</h3>
    <dl>
      <dt>
        [1] <a href="/abs/2602.22154">arXiv:2602.22154</a>
        [<a href="/pdf/2602.22154">pdf</a>, <a href="/html/2602.22154">html</a>]
      </dt>
      <dd>
        <div class="list-title mathjax">
          Title: Position-Based Flocking for Persistent Alignment without Velocity Sensing
        </div>
      </dd>
      <dt>
        [2] <a href="/abs/2602.22118">arXiv:2602.22118</a>
        [<a href="/pdf/2602.22118">pdf</a>]
      </dt>
      <dd>
        <div class="list-title mathjax">Title: System Design of the Ultra Mobility Vehicle</div>
      </dd>
    </dl>

    <h3>Wed, 25 Feb 2026 (showing 1 of 1 entries )</h3>
    <dl>
      <dt>
        [1] <a href="/abs/2602.12345">arXiv:2602.12345</a>
        [<a href="/pdf/2602.12345">pdf</a>]
      </dt>
      <dd>
        <div class="list-title mathjax">Title: Older Robotics Paper</div>
      </dd>
    </dl>
  </body>
</html>
"""


class ArxivRecentParserTests(unittest.TestCase):
    def test_latest_date_is_used_by_default(self):
        parser = scrape_papers(SAMPLE_HTML)

        self.assertEqual(parser.range_start, date(2026, 2, 26))
        self.assertEqual(parser.range_end, date(2026, 2, 26))
        self.assertEqual(len(parser.papers), 2)
        self.assertEqual(
            parser.papers[0].title,
            "Position-Based Flocking for Persistent Alignment without Velocity Sensing",
        )
        self.assertEqual(parser.papers[0].pdf_url, "https://arxiv.org/pdf/2602.22154")
        self.assertEqual(parser.papers[0].arxiv_date, "2026-02-26")

    def test_specific_date_can_be_selected(self):
        parser = scrape_papers(SAMPLE_HTML, target_date=date(2026, 2, 25))

        self.assertEqual(len(parser.papers), 1)
        self.assertEqual(parser.papers[0].title, "Older Robotics Paper")
        self.assertEqual(parser.papers[0].pdf_url, "https://arxiv.org/pdf/2602.12345")
        self.assertEqual(parser.papers[0].arxiv_date, "2026-02-25")

    def test_date_range_is_supported(self):
        parser = scrape_papers(
            SAMPLE_HTML,
            start_date=date(2026, 2, 25),
            end_date=date(2026, 2, 26),
        )
        payload = build_payload(parser, "https://arxiv.org/list/cs.RO/recent?show=2000")

        self.assertEqual(payload["target_date"], "2026-02-25_to_2026-02-26")
        self.assertEqual(payload["paper_count"], 3)
        self.assertEqual(payload["arxiv_start_date"], "2026-02-25")
        self.assertEqual(payload["arxiv_end_date"], "2026-02-26")
        self.assertEqual([paper["arxiv_date"] for paper in payload["papers"]], ["2026-02-26", "2026-02-26", "2026-02-25"])


if __name__ == "__main__":
    unittest.main()
