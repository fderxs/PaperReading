#!/usr/bin/env python3
"""Prepare a Codex-in-the-loop paper filtering task without calling an LLM API."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from render_selector import (
    ROOT_DIR,
    arxiv_id_from_pdf_url,
    classify_paper,
    fetch_arxiv_metadata,
    load_institutions_cache,
    load_summary_zh_cache,
    reason_from_tags,
)


def load_json(path: Path) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def escape_table(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ").strip()


def build_metadata_package(scraped_path: Path, timeout: int, use_arxiv_api: bool) -> Dict[str, object]:
    scraped = load_json(scraped_path)
    raw_papers = list(scraped.get("papers", []))
    arxiv_ids = [
        arxiv_id
        for arxiv_id in (arxiv_id_from_pdf_url(str(paper.get("pdf_url", ""))) for paper in raw_papers)
        if arxiv_id
    ]

    metadata: Dict[str, Dict[str, object]] = {}
    metadata_error = ""
    if use_arxiv_api and arxiv_ids:
        try:
            metadata = fetch_arxiv_metadata(arxiv_ids, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - this task file is still useful with title-only data.
            metadata_error = f"{type(exc).__name__}: {exc}"

    summary_zh_cache = load_summary_zh_cache()
    institutions_cache = load_institutions_cache()

    papers: List[Dict[str, object]] = []
    for index, raw in enumerate(raw_papers, 1):
        arxiv_id = arxiv_id_from_pdf_url(str(raw.get("pdf_url", "")))
        meta = metadata.get(arxiv_id, {})
        title = str(meta.get("title") or raw.get("title") or "").strip()
        summary = str(meta.get("summary") or "").strip()
        classification = classify_paper(title, summary)
        tags = list(classification["tags"])
        papers.append(
            {
                "raw_paper_id": f"R{index:02d}",
                "arxiv_id": arxiv_id,
                "title": title,
                "pdf_url": raw.get("pdf_url", ""),
                "authors": list(meta.get("authors") or []),
                "institutions": institutions_cache.get(arxiv_id, ""),
                "summary": summary,
                "summary_zh": summary_zh_cache.get(arxiv_id, ""),
                "heuristic_score": int(classification["score"]),
                "heuristic_tags": tags,
                "heuristic_reason": reason_from_tags(tags) if tags else "",
            }
        )

    papers.sort(key=lambda item: (-int(item["heuristic_score"]), str(item["title"]).lower()))
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_json": str(scraped_path),
        "run_date": scraped_path.parent.name,
        "arxiv_date": scraped.get("target_date", ""),
        "arxiv_start_date": scraped.get("arxiv_start_date", ""),
        "arxiv_end_date": scraped.get("arxiv_end_date", ""),
        "source_url": scraped.get("source_url", ""),
        "target_date_label": scraped.get("target_date_label", ""),
        "total_paper_count": len(raw_papers),
        "metadata_source": "arxiv_api" if use_arxiv_api else "title_only",
        "metadata_error": metadata_error,
        "papers": papers,
    }


def render_task(package: Dict[str, object], root: Path, metadata_path: Path, shortlist_path: Path) -> str:
    run_dir = metadata_path.parent
    arxiv_date = str(package.get("arxiv_date", ""))
    target_date_label = str(package.get("target_date_label") or arxiv_date)
    source_json = str(package.get("source_json", ""))
    preference_path = root / "data" / "paper_preference_records.jsonl"
    summary_cache = root / "data" / "summary_zh_cache.json"
    institution_cache = root / "data" / "institutions_cache.json"
    selector_path = run_dir / f"vla_planning_selector_{arxiv_date}.html"

    rows = []
    for paper in package.get("papers", []):
        rows.append(
            "| {raw_paper_id} | {heuristic_score} | {tags} | {title} |".format(
                raw_paper_id=escape_table(paper.get("raw_paper_id", "")),
                heuristic_score=escape_table(paper.get("heuristic_score", "")),
                tags=escape_table(", ".join(paper.get("heuristic_tags", []))),
                title=escape_table(paper.get("title", "")),
            )
        )
    table = "\n".join(rows)
    metadata_note = ""
    if package.get("metadata_error"):
        metadata_note = f"\n> 注意：arXiv 元数据拉取失败，只能先基于标题筛选。错误：`{package['metadata_error']}`\n"

    return f"""# LLM-in-the-loop 筛选任务：{target_date_label}

本文件由脚本自动生成，没有调用任何大模型 API。请把这个任务交给当前 Codex/Cursor 对话里的我来完成筛选与 HTML 生成。
{metadata_note}
## 输入文件

- 原始爬取 JSON：`{source_json}`
- arXiv 元数据包：`{metadata_path}`
- 历史偏好记录：`{preference_path}`
- 中文摘要缓存：`{summary_cache}`
- 机构缓存：`{institution_cache}`

## 我需要完成的事

1. 读取元数据包和历史偏好记录，结合你的关注方向进行筛选。
2. 关注范围：VLA、具身规划 Planning、World Model、长时程任务、机器人/具身智能相关综述、数据集、测试基准、评测与可靠性文章。
3. 生成或覆盖最终 shortlist：`{shortlist_path}`。
4. 如果补充了中文摘要或机构信息，同步更新 `data/summary_zh_cache.json` 和 `data/institutions_cache.json`。
5. 运行下面命令渲染选择器 HTML：

```bash
python3 scripts/render_selector.py "{shortlist_path}"
```

6. 完成后告诉用户打开选择器：

```bash
./serve_selector.sh --run-dir "{run_dir}"
```

## shortlist JSON 格式要求

最终 JSON 至少包含这些字段：

```json
{{
  "generated_at": "ISO 时间",
  "source_json": "{source_json}",
  "run_date": "{package.get('run_date', '')}",
  "arxiv_date": "{arxiv_date}",
  "source_url": "{package.get('source_url', '')}",
  "total_paper_count": {package.get('total_paper_count', 0)},
  "shortlist_count": 0,
  "papers": []
}}
```

每篇 `papers` 需要包含：

```json
{{
  "paper_id": "P01",
  "arxiv_id": "2604.xxxxx",
  "title": "论文标题",
  "pdf_url": "https://arxiv.org/pdf/...",
  "authors": ["作者"],
  "institutions": "机构，无法确认时写待补充",
  "summary": "英文摘要",
  "summary_zh": "中文摘要",
  "tags": ["VLA", "Planning"],
  "score": 18,
  "reason": "为什么推荐/保留"
}}
```

## 候选论文速览

| 原始编号 | 启发式分数 | 启发式标签 | 标题 |
|---|---:|---|---|
{table}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a Codex-in-the-loop filtering task.")
    parser.add_argument("scraped_json", type=Path, help="Path to cs_ro_papers_<date>.json")
    parser.add_argument("--root", type=Path, default=ROOT_DIR, help="PaperReading root directory.")
    parser.add_argument("--timeout", type=int, default=60, help="arXiv API timeout in seconds.")
    parser.add_argument("--no-arxiv-api", action="store_true", help="Skip arXiv API metadata fetching.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    scraped_path = args.scraped_json.resolve()
    package = build_metadata_package(scraped_path, timeout=args.timeout, use_arxiv_api=not args.no_arxiv_api)
    arxiv_date = str(package.get("arxiv_date", ""))

    metadata_path = scraped_path.parent / f"all_papers_metadata_{arxiv_date}.json"
    shortlist_path = scraped_path.parent / f"shortlist_vla_planning_{arxiv_date}.json"
    task_path = scraped_path.parent / f"llm_filter_task_{arxiv_date}.md"

    metadata_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    task_path.write_text(render_task(package, root, metadata_path, shortlist_path), encoding="utf-8")

    print(f"Wrote metadata package: {metadata_path}")
    print(f"Wrote LLM filter task: {task_path}")
    if package.get("metadata_error"):
        print(f"Warning: metadata fetch failed: {package['metadata_error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
