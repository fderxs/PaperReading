import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from selector_server import normalize_selection_payload


class SelectorServerTests(unittest.TestCase):
    def test_normalize_selection_payload_filters_unselected_items(self):
        payload = {
            "run_date": "2026-04-24",
            "arxiv_date": "2026-04-23_to_2026-04-24",
            "selected_at": "2026-04-24T00:00:00Z",
            "selected_papers": [
                {
                    "paper_id": "P01",
                    "arxiv_id": "2604.11111",
                    "title": "Keep Me",
                    "pdf_url": "https://arxiv.org/pdf/2604.11111",
                    "priority": "A",
                    "notes": "",
                },
                {
                    "paper_id": "P02",
                    "arxiv_id": "2604.22222",
                    "title": "Drop Me",
                    "pdf_url": "https://arxiv.org/pdf/2604.22222",
                    "priority": "",
                    "notes": "   ",
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            normalized = normalize_selection_payload(payload, Path(tmp_dir_str))

        self.assertEqual(normalized["selected_count"], 1)
        self.assertEqual(normalized["selected_papers"][0]["paper_id"], "P01")

    def test_normalize_selection_payload_rejects_invalid_scope(self):
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            with self.assertRaises(ValueError):
                normalize_selection_payload(
                    {"arxiv_date": "../bad", "selected_papers": []},
                    Path(tmp_dir_str),
                )


if __name__ == "__main__":
    unittest.main()
