#!/usr/bin/env python3
"""Prepare a Codex-in-the-loop paper filtering task without calling an LLM API."""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
SUMMARY_ZH_CACHE = DATA_DIR / "summary_zh_cache.json"
INSTITUTIONS_CACHE = DATA_DIR / "institutions_cache.json"
USER_AGENT = "paperreading-dashboard/1.0 (+https://arxiv.org/list/cs.RO/recent)"
ARXIV_API = "https://export.arxiv.org/api/query"
VLA_RE = re.compile(r"\b(VLA|vision[-\s]?language[-\s]?action)\b", re.I)
PLANNING_RE = re.compile(
    r"\b(planning|planner|motion planning|world model|model[-\s]?predictive|"
    r"trajectory|long[-\s]?horizon|action synthesis|temporal logic)\b",
    re.I,
)
BENCHMARK_RE = re.compile(r"\b(dataset|benchmark|bench|evaluation|test)\b", re.I)
SAFETY_RE = re.compile(r"\b(calibration|uncertainty|failure|safe|safety|robust)\b", re.I)
EMBODIED_RE = re.compile(
    r"\b(embodied|manipulation|robotic autonomy|foundation model|cross[-\s]?embodiment)\b",
    re.I,
)


def arxiv_id_from_pdf_url(pdf_url: str) -> str:
    match = re.search(r"/pdf/([^/?#]+)", pdf_url)
    if not match:
        return ""
    return match.group(1).removesuffix(".pdf")


def chunked(values: List[str], size: int) -> List[List[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def fetch_arxiv_metadata(arxiv_ids: List[str], timeout: int) -> Dict[str, Dict[str, object]]:
    metadata: Dict[str, Dict[str, object]] = {}
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    for batch in chunked(arxiv_ids, 50):
        url = f"{ARXIV_API}?{urlencode({'id_list': ','.join(batch), 'max_results': len(batch)})}"
        request = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=timeout) as response:
            root = ET.fromstring(response.read())

        for entry in root.findall("atom:entry", ns):
            raw_id = entry.findtext("atom:id", default="", namespaces=ns).rsplit("/", 1)[-1]
            arxiv_id = re.sub(r"v\d+$", "", raw_id)
            title = " ".join(entry.findtext("atom:title", default="", namespaces=ns).split())
            summary = " ".join(entry.findtext("atom:summary", default="", namespaces=ns).split())
            authors = [
                author.findtext("atom:name", default="", namespaces=ns)
                for author in entry.findall("atom:author", ns)
            ]
            metadata[arxiv_id] = {"title": title, "summary": summary, "authors": authors}

    return metadata


def load_summary_zh_cache() -> Dict[str, str]:
    if not SUMMARY_ZH_CACHE.exists():
        return {}
    return json.loads(SUMMARY_ZH_CACHE.read_text(encoding="utf-8"))


def load_institutions_cache() -> Dict[str, str]:
    if not INSTITUTIONS_CACHE.exists():
        return {}
    return json.loads(INSTITUTIONS_CACHE.read_text(encoding="utf-8"))


def classify_paper(title: str, summary: str) -> Dict[str, object]:
    text = f"{title}\n{summary}"
    score = 0
    tags: List[str] = []

    if VLA_RE.search(text):
        score += 10
        tags.append("VLA")
    if PLANNING_RE.search(text):
        score += 8
        tags.append("Planning")
    if "world model" in text.lower():
        score += 4
        tags.append("World Model")
    if EMBODIED_RE.search(text):
        score += 4
        tags.append("具身/机器人")
    if SAFETY_RE.search(text):
        score += 3
        tags.append("可靠性/安全")
    if BENCHMARK_RE.search(text):
        score += 2
        tags.append("数据集/基准")

    return {"score": score, "tags": list(dict.fromkeys(tags))}


def reason_from_tags(tags: List[str]) -> str:
    if "VLA" in tags and "Planning" in tags:
        return "同时涉及 VLA 与规划/长时程决策，是高优先级候选。"
    if "VLA" in tags:
        return "直接涉及 VLA 或视觉-语言-动作模型，符合当前筛选主线。"
    if "Planning" in tags or "World Model" in tags:
        return "直接涉及具身规划、运动规划或 world model，符合当前筛选主线。"
    if "数据集/基准" in tags:
        return "包含数据集、基准或评测信息，可作为 VLA/规划方向参考。"
    return "关键词相关，建议快速浏览后决定是否深入。"


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
    dashboard_path = root / "dashboard" / "reading_dashboard.html"

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

本文件由脚本自动生成，没有调用任何大模型 API。请把这个任务交给当前 Codex/Cursor 对话里的我来完成筛选，并生成唯一入口 reading dashboard。
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
5. 运行下面命令渲染 reading dashboard：

```bash
python3 scripts/render_reading_dashboard.py --shortlist "{shortlist_path}"
```

6. 完成后告诉用户打开 reading dashboard：

```bash
./start_dashboard.sh --run-dir "{run_dir}"
```

预期 HTML：`{dashboard_path}`。

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
