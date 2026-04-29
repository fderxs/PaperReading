#!/usr/bin/env python3
"""Serve selector HTML from a single run directory and save normalized selection JSON."""

import argparse
import json
import os
import re
import tempfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List
from urllib.parse import parse_qs, urlparse


ARXIV_SCOPE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:_to_\d{4}-\d{2}-\d{2})?$")
PRIORITY_VALUES = {"", "A", "B", "C"}


def validate_arxiv_scope(value: object) -> str:
    scope = str(value or "").strip()
    if not scope:
        raise ValueError("Missing arxiv_date value")
    if not ARXIV_SCOPE_RE.fullmatch(scope):
        raise ValueError(f"Invalid arxiv_date value: {scope}")
    return scope


def normalize_selection_payload(payload: Dict[str, object], run_dir: Path) -> Dict[str, object]:
    arxiv_date = validate_arxiv_scope(payload.get("arxiv_date"))
    run_date = str(payload.get("run_date") or run_dir.name).strip() or run_dir.name

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


def find_latest_selector_html(run_dir: Path) -> Path:
    matches = sorted(
        run_dir.glob("vla_planning_selector_*.html"),
        key=lambda path: (path.stat().st_mtime, path.name),
    )
    if not matches:
        raise FileNotFoundError(f"No selector HTML found in {run_dir}")
    return matches[-1]


class SelectorRequestHandler(SimpleHTTPRequestHandler):
    run_dir: Path
    root_dir: Path

    def do_GET(self) -> None:
        if self.path.startswith("/selection-status"):
            self._handle_selection_status()
            return
        if self.path.startswith("/reading-status"):
            self._handle_reading_status()
            return
        if self.path.startswith("/papers/"):
            self._handle_paper_file()
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if self.path.startswith("/papers/"):
            self._handle_paper_file(send_body=False)
            return
        super().do_HEAD()

    def _handle_selection_status(self) -> None:
        try:
            query = parse_qs(urlparse(self.path).query)
            arxiv_date = validate_arxiv_scope(query.get("arxiv_date", [""])[0])
            output_path = self.run_dir / f"selected_vla_planning_papers_{arxiv_date}.json"
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
            status_path = self.run_dir / f"reading_status_{arxiv_date}.json"
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
        except Exception as exc:
            self.send_error(404, str(exc))

    def do_POST(self) -> None:
        if self.path == "/save-reading-status":
            self._handle_save_reading_status()
            return
        if self.path != "/save-selection":
            self.send_error(404, "Unknown endpoint")
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            normalized = normalize_selection_payload(payload, self.run_dir)
            arxiv_date = normalized["arxiv_date"]
            output_path = self.run_dir / f"selected_vla_planning_papers_{arxiv_date}.json"
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

    def _handle_save_reading_status(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            arxiv_date = validate_arxiv_scope(payload.get("arxiv_date"))
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
                    }
                )

            normalized = {
                "run_date": str(payload.get("run_date") or self.run_dir.name).strip() or self.run_dir.name,
                "arxiv_date": arxiv_date,
                "updated_at": str(payload.get("updated_at") or "").strip(),
                "read_papers": read_papers,
            }
            output_path = self.run_dir / f"reading_status_{arxiv_date}.json"
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
            super().__init__(*args, directory=str(run_dir), **kwargs)

    Handler.run_dir = run_dir
    Handler.root_dir = root_dir
    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve selector HTML and save selection JSON.")
    parser.add_argument("--run-dir", type=Path, required=True, help="Date folder to serve and write selected JSON into.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind. Default: 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind. Default: 8765")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    root_dir = run_dir.parent.parent if run_dir.parent.name == "runs" else Path.cwd().resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    selector_html = find_latest_selector_html(run_dir)

    handler = make_handler(run_dir, root_dir)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}/{selector_html.name}"
    print(f"Serving selector directory: {run_dir}")
    print(f"Saving selected JSON into: {run_dir}")
    print(f"Open selector from: {url}")
    print("Press Ctrl-C after saving your selection.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nSelector server stopped.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
