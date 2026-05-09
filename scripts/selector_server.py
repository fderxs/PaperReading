#!/usr/bin/env python3
"""Serve the reading dashboard and persist local reading/selection state."""

import argparse
import base64
import json
import mimetypes
import os
import re
import tempfile
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List
from urllib.parse import parse_qs, unquote, urlparse


ARXIV_SCOPE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:_to_\d{4}-\d{2}-\d{2})?$")
RUN_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PRIORITY_VALUES = {"", "A", "B", "C"}
CLIENT_DISCONNECT_ERRORS = (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)


def validate_arxiv_scope(value: object) -> str:
    scope = str(value or "").strip()
    if not scope:
        raise ValueError("Missing arxiv_date value")
    if not ARXIV_SCOPE_RE.fullmatch(scope):
        raise ValueError(f"Invalid arxiv_date value: {scope}")
    return scope


def validate_run_date(value: object, default: str) -> str:
    run_date = str(value or default).strip() or default
    if not RUN_DATE_RE.fullmatch(run_date):
        raise ValueError(f"Invalid run_date value: {run_date}")
    return run_date


def normalize_selection_payload(payload: Dict[str, object], run_dir: Path) -> Dict[str, object]:
    arxiv_date = validate_arxiv_scope(payload.get("arxiv_date"))
    run_date = validate_run_date(payload.get("run_date"), run_dir.name)

    raw_selected = payload.get("selected_papers", [])
    if not isinstance(raw_selected, list):
        raise ValueError("selected_papers must be a list")

    selected_papers: List[Dict[str, str]] = []
    seen_keys = set()
    for raw in raw_selected:
        if not isinstance(raw, dict):
            raise ValueError("Each selected paper must be an object")

        paper_id = str(raw.get("paper_id") or "").strip()
        arxiv_id = str(raw.get("arxiv_id") or "").strip()
        title = str(raw.get("title") or "").strip()
        pdf_url = str(raw.get("pdf_url") or "").strip()
        priority = str(raw.get("priority") or "").strip().upper()
        notes = str(raw.get("notes") or "").strip()

        if priority not in PRIORITY_VALUES:
            raise ValueError(f"Invalid priority value: {priority}")
        if not (priority or notes):
            continue
        if not title or not pdf_url:
            raise ValueError("Each selected paper must include title and pdf_url")

        dedupe_key = arxiv_id or paper_id or title
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        selected_papers.append(
            {
                "paper_id": paper_id,
                "arxiv_id": arxiv_id,
                "title": title,
                "pdf_url": pdf_url,
                "priority": priority,
                "notes": notes,
            }
        )

    return {
        "source": str(payload.get("source") or "").strip(),
        "run_date": run_date,
        "arxiv_date": arxiv_date,
        "selected_at": str(payload.get("selected_at") or "").strip(),
        "selected_count": len(selected_papers),
        "selected_papers": selected_papers,
    }


def write_json_atomic(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.stem}_",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    os.replace(temp_path, path)


class SelectorRequestHandler(SimpleHTTPRequestHandler):
    run_dir: Path
    root_dir: Path

    def _send_error_quietly(self, code: int, message: str) -> None:
        try:
            self.send_error(code, message)
        except CLIENT_DISCONNECT_ERRORS:
            return

    def do_GET(self) -> None:
        if self.path.startswith("/selection-status"):
            self._handle_selection_status()
            return
        if self.path.startswith("/reading-status"):
            self._handle_reading_status()
            return
        if self.path.startswith("/cn-pdf-info"):
            self._handle_cn_pdf_info()
            return
        if self.path.startswith("/cn-pdf-page"):
            self._handle_cn_pdf_page()
            return
        if self.path.startswith("/papers/"):
            self._handle_paper_file()
            return
        if self.path.startswith("/runs/"):
            self._handle_run_file()
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if self.path.startswith("/papers/"):
            self._handle_paper_file(send_body=False)
            return
        if self.path.startswith("/runs/"):
            self._handle_run_file(send_body=False)
            return
        super().do_HEAD()

    def _resolve_run_dir(self, raw_run_date: object | None = None) -> Path:
        run_date = validate_run_date(raw_run_date, self.run_dir.name)
        target = (self.root_dir / "runs" / run_date).resolve()
        runs_dir = (self.root_dir / "runs").resolve()
        if target.parent != runs_dir or not target.exists():
            raise FileNotFoundError(run_date)
        return target

    def _handle_selection_status(self) -> None:
        try:
            query = parse_qs(urlparse(self.path).query)
            arxiv_date = validate_arxiv_scope(query.get("arxiv_date", [""])[0])
            run_dir = self._resolve_run_dir(query.get("run_date", [self.run_dir.name])[0])
            output_path = run_dir / f"selected_vla_planning_papers_{arxiv_date}.json"
            body = json.dumps(
                {"ok": True, "exists": output_path.exists(), "path": str(output_path)},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            body = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def _handle_reading_status(self) -> None:
        try:
            query = parse_qs(urlparse(self.path).query)
            arxiv_date = validate_arxiv_scope(query.get("arxiv_date", [""])[0])
            run_dir = self._resolve_run_dir(query.get("run_date", [self.run_dir.name])[0])
            status_path = run_dir / f"reading_status_{arxiv_date}.json"
            status = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}
            body = json.dumps(
                {"ok": True, "exists": status_path.exists(), "path": str(status_path), "status": status},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            body = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def _handle_paper_file(self, send_body: bool = True) -> None:
        try:
            raw_name = Path(urlparse(self.path).path).name
            if not raw_name.endswith(".pdf") or raw_name != Path(raw_name).name:
                raise ValueError("Invalid PDF filename")
            pdf_path = (self.root_dir / "papers" / raw_name).resolve()
            papers_dir = (self.root_dir / "papers").resolve()
            if pdf_path.parent != papers_dir or not pdf_path.exists():
                raise FileNotFoundError(raw_name)
            data_size = pdf_path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(data_size))
            self.end_headers()
            if not send_body:
                return
            with pdf_path.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except CLIENT_DISCONNECT_ERRORS:
            return
        except Exception as exc:
            self._send_error_quietly(404, str(exc))

    def _handle_run_file(self, send_body: bool = True) -> None:
        try:
            raw_path = unquote(urlparse(self.path).path)
            parts = raw_path.lstrip("/").split("/", 2)
            if len(parts) != 3 or parts[0] != "runs":
                raise ValueError("Invalid run file path")
            run_dir = self._resolve_run_dir(parts[1])
            relative_path = parts[2]
            if not relative_path or relative_path.startswith("/") or "\\" in relative_path:
                raise ValueError("Invalid run file path")
            target = (run_dir / relative_path).resolve()
            if not str(target).startswith(str(run_dir) + os.sep) or not target.is_file():
                raise FileNotFoundError(relative_path)
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            data_size = target.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(data_size))
            self.end_headers()
            if not send_body:
                return
            with target.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except CLIENT_DISCONNECT_ERRORS:
            return
        except Exception as exc:
            self._send_error_quietly(404, str(exc))

    def _handle_cn_pdf_info(self) -> None:
        try:
            query = parse_qs(urlparse(self.path).query)
            run_dir = self._resolve_run_dir(query.get("run_date", [self.run_dir.name])[0])
            pdf_path = self._resolve_cn_pdf_path(query.get("path", [""])[0], run_dir)
            try:
                import fitz  # type: ignore
            except ImportError as exc:
                raise RuntimeError("PyMuPDF is required for PDF page rendering. Install with: python3 -m pip install PyMuPDF") from exc
            with fitz.open(pdf_path) as doc:
                pages = [
                    {"page_index": index, "width": doc[index].rect.width, "height": doc[index].rect.height}
                    for index in range(doc.page_count)
                ]
            body = json.dumps(
                {"ok": True, "path": str(pdf_path), "page_count": len(pages), "pages": pages},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            body = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def _handle_cn_pdf_page(self) -> None:
        try:
            query = parse_qs(urlparse(self.path).query)
            run_dir = self._resolve_run_dir(query.get("run_date", [self.run_dir.name])[0])
            pdf_path = self._resolve_cn_pdf_path(query.get("path", [""])[0], run_dir)
            page_index = int(query.get("page", ["0"])[0])
            zoom = float(query.get("zoom", ["1.45"])[0])
            zoom = min(2.4, max(0.5, zoom))
            try:
                import fitz  # type: ignore
            except ImportError as exc:
                raise RuntimeError("PyMuPDF is required for PDF page rendering. Install with: python3 -m pip install PyMuPDF") from exc
            with fitz.open(pdf_path) as doc:
                if page_index < 0 or page_index >= doc.page_count:
                    raise ValueError("Invalid page index")
                page = doc[page_index]
                pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                data = pixmap.tobytes("png")
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            body = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path == "/save-reading-status":
            self._handle_save_reading_status()
            return
        if self.path == "/save-cn-pdf":
            self._handle_save_cn_pdf()
            return
        if self.path != "/save-selection":
            self.send_error(404, "Unknown endpoint")
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            run_dir = self._resolve_run_dir(payload.get("run_date"))
            normalized = normalize_selection_payload(payload, run_dir)
            arxiv_date = normalized["arxiv_date"]
            output_path = run_dir / f"selected_vla_planning_papers_{arxiv_date}.json"
            write_json_atomic(output_path, normalized)
        except Exception as exc:
            body = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        body = json.dumps({"ok": True, "path": str(output_path)}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _resolve_cn_pdf_path(self, raw_path: object, run_dir: Path | None = None) -> Path:
        run_dir = run_dir or self.run_dir
        rel_path = str(raw_path or "").strip()
        if not rel_path:
            raise ValueError("Missing PDF path")
        if rel_path.startswith("/runs/"):
            parts = rel_path.lstrip("/").split("/", 2)
            if len(parts) != 3:
                raise ValueError("Invalid PDF path")
            run_dir = self._resolve_run_dir(parts[1])
            rel_path = parts[2]
        if rel_path.startswith("/") or "\\" in rel_path:
            raise ValueError("PDF path must be relative")

        target = (run_dir / rel_path).resolve()
        paper_cn_dir = (run_dir / "paper_cn").resolve()
        if target.name != "paper_cn.pdf":
            raise ValueError("Only paper_cn.pdf can be overwritten")
        if target.parent == paper_cn_dir or not str(target).startswith(str(paper_cn_dir) + os.sep):
            raise ValueError("PDF path must stay under paper_cn/")
        if not target.exists():
            raise FileNotFoundError(rel_path)
        return target

    def _handle_save_cn_pdf(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 120 * 1024 * 1024:
                raise ValueError("Request body too large")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            run_dir = self._resolve_run_dir(payload.get("run_date"))
            target = self._resolve_cn_pdf_path(payload.get("path"), run_dir)
            pdf_base64 = str(payload.get("pdf_base64") or "")
            if "," in pdf_base64:
                pdf_base64 = pdf_base64.split(",", 1)[1]
            pdf_bytes = base64.b64decode(pdf_base64, validate=True)
            if not pdf_bytes.startswith(b"%PDF-"):
                raise ValueError("Uploaded content is not a PDF")

            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup_path = target.with_name(f"{target.stem}.before_notes_{timestamp}{target.suffix}")
            if target.exists():
                backup_path.write_bytes(target.read_bytes())

            with tempfile.NamedTemporaryFile("wb", dir=target.parent, prefix=".paper_cn_", suffix=".tmp", delete=False) as handle:
                temp_path = Path(handle.name)
                handle.write(pdf_bytes)
            os.replace(temp_path, target)
        except Exception as exc:
            body = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        body = json.dumps(
            {"ok": True, "path": str(target), "backup_path": str(backup_path)},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_save_reading_status(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            arxiv_date = validate_arxiv_scope(payload.get("arxiv_date"))
            run_dir = self._resolve_run_dir(payload.get("run_date"))
            raw_read_papers = payload.get("read_papers", [])
            if not isinstance(raw_read_papers, list):
                raise ValueError("read_papers must be a list")

            read_papers: List[Dict[str, object]] = []
            for raw in raw_read_papers:
                if not isinstance(raw, dict):
                    raise ValueError("Each read paper must be an object")
                read_papers.append(
                    {
                        "reading_id": str(raw.get("reading_id") or "").strip(),
                        "selector_id": str(raw.get("selector_id") or raw.get("paper_id") or "").strip(),
                        "arxiv_id": str(raw.get("arxiv_id") or "").strip(),
                        "read": bool(raw.get("read")),
                        "read_at": str(raw.get("read_at") or "").strip(),
                        "intensive": bool(raw.get("intensive")),
                        "intensive_at": str(raw.get("intensive_at") or "").strip(),
                    }
                )

            normalized = {
                "run_date": run_dir.name,
                "arxiv_date": arxiv_date,
                "updated_at": str(payload.get("updated_at") or "").strip(),
                "read_papers": read_papers,
            }
            output_path = run_dir / f"reading_status_{arxiv_date}.json"
            write_json_atomic(output_path, normalized)
        except Exception as exc:
            body = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        body = json.dumps({"ok": True, "path": str(output_path)}, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def make_handler(run_dir: Path, root_dir: Path) -> type[SelectorRequestHandler]:
    class Handler(SelectorRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root_dir), **kwargs)

    Handler.run_dir = run_dir
    Handler.root_dir = root_dir
    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve reading dashboard HTML and save local state JSON.")
    parser.add_argument("--run-dir", type=Path, required=True, help="Date folder to serve and write selected JSON into.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind. Default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind. Default: 8765")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    root_dir = run_dir.parent.parent if run_dir.parent.name == "runs" else Path.cwd().resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    handler = make_handler(run_dir, root_dir)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving project root: {root_dir}")
    print(f"Saving local JSON state into: {run_dir}")
    print("Press Ctrl-C when done.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard server stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
