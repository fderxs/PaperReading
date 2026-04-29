#!/usr/bin/env python3
"""Process selected papers: record preference, download PDFs, create analysis files."""

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from urllib.request import Request, urlopen

from render_reading_dashboard import write_reading_dashboard


USER_AGENT = "paperreading-post-selection/1.0 (+https://arxiv.org)"
ROOT_DIR = Path(__file__).resolve().parent.parent
PDF_HEADER = b"%PDF-"


def find_latest_run_dir(root: Path) -> Path:
    runs_dir = root / "runs"
    dirs = [
        child
        for child in runs_dir.iterdir()
        if child.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", child.name)
    ]
    if not dirs:
        raise FileNotFoundError("No YYYY-MM-DD run directory found.")
    return max(dirs, key=lambda path: path.name)


def find_selection_json(run_dir: Path) -> Path:
    matches = sorted(
        run_dir.glob("selected_vla_planning_papers_*.json"),
        key=lambda path: (path.stat().st_mtime, path.name),
    )
    if not matches:
        raise FileNotFoundError(f"No selected_vla_planning_papers_*.json found in {run_dir}")
    return matches[-1]


def load_json(path: Path) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_filename(value: str, max_len: int = 90) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")[:max_len]


def arxiv_id_from_pdf_url(pdf_url: str) -> str:
    match = re.search(r"/pdf/([^/?#]+)", pdf_url)
    return match.group(1).removesuffix(".pdf") if match else ""


def load_shortlist(run_dir: Path, arxiv_date: str) -> Dict[str, object]:
    shortlist_path = run_dir / f"shortlist_vla_planning_{arxiv_date}.json"
    if shortlist_path.exists():
        return load_json(shortlist_path)

    # Fallback for the first manually-created run.
    selected = load_json(find_selection_json(run_dir))
    papers = []
    for index, paper in enumerate(selected.get("selected_papers", []), 1):
        papers.append(
            {
                "paper_id": paper.get("paper_id") or f"P{index:02d}",
                "arxiv_id": paper.get("arxiv_id") or arxiv_id_from_pdf_url(paper.get("pdf_url", "")),
                "title": paper.get("title", ""),
                "pdf_url": paper.get("pdf_url", ""),
                "authors": [],
                "summary": "",
                "tags": [],
                "reason": "",
            }
        )
    return {
        "run_date": run_dir.name,
        "arxiv_date": arxiv_date,
        "papers": papers,
    }


def merged_records(
    shortlist: Dict[str, object],
    selection: Dict[str, object],
    selection_path: Path,
) -> List[Dict[str, object]]:
    selected_by_arxiv = {
        paper.get("arxiv_id"): paper for paper in selection.get("selected_papers", [])
    }
    selected_by_id = {
        paper.get("paper_id"): paper
        for paper in selection.get("selected_papers", [])
        if not paper.get("arxiv_id")
    }
    run_date = str(selection.get("run_date") or shortlist.get("run_date") or selection_path.parent.name)
    arxiv_date = str(selection.get("arxiv_date") or shortlist.get("arxiv_date") or "")
    now = datetime.now(timezone.utc).isoformat()

    records = []
    for paper in shortlist.get("papers", []):
        selected = selected_by_arxiv.get(paper.get("arxiv_id")) or selected_by_id.get(paper.get("paper_id"))
        records.append(
            {
                "recorded_at": now,
                "run_date": run_date,
                "arxiv_date": arxiv_date,
                "selection_source": str(selection_path),
                "paper_id": paper.get("paper_id", ""),
                "arxiv_id": paper.get("arxiv_id", ""),
                "title": paper.get("title", ""),
                "pdf_url": paper.get("pdf_url", ""),
                "tags": paper.get("tags", []),
                "decision": "selected" if selected else "skipped",
                "priority": selected.get("priority", "") if selected else "",
                "notes": selected.get("notes", "") if selected else "",
                "authors": paper.get("authors", []),
                "summary": paper.get("summary", ""),
            }
        )
    return records


def rewrite_preference_jsonl(root: Path, run_date: str, arxiv_date: str, records: List[Dict[str, object]]) -> None:
    data_dir = root / "data"
    data_dir.mkdir(exist_ok=True)
    path = data_dir / "paper_preference_records.jsonl"
    existing: List[Dict[str, object]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if (
                item.get("run_date") == run_date
                and item.get("arxiv_date") == arxiv_date
                and item.get("preference_stage") != "intensive_translation"
            ):
                continue
            existing.append(item)

    all_records = existing + records
    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in all_records),
        encoding="utf-8",
    )


def looks_like_pdf_bytes(data: bytes) -> bool:
    return data.startswith(PDF_HEADER)


def is_valid_pdf_file(path: Path) -> bool:
    if not path.exists() or not path.is_file() or path.stat().st_size < len(PDF_HEADER):
        return False
    try:
        with path.open("rb") as handle:
            return handle.read(len(PDF_HEADER)) == PDF_HEADER
    except OSError:
        return False


def cleanup_invalid_pdf_candidates(candidates: List[Path]) -> None:
    for path in candidates:
        if path.exists() and not is_valid_pdf_file(path):
            path.unlink()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "wb",
        dir=path.parent,
        prefix=f".{path.stem}_",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
        handle.write(data)

    os.replace(temp_path, path)


def download_pdf(record: Dict[str, object], papers_dir: Path, timeout: int) -> Path:
    papers_dir.mkdir(parents=True, exist_ok=True)
    arxiv_id = str(record.get("arxiv_id", "unknown"))
    title = str(record.get("title", "paper"))
    existing = sorted(papers_dir.glob(f"{arxiv_id}_*.pdf"))
    cleanup_invalid_pdf_candidates(existing)
    existing = sorted(papers_dir.glob(f"{arxiv_id}_*.pdf"))
    if existing:
        return existing[0]

    out = papers_dir / f"{arxiv_id}_{safe_filename(title)}.pdf"
    if out.exists() and is_valid_pdf_file(out):
        return out
    if out.exists() and not is_valid_pdf_file(out):
        out.unlink()

    pdf_url = str(record.get("pdf_url", ""))
    if not pdf_url:
        raise ValueError(f"Missing pdf_url for {arxiv_id or title}")
    if not pdf_url.endswith(".pdf"):
        pdf_url = f"{pdf_url}.pdf"
    request = Request(
        pdf_url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.1"},
    )
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
        content_type = str(response.headers.get("Content-Type", "")).lower()

    if not looks_like_pdf_bytes(data):
        raise RuntimeError(
            f"Downloaded content for {arxiv_id or title} is not a valid PDF "
            f"(Content-Type: {content_type or 'unknown'})."
        )

    atomic_write_bytes(out, data)
    if not is_valid_pdf_file(out):
        raise RuntimeError(f"Saved PDF for {arxiv_id or title} failed validation.")
    return out


def analysis_filename(record: Dict[str, object]) -> str:
    arxiv_id = str(record.get("arxiv_id", "unknown"))
    slug = safe_filename(str(record.get("title", "paper")).lower(), max_len=60)
    return f"{arxiv_id}_{slug}.md"


def create_analysis(record: Dict[str, object], pdf_path: Path, run_dir: Path, template: str, overwrite: bool) -> Path:
    analyses_dir = run_dir / "analyses"
    analyses_dir.mkdir(exist_ok=True)
    arxiv_id = str(record.get("arxiv_id", ""))
    existing = sorted(analyses_dir.glob(f"{arxiv_id}_*.md"))
    if existing and not overwrite:
        return existing[0]

    out = analyses_dir / analysis_filename(record)
    if out.exists() and not overwrite:
        return out

    relative_pdf = Path("../../..") / "papers" / pdf_path.name
    content = template
    replacements = {
        "{{title}}": str(record.get("title", "")),
        "{{arxiv_id}}": str(record.get("arxiv_id", "")),
        "{{local_pdf_path}}": str(relative_pdf),
        "{{arxiv_url}}": f"https://arxiv.org/abs/{record.get('arxiv_id', '')}",
        "{{priority}}": str(record.get("priority", "")),
        "{{notes}}": str(record.get("notes", "")) or "无",
        "{{abstract}}": str(record.get("summary", "")) or "未从 shortlist 中获取到摘要；后续精读时可从 PDF 中补充。",
    }
    for old, new in replacements.items():
        content = content.replace(old, new)

    out.write_text(content, encoding="utf-8")
    return out


def escape_table(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def write_analysis_task(
    root: Path,
    run_dir: Path,
    arxiv_date: str,
    selection_path: Path,
    selection_record_path: Path,
    analysis_items: List[Dict[str, object]],
) -> Path:
    task_path = run_dir / f"llm_analysis_task_{arxiv_date}.md"
    template_path = root / "templates" / "analysis_template.md"
    rows = []
    for item in analysis_items:
        record = item["record"]
        rows.append(
            "| {priority} | {arxiv_id} | {title} | {notes} | {pdf} | {analysis} |".format(
                priority=escape_table(record.get("priority", "")),
                arxiv_id=escape_table(record.get("arxiv_id", "")),
                title=escape_table(record.get("title", "")),
                notes=escape_table(record.get("notes", "") or "无"),
                pdf=escape_table(item["pdf_path"]),
                analysis=escape_table(item["analysis_path"]),
            )
        )

    table = "\n".join(rows)
    content = f"""# LLM-in-the-loop 精读任务：{arxiv_date}

本文件由脚本自动生成，没有调用任何大模型 API。请把这个任务交给当前 Codex/Cursor 对话里的我，让我基于用户选择、备注和本地 PDF 完成逐篇精讲。

## 输入文件

- 用户选择 JSON：`{selection_path}`
- 本轮选择记录：`{selection_record_path}`
- 历史偏好记录：`{root / 'data' / 'paper_preference_records.jsonl'}`
- 分析模板：`{template_path}`

## 我需要完成的事

1. 读取用户选择 JSON、选择记录、历史偏好和下表中的本地 PDF。
2. 按用户优先级和备注决定精读深度，优先处理 `A`，其次 `B`，最后 `C`。
3. 逐篇完善对应分析 Markdown，不要只停留在摘要改写。
4. 若已有分析内容，不要粗暴覆盖；应保留有价值内容并补充/重构。
5. 分析内容必须包含：一句话结论、论文定位、背景动机、核心贡献、方法详解、实验结果、局限疑问、是否值得继续读。
6. 如果 PDF 中有关键图表，应只挑真正有帮助的 1 到 3 张插入正文相关段落中，例如方法图放在 `5. 方法详解`，主结果/消融表放在 `6. 实验与结果`；不要在文末追加一个“图表附件大全”。
7. 图表之外的完整抽取结果保留在 `runs/{run_dir.name}/artifacts/`、`figures/` 和 `tables/` 中，分析正文里不要把所有图表都列一遍。
8. 对用户备注中的具体问题要显式回答。

## 待精读论文

| 优先级 | arXiv ID | 标题 | 用户备注 | PDF | 分析文件 |
|---|---|---|---|---|---|
{table}
"""
    task_path.write_text(content, encoding="utf-8")
    return task_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Process selected paper JSON from the selector HTML.")
    parser.add_argument("--root", type=Path, default=ROOT_DIR, help="PaperReading root directory.")
    parser.add_argument("--run-dir", type=Path, default=None, help="Run folder. Default: latest YYYY-MM-DD folder.")
    parser.add_argument("--selection", type=Path, default=None, help="Selected JSON path. Default: latest in run folder.")
    parser.add_argument("--timeout", type=int, default=120, help="PDF download timeout.")
    parser.add_argument("--overwrite-analysis", action="store_true", help="Overwrite existing analysis files.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    run_dir = (args.run_dir.resolve() if args.run_dir else find_latest_run_dir(root))
    selection_path = (args.selection.resolve() if args.selection else find_selection_json(run_dir))
    selection = load_json(selection_path)
    arxiv_date = str(selection.get("arxiv_date") or re.search(r"(\d{4}-\d{2}-\d{2})", selection_path.name).group(1))
    shortlist = load_shortlist(run_dir, arxiv_date)
    records = merged_records(shortlist, selection, selection_path)

    run_date = str(selection.get("run_date") or shortlist.get("run_date") or run_dir.name)
    rewrite_preference_jsonl(root, run_date, arxiv_date, records)

    selection_record_path = run_dir / f"selection_record_{arxiv_date}.json"
    selection_record_path.write_text(
        json.dumps(
            {
                "run_date": run_date,
                "arxiv_date": arxiv_date,
                "selection_source": str(selection_path),
                "record_scope": "papers shortlisted and shown to the user",
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    template = (root / "templates" / "analysis_template.md").read_text(encoding="utf-8")
    papers_dir = root / "papers"
    selected_records = [record for record in records if record["decision"] == "selected"]
    analysis_paths = []
    analysis_items: List[Dict[str, object]] = []
    for record in selected_records:
        pdf_path = download_pdf(record, papers_dir, timeout=args.timeout)
        analysis_path = create_analysis(record, pdf_path, run_dir, template, args.overwrite_analysis)
        analysis_paths.append(analysis_path)
        analysis_items.append({"record": record, "pdf_path": pdf_path, "analysis_path": analysis_path})

    analysis_task_path = write_analysis_task(
        root,
        run_dir,
        arxiv_date,
        selection_path,
        selection_record_path,
        analysis_items,
    )
    reading_paths = write_reading_dashboard(root, run_dir, arxiv_date, analysis_items)

    print(f"Run dir: {run_dir}")
    print(f"Selection: {selection_path}")
    print(f"Preference records updated: {root / 'data' / 'paper_preference_records.jsonl'}")
    print(f"Selection record: {selection_record_path}")
    print(f"Downloaded/checked PDFs: {len(selected_records)} in {papers_dir}")
    print(f"Analysis files: {len(analysis_paths)}")
    print(f"LLM analysis task: {analysis_task_path}")
    print(f"Reading dashboard: {reading_paths['dashboard']}")
    print(f"Reading manifest: {reading_paths['manifest']}")
    print(f"Reading status: {reading_paths['status']}")
    for path in analysis_paths:
        print(f"- {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
