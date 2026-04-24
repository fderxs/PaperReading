import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from process_selection import download_pdf, is_valid_pdf_file, looks_like_pdf_bytes


class FakeResponse:
    def __init__(self, data: bytes, content_type: str) -> None:
        self._data = data
        self.headers = {"Content-Type": content_type}

    def read(self) -> bytes:
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class ProcessSelectionTests(unittest.TestCase):
    def test_pdf_header_checks(self):
        self.assertTrue(looks_like_pdf_bytes(b"%PDF-1.7\n..."))
        self.assertFalse(looks_like_pdf_bytes(b"<html>not pdf"))

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            valid = tmp_dir / "valid.pdf"
            invalid = tmp_dir / "invalid.pdf"
            valid.write_bytes(b"%PDF-1.7\nbody")
            invalid.write_bytes(b"<html>oops</html>")
            self.assertTrue(is_valid_pdf_file(valid))
            self.assertFalse(is_valid_pdf_file(invalid))

    def test_download_pdf_rejects_non_pdf_response(self):
        record = {
            "arxiv_id": "2604.99999",
            "title": "Broken Download",
            "pdf_url": "https://arxiv.org/pdf/2604.99999",
        }
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            papers_dir = Path(tmp_dir_str)
            with patch("process_selection.urlopen", return_value=FakeResponse(b"<html>oops</html>", "text/html")):
                with self.assertRaises(RuntimeError):
                    download_pdf(record, papers_dir, timeout=10)
            self.assertEqual(list(papers_dir.glob("*.pdf")), [])

    def test_download_pdf_writes_valid_file(self):
        record = {
            "arxiv_id": "2604.12345",
            "title": "Good Download",
            "pdf_url": "https://arxiv.org/pdf/2604.12345",
        }
        pdf_bytes = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n"

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            papers_dir = Path(tmp_dir_str)
            with patch(
                "process_selection.urlopen",
                return_value=FakeResponse(pdf_bytes, "application/pdf"),
            ):
                output = download_pdf(record, papers_dir, timeout=10)

            self.assertTrue(output.exists())
            self.assertTrue(is_valid_pdf_file(output))


if __name__ == "__main__":
    unittest.main()
