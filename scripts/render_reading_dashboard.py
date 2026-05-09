#!/usr/bin/env python3
"""Render an interactive reading dashboard for selected papers."""

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


TAG_LIMIT = 3
TAG_POOL = (
    "VLA",
    "规划/长时程",
    "世界模型",
    "数据集/基准",
    "评测",
    "可靠性/安全",
    "机器人操作",
    "导航/移动机器人",
    "触觉/多模态",
    "人类示范/意图",
    "跨本体泛化",
    "VLM/语言引导",
    "强化学习",
    "后训练",
    "部署",
    "综述",
    "医疗机器人",
    "工业部署",
)
TAG_ORDER = {tag: index for index, tag in enumerate(TAG_POOL)}
GLOBAL_DASHBOARD_DIR = "dashboard"
GLOBAL_DASHBOARD_NAME = "reading_dashboard.html"


TAG_ALIASES = [
    ("VLA", ("vla", "vision-language-action", "vision language action", "视觉--语言--动作", "视觉-语言-动作")),
    ("规划/长时程", ("planning", "planner", "long-horizon", "long horizon", "trajectory", "motion planning", "sequential task", "规划", "长时程")),
    ("世界模型", ("world model", "世界模型")),
    ("数据集/基准", ("dataset", "benchmark", "bench", "libero", "数据集", "基准")),
    ("数据引擎", ("data engine", "数据引擎")),
    ("综述", ("survey", "综述")),
    ("可靠性/安全", ("reliability", "safety", "safe", "robust", "uncertainty", "failure", "red teaming", "physical safety", "安全架构", "可靠", "安全", "鲁棒")),
    ("评测", ("evaluation", "evaluate", "policy evaluation", "评测", "评价")),
    ("部署", ("deployment", "deploy", "edge deployment", "部署")),
    ("具身/机器人", ("embodied", "robot", "robotic", "具身", "机器人")),
    ("机器人操作", ("manipulation", "bimanual", "dexterous", "grasp", "操作", "抓取", "双臂")),
    ("触觉/多模态", ("tactile", "vision-tactile", "multimodal", "触觉", "视觉-触觉", "多模态")),
    ("人类示范/意图", ("human demonstration", "human demonstrations", "human intention", "gaze", "人类示范", "人类意图", "意图", "凝视")),
    ("人机交互", ("human-in-the-loop", "human-robot interaction", "hri", "人机交互")),
    ("跨本体泛化", ("cross-embodiment", "cross embodiment", "embodiment", "跨本体", "跨具身")),
    ("泛化", ("generalization", "generalizable", "泛化")),
    ("后训练", ("post-training", "post training", "fine-tuning", "finetuning", "后训练", "微调")),
    ("强化学习", ("reinforcement", "rl", "强化学习")),
    ("策略/动作表示", ("action head", "action representation", "generative policy", "diffusion", "behavior phasing", "policy", "动作表示", "策略")),
    ("技能学习", ("skill learning", "meta-skill", "技能")),
    ("导航/移动机器人", ("navigation", "off-road", "mobile robot", "active visual tracking", "导航", "移动机器人")),
    ("VLM/语言引导", ("vlm", "llm agent", "language-guided", "code-as-planner", "语言引导")),
    ("形式化/可解释", ("formal methods", "interpretability", "interpretable", "conformal", "形式化", "可解释")),
    ("空间/语义表示", ("semantic graph", "spatial constraints", "空间", "语义图")),
    ("模型架构", ("model architecture", "architecture", "模型架构")),
    ("低数据", ("low-data", "low data", "低数据")),
    ("校准", ("calibration", "校准")),
    ("自动驾驶", ("autonomous driving", "自动驾驶")),
    ("医疗机器人", ("medical", "surgery", "surgical", "医疗")),
    ("工业部署", ("industrial", "industry", "工业")),
]


def matching_tags(value: str) -> List[str]:
    text = value.strip()
    if not text:
        return []
    lowered = text.lower()
    matches = []
    for canonical, aliases in TAG_ALIASES:
        if canonical not in TAG_ORDER:
            continue
        if text == canonical or any(alias in lowered for alias in aliases):
            matches.append(canonical)
    if text in TAG_ORDER:
        matches.append(text)
    return matches


def split_tags(values: Iterable[object]) -> List[str]:
    tags: List[str] = []
    for value in values:
        if isinstance(value, list):
            tags.extend(split_tags(value))
            continue
        text = str(value or "").strip()
        if not text:
            continue
        parts = re.split(r"\s*/\s*|[,，;；|]+", text)
        tags.extend(part.strip() for part in parts if part.strip())
    return tags


def normalize_tags(values: Iterable[object]) -> List[str]:
    seen = set()
    tags = []
    for raw in split_tags(values):
        for tag in matching_tags(raw):
            if tag in seen:
                continue
            seen.add(tag)
            tags.append(tag)
    tags.sort(key=lambda tag: TAG_ORDER[tag])
    return tags[:TAG_LIMIT]


def extract_analysis_tags(path: Path) -> List[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"^\|\s*方向\s*\|\s*([^|\n]+)\|", text, flags=re.MULTILINE)
    if not match:
        return []
    return normalize_tags([match.group(1)])


def relpath(path: Path, start: Path) -> str:
    return os.path.relpath(path, start).replace(os.sep, "/")


def reading_id(index: int) -> str:
    return f"R{index:02d}"


def find_cn_pdf(run_dir: Path, read_id: str, arxiv_id: str) -> str:
    paper_cn_dir = run_dir / "paper_cn"
    candidates = [
        paper_cn_dir / f"{read_id}_{arxiv_id}" / "paper_cn.pdf",
        paper_cn_dir / f"{read_id}_{arxiv_id}" / "translated.pdf",
        paper_cn_dir / f"{read_id}_{arxiv_id}" / f"{arxiv_id}_cn.pdf",
        paper_cn_dir / arxiv_id / "paper_cn.pdf",
        paper_cn_dir / arxiv_id / f"{arxiv_id}_cn.pdf",
    ]
    for candidate in candidates:
        if candidate.exists():
            return relpath(candidate.resolve(), run_dir.resolve())
    return ""


def url_for_run_file(run_date: str, relative_path: str) -> str:
    return f"/runs/{run_date}/{relative_path.lstrip('/')}"


def global_dashboard_path(root: Path) -> Path:
    return root / GLOBAL_DASHBOARD_DIR / GLOBAL_DASHBOARD_NAME


def write_global_dashboard(root: Path, manifest: Dict[str, object]) -> Path:
    dashboard_path = global_dashboard_path(root)
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    dashboard_path.write_text(render_html(manifest, root), encoding="utf-8")
    return dashboard_path


def load_json(path: Path) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def status_map(run_dir: Path, arxiv_date: str) -> Dict[str, Dict[str, object]]:
    status_path = run_dir / f"reading_status_{arxiv_date}.json"
    if not status_path.exists():
        return {}
    try:
        payload = load_json(status_path)
    except json.JSONDecodeError:
        return {}
    result: Dict[str, Dict[str, object]] = {}
    for item in payload.get("read_papers", []):
        if isinstance(item, dict) and item.get("reading_id"):
            result[str(item["reading_id"])] = item
    return result


def selected_map(run_dir: Path, arxiv_date: str) -> Dict[str, Dict[str, object]]:
    selected_path = run_dir / f"selected_vla_planning_papers_{arxiv_date}.json"
    if not selected_path.exists():
        return {}
    try:
        payload = load_json(selected_path)
    except json.JSONDecodeError:
        return {}
    result: Dict[str, Dict[str, object]] = {}
    for item in payload.get("selected_papers", []):
        if isinstance(item, dict):
            key = str(item.get("arxiv_id") or item.get("paper_id") or item.get("title") or "")
            if key:
                result[key] = item
    return result


def archive_key(run_date: str, arxiv_date: str) -> str:
    return f"{run_date}::{arxiv_date}"


def archive_sort_key(entry: Dict[str, object]) -> Tuple[str, str]:
    return (str(entry.get("run_date", "")), str(entry.get("arxiv_date", "")))


def normalize_manifest_paper(run_dir: Path, paper: Dict[str, object], entry_key: str) -> Dict[str, object]:
    run_date = run_dir.name
    analysis_path = str(paper.get("analysis_path") or "")
    pdf_file = str(paper.get("pdf_file") or Path(str(paper.get("pdf_path") or "")).name)
    cn_pdf_path = str(paper.get("cn_pdf_path") or find_cn_pdf(run_dir, str(paper.get("reading_id", "")), str(paper.get("arxiv_id", ""))))
    analysis_tags = extract_analysis_tags(run_dir / analysis_path) if analysis_path else []
    topics = normalize_tags(
        [
            paper.get("tags", []),
            analysis_tags,
            paper.get("title", ""),
            paper.get("notes", ""),
        ]
    )
    result = dict(paper)
    result.update(
        {
            "entry_key": entry_key,
            "run_date": run_date,
            "topics": topics,
            "pdf_path": f"/papers/{pdf_file}" if pdf_file else str(paper.get("pdf_path") or ""),
            "analysis_path": url_for_run_file(run_date, analysis_path) if analysis_path else "",
            "cn_pdf_path": url_for_run_file(run_date, cn_pdf_path) if cn_pdf_path else "",
            "cn_pdf_raw_path": cn_pdf_path,
        }
    )
    return result


def normalize_candidate(run_dir: Path, paper: Dict[str, object], entry_key: str, selected: Dict[str, Dict[str, object]]) -> Dict[str, object]:
    key = str(paper.get("arxiv_id") or paper.get("paper_id") or paper.get("title") or "")
    selected_item = selected.get(key, {})
    result = dict(paper)
    result.update(
        {
            "entry_key": entry_key,
            "run_date": run_dir.name,
            "topics": normalize_tags(
                [
                    paper.get("tags", []),
                    paper.get("title", ""),
                    paper.get("reason", ""),
                    paper.get("summary", ""),
                    paper.get("summary_zh", ""),
                ]
            ),
            "priority": str(selected_item.get("priority") or ""),
            "notes": str(selected_item.get("notes") or ""),
        }
    )
    return result


def build_archive(root: Path, active_manifest: Dict[str, object]) -> Dict[str, object]:
    entries: Dict[str, Dict[str, object]] = {}
    runs_dir = root / "runs"
    if not runs_dir.exists():
        return {"active_key": "", "entries": [], "tags": []}

    for manifest_path in sorted(runs_dir.glob("*/reading_manifest_*.json")):
        run_dir = manifest_path.parent
        try:
            manifest = load_json(manifest_path)
        except json.JSONDecodeError:
            continue
        arxiv_date = str(manifest.get("arxiv_date") or manifest_path.name.removeprefix("reading_manifest_").removesuffix(".json"))
        key = archive_key(run_dir.name, arxiv_date)
        entry = entries.setdefault(
            key,
            {
                "key": key,
                "run_date": run_dir.name,
                "arxiv_date": arxiv_date,
                "year": run_dir.name[:4],
                "month": run_dir.name[:7],
                "papers": [],
                "candidates": [],
                "status": status_map(run_dir, arxiv_date),
            },
        )
        entry["papers"] = [
            normalize_manifest_paper(run_dir, paper, key)
            for paper in manifest.get("papers", [])
            if isinstance(paper, dict)
        ]

    for shortlist_path in sorted(runs_dir.glob("*/shortlist_vla_planning_*.json")):
        run_dir = shortlist_path.parent
        try:
            shortlist = load_json(shortlist_path)
        except json.JSONDecodeError:
            continue
        arxiv_date = str(shortlist.get("arxiv_date") or shortlist_path.name.removeprefix("shortlist_vla_planning_").removesuffix(".json"))
        key = archive_key(run_dir.name, arxiv_date)
        selected = selected_map(run_dir, arxiv_date)
        entry = entries.setdefault(
            key,
            {
                "key": key,
                "run_date": run_dir.name,
                "arxiv_date": arxiv_date,
                "year": run_dir.name[:4],
                "month": run_dir.name[:7],
                "papers": [],
                "candidates": [],
                "status": status_map(run_dir, arxiv_date),
            },
        )
        entry["candidates"] = [
            normalize_candidate(run_dir, paper, key, selected)
            for paper in shortlist.get("papers", [])
            if isinstance(paper, dict)
        ]

    active_key = archive_key(str(active_manifest.get("run_date") or ""), str(active_manifest.get("arxiv_date") or ""))
    tags = sorted(
        {
            tag
            for entry in entries.values()
            for paper in list(entry.get("papers", [])) + list(entry.get("candidates", []))
            for tag in paper.get("topics", [])
            if tag in TAG_ORDER
        },
        key=lambda tag: TAG_ORDER[tag],
    )
    return {
        "active_key": active_key,
        "entries": sorted(entries.values(), key=archive_sort_key, reverse=True),
        "tags": tags,
    }


def build_manifest(
    root: Path,
    run_dir: Path,
    arxiv_date: str,
    analysis_items: List[Dict[str, object]],
) -> Dict[str, object]:
    papers = []
    for index, item in enumerate(analysis_items, 1):
        record = item["record"]
        pdf_path = Path(str(item["pdf_path"])).resolve()
        analysis_path = Path(str(item["analysis_path"])).resolve()
        read_id = reading_id(index)
        arxiv_id = str(record.get("arxiv_id", ""))
        papers.append(
            {
                "reading_id": read_id,
                "selector_id": str(record.get("paper_id", "")),
                "arxiv_id": arxiv_id,
                "title": str(record.get("title", "")),
                "priority": str(record.get("priority", "")),
                "notes": str(record.get("notes", "")),
                "tags": list(record.get("tags", [])),
                "pdf_path": relpath(pdf_path, run_dir),
                "analysis_path": relpath(analysis_path, run_dir),
                "cn_pdf_path": find_cn_pdf(run_dir, read_id, arxiv_id),
                "pdf_file": pdf_path.name,
                "analysis_file": analysis_path.name,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_date": run_dir.name,
        "arxiv_date": arxiv_date,
        "root": relpath(root.resolve(), run_dir.resolve()),
        "paper_count": len(papers),
        "papers": papers,
    }


def render_html(manifest: Dict[str, object], root: Path | None = None) -> str:
    root = root or Path.cwd().resolve()
    archive = build_archive(root, manifest)
    active_key = archive_key(str(manifest.get("run_date") or ""), str(manifest.get("arxiv_date") or ""))
    active_entry = next((entry for entry in archive.get("entries", []) if entry.get("key") == active_key), None)
    display_manifest = dict(manifest)
    if active_entry:
        display_manifest["papers"] = active_entry.get("papers", manifest.get("papers", []))
    manifest_json = json.dumps(display_manifest, ensure_ascii=False, indent=2)
    archive_json = json.dumps(archive, ensure_ascii=False, indent=2)
    title = "PaperReading Dashboard"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      --ink: #1f2528;
      --muted: #687277;
      --line: #d8dedb;
      --bg: #f6f7f3;
      --panel: #ffffff;
      --accent: #226b5f;
      --accent-soft: #e0f0ec;
      --warn: #8a5b12;
      --shadow: 0 14px 36px rgba(31, 37, 40, 0.10);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: var(--bg);
      font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.5;
    }}
    header {{
      height: 68px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
      padding: 0 20px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.94);
      position: sticky;
      top: 0;
      z-index: 5;
    }}
    h1 {{ font-size: 1.12rem; margin: 0; }}
    .summary {{ color: var(--muted); font-size: 0.92rem; }}
    .hidden {{ display: none !important; }}
    .app-shell {{
      display: grid;
      grid-template-columns: 250px minmax(0, 1fr);
      min-height: calc(100vh - 68px);
    }}
    .app-shell.reader-active {{
      grid-template-columns: minmax(0, 1fr);
    }}
    .app-shell.reader-active .archive-nav {{
      display: none;
    }}
    .archive-nav {{
      border-right: 1px solid var(--line);
      background: #fbfcfa;
      padding: 14px;
      overflow: auto;
      position: sticky;
      top: 68px;
      height: calc(100vh - 68px);
    }}
    .archive-nav h2 {{
      font-size: 0.92rem;
      margin: 8px 0 10px;
    }}
    .archive-group {{
      margin-bottom: 12px;
    }}
    .archive-button {{
      width: 100%;
      border: 0;
      background: transparent;
      color: var(--ink);
      cursor: pointer;
      text-align: left;
      border-radius: 6px;
      padding: 5px 7px;
      font: inherit;
    }}
    .archive-button:hover, .archive-button.active {{
      background: var(--accent-soft);
      color: var(--accent);
    }}
    .archive-month {{ padding-left: 13px; font-size: 0.9rem; }}
    .archive-date {{ padding-left: 26px; font-size: 0.86rem; color: var(--muted); }}
    .workspace {{
      min-width: 0;
    }}
    .list-view {{
      min-height: calc(100vh - 68px);
      padding: 18px;
      max-width: 1180px;
      margin: 0 auto;
      width: 100%;
    }}
    .filters {{
      display: grid;
      grid-template-columns: 1fr 120px 170px auto;
      gap: 8px;
      position: sticky;
      top: 68px;
      z-index: 4;
      margin: -18px -18px 14px;
      padding: 14px 18px;
      border-bottom: 1px solid rgba(216, 222, 219, 0.86);
      background: rgba(246, 247, 243, 0.94);
      backdrop-filter: blur(10px);
    }}
    .mode-toggle {{
      display: inline-flex;
      border: 1px solid var(--line);
      border-radius: 7px;
      overflow: hidden;
      background: white;
      min-height: 34px;
    }}
    .mode-toggle button {{
      border: 0;
      border-right: 1px solid var(--line);
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      padding: 4px 10px;
      font: inherit;
      white-space: nowrap;
    }}
    .mode-toggle button:last-child {{ border-right: 0; }}
    .mode-toggle button.active {{
      background: var(--accent);
      color: white;
    }}
    .selection-actions {{
      display: none;
      align-items: center;
      gap: 8px;
      position: sticky;
      top: 123px;
      z-index: 3;
      margin: -14px -18px 14px;
      padding: 8px 18px 10px;
      border-bottom: 1px solid rgba(216, 222, 219, 0.78);
      background: rgba(246, 247, 243, 0.94);
      backdrop-filter: blur(10px);
      color: var(--muted);
      font-size: 0.9rem;
    }}
    .selection-actions.visible {{ display: flex; }}
    .selection-actions button {{
      min-height: 32px;
      border: 1px solid var(--accent);
      border-radius: 6px;
      background: var(--accent);
      color: white;
      cursor: pointer;
      padding: 4px 10px;
      font: inherit;
    }}
    input[type="search"], select {{
      width: 100%;
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 9px;
      background: white;
      color: var(--ink);
    }}
    #paperList {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
      grid-auto-rows: 176px;
      gap: 12px;
    }}
    .paper-row {{
      display: grid;
      grid-template-columns: 1fr;
      height: 176px;
      padding: 13px;
      border: 1px solid #f0c4bd;
      border-radius: 8px;
      background: #fff2ef;
      cursor: pointer;
      box-shadow: 0 1px 0 rgba(31, 37, 40, 0.03);
      overflow: hidden;
    }}
    .paper-row:hover, .paper-row.active {{
      border-color: #d57f72;
      background: #ffe9e4;
    }}
    .paper-row.read {{
      border-color: #a8d4bf;
      background: #eef8f1;
    }}
    .paper-row.read:hover, .paper-row.read.active {{
      border-color: #72b28f;
      background: #e2f2e8;
    }}
    .paper-row.read .row-title {{ color: #4f675b; }}
    .paper-row.intensive {{
      border-color: #4d9a72;
      background: #dff0e6;
      color: var(--ink);
      box-shadow: 0 8px 22px rgba(45, 107, 78, 0.13);
    }}
    .paper-row.intensive:hover, .paper-row.intensive.active {{
      border-color: #2f7f5d;
      background: #d2eadc;
    }}
    .paper-row.intensive .row-id,
    .paper-row.intensive .row-title,
    .paper-row.intensive .row-meta {{ color: var(--ink); }}
    .paper-row.candidate {{
      cursor: default;
      background: #fffdf5;
      border-color: #ded7bf;
    }}
    .paper-row.candidate.selected {{
      background: #fff3df;
      border-color: #c98244;
    }}
    .row-body {{
      min-height: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      height: 100%;
    }}
    .row-id {{ font-weight: 800; color: var(--accent); font-size: 0.86rem; }}
    .row-title {{
      margin: 5px 0 8px;
      font-weight: 650;
      font-size: 0.94rem;
      line-height: 1.35;
      min-height: 0;
      display: -webkit-box;
      -webkit-line-clamp: 4;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}
    .row-meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      color: var(--muted);
      font-size: 0.78rem;
      align-items: flex-end;
      max-height: 50px;
      overflow: hidden;
    }}
    .candidate-controls {{
      display: grid;
      grid-template-columns: 116px 1fr;
      gap: 6px;
      margin-top: auto;
    }}
    .candidate-controls textarea {{
      min-height: 32px;
      max-height: 54px;
      resize: vertical;
      border: 1px solid var(--line);
      border-radius: 6px;
      font: inherit;
      padding: 5px 7px;
    }}
    #paperList.selection-list {{
      display: block;
    }}
    #paperList.selection-list .paper-row.candidate {{
      display: grid;
      grid-template-columns: 82px minmax(0, 1fr);
      gap: 16px;
      height: auto;
      min-height: 0;
      margin-bottom: 14px;
      padding: 18px;
      overflow: visible;
      background: #fffdf8;
      border-color: #d7cfbd;
    }}
    #paperList.selection-list .paper-row.candidate.selected {{
      background: #fff4df;
      border-color: #c98244;
    }}
    .candidate-status {{
      align-self: start;
      text-align: center;
      border-radius: 7px;
      padding: 8px 6px;
      background: #eee8d8;
      color: #667064;
      font-weight: 800;
      font-size: 0.78rem;
    }}
    .paper-row.candidate.selected .candidate-status {{
      background: var(--accent);
      color: white;
    }}
    #paperList.selection-list .row-body {{
      display: block;
      height: auto;
    }}
    #paperList.selection-list .row-title {{
      display: block;
      overflow: visible;
      margin: 0 0 8px;
      font-size: 1.05rem;
      line-height: 1.35;
    }}
    .candidate-info {{
      display: grid;
      gap: 6px;
      margin: 10px 0 12px;
      color: var(--muted);
      font-size: 0.9rem;
    }}
    .candidate-info p {{
      margin: 0;
    }}
    .candidate-info strong {{
      color: var(--ink);
    }}
    .candidate-summary {{
      color: #48524d;
      background: #f5f3ea;
      border: 1px solid #e3ddcf;
      border-radius: 7px;
      padding: 9px 10px;
      line-height: 1.55;
    }}
    #paperList.selection-list .candidate-controls {{
      margin-top: 12px;
      grid-template-columns: 150px 1fr;
    }}
    #paperList.selection-list .candidate-controls textarea {{
      min-height: 42px;
      max-height: 110px;
    }}
    .pill {{
      display: inline-flex;
      align-items: center;
      min-height: 21px;
      padding: 1px 7px;
      border-radius: 999px;
      background: #eef2ef;
      color: #435049;
    }}
    .pill.priority-a {{ background: #ffe7cc; color: #7a420b; }}
    .pill.priority-b {{ background: #e4edf9; color: #285078; }}
    .pill.priority-c {{ background: #eeeeee; color: #555; }}
    .reader-view {{
      min-height: calc(100vh - 68px);
    }}
    .reader-top {{
      height: 48px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      padding: 0 14px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfa;
    }}
    .toolbar-left, .toolbar-right {{
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }}
    .toolbar-left {{
      flex: 1 1 auto;
    }}
    .toolbar-right {{
      flex: 0 0 auto;
      margin-left: auto;
    }}
    .toolbar-button {{
      min-height: 32px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: white;
      color: var(--ink);
      cursor: pointer;
      padding: 4px 10px;
      font: inherit;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      white-space: nowrap;
    }}
    .toolbar-button.primary {{
      border-color: var(--accent);
      background: var(--accent);
      color: white;
    }}
    .toolbar-button.read {{
      border-color: #8aa79e;
      background: var(--accent-soft);
      color: var(--accent);
    }}
    .toolbar-button.intensive {{
      border-color: #124c36;
      background: #124c36;
      color: white;
    }}
    .view-toggle {{
      display: inline-flex;
      border: 1px solid var(--line);
      border-radius: 7px;
      overflow: hidden;
      background: white;
    }}
    .view-toggle button {{
      min-height: 32px;
      border: 0;
      border-right: 1px solid var(--line);
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      padding: 4px 10px;
      font: inherit;
    }}
    .view-toggle button:last-child {{ border-right: 0; }}
    .view-toggle button.active {{
      background: var(--accent);
      color: white;
    }}
    .reader-grid {{
      display: grid;
      grid-template-columns: minmax(360px, 48%) minmax(360px, 52%);
      min-width: 0;
    }}
    .reader-pane, .pdf-pane {{
      min-width: 0;
      height: calc(100vh - 116px);
      overflow: hidden;
      background: var(--panel);
    }}
    .current-id {{ color: var(--accent); font-weight: 800; }}
    .read-state {{ background: #f1f3f1; color: #56625d; }}
    .read-state.done {{ background: var(--accent-soft); color: var(--accent); }}
    .intensive-state {{ background: #124c36; color: white; }}
    #analysis {{
      height: 100%;
      overflow: auto;
      padding: 22px 28px 60px;
      font-size: 0.96rem;
    }}
    #analysis h1, #analysis h2, #analysis h3 {{ line-height: 1.25; }}
    #analysis h1 {{ font-size: 1.55rem; margin: 0 0 18px; }}
    #analysis h2 {{ font-size: 1.18rem; margin-top: 26px; }}
    #analysis h3 {{ font-size: 1rem; margin-top: 20px; }}
    #analysis pre {{
      overflow: auto;
      padding: 12px;
      background: #f0f2ef;
      border-radius: 6px;
    }}
    #analysis table {{ width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 0.88rem; }}
    #analysis th, #analysis td {{ border: 1px solid var(--line); padding: 7px; vertical-align: top; }}
    #analysis th {{ background: #f1f5f2; text-align: left; }}
    #analysis img {{ max-width: 100%; border: 1px solid var(--line); box-shadow: var(--shadow); }}
    iframe {{
      width: 100%;
      height: 100%;
      border: 0;
      background: #e8ece9;
    }}
    #cnPdfFrame {{ background: #f1f5f2; }}
    .cn-annotator {{
      height: 100%;
      display: flex;
      flex-direction: column;
      min-width: 0;
      background: #eef2ef;
    }}
    .note-toolbar {{
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 8px 10px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfa;
      flex-wrap: wrap;
    }}
    .note-toolbar button {{
      min-height: 30px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: white;
      color: var(--ink);
      cursor: pointer;
      padding: 4px 9px;
      font: inherit;
      white-space: nowrap;
    }}
    .note-toolbar button.active {{
      border-color: var(--accent);
      background: var(--accent);
      color: white;
    }}
    .note-toolbar button.save {{
      border-color: #124c36;
      background: #124c36;
      color: white;
    }}
    .note-status {{
      color: var(--muted);
      font-size: 0.82rem;
      min-width: 120px;
    }}
    .cn-pages {{
      flex: 1 1 auto;
      overflow: auto;
      padding: 14px;
    }}
    .cn-page {{
      position: relative;
      margin: 0 auto 18px;
      background: white;
      box-shadow: 0 10px 28px rgba(31, 37, 40, 0.16);
      line-height: 0;
    }}
    .cn-page canvas {{
      display: block;
    }}
    .cn-page img {{
      display: block;
      width: 100%;
      height: 100%;
    }}
    .cn-annotation-layer {{
      position: absolute;
      inset: 0;
      cursor: crosshair;
    }}
    .empty {{
      padding: 30px;
      color: var(--muted);
    }}
    @media (max-width: 1040px) {{
      .app-shell {{ grid-template-columns: 1fr; }}
      .archive-nav {{ position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--line); }}
      .filters {{ grid-template-columns: 1fr; }}
      #paperList {{ grid-template-columns: 1fr; }}
      #paperList.selection-list .paper-row.candidate {{ grid-template-columns: 1fr; }}
      .reader-grid {{ grid-template-columns: 1fr; }}
      .reader-pane, .pdf-pane {{ height: 70vh; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>{title}</h1>
      <div class="summary"><span id="progress">0/0</span> 已读；点击列表项进入阅读界面，提问时可引用阅读 ID。</div>
    </div>
    <div class="summary">状态会保存到浏览器；通过本地 server 打开时也会写入 JSON。</div>
  </header>
  <div class="app-shell">
  <aside class="archive-nav" aria-label="历史归档">
    <h2>历史归档</h2>
    <div id="archiveTree"></div>
  </aside>
  <div class="workspace">
  <div id="listView" class="list-view">
      <div class="filters">
        <input id="query" type="search" placeholder="搜索标题 / ID / arXiv">
        <select id="priority">
          <option value="">全部级别</option>
          <option value="A">A</option>
          <option value="B">B</option>
          <option value="C">C</option>
        </select>
        <select id="tagFilter">
          <option value="">全部标签</option>
        </select>
        <div class="mode-toggle" aria-label="列表模式">
          <button id="readingMode" class="active" type="button">阅读列表</button>
          <button id="selectionMode" type="button">论文挑选</button>
        </div>
      </div>
      <div id="selectionActions" class="selection-actions">
        <button id="saveSelection" type="button">保存选择</button>
        <span id="selectionNotice"></span>
      </div>
      <div id="paperList"></div>
  </div>
  <main id="readerView" class="reader-view hidden">
    <div class="reader-top">
      <div class="toolbar-left">
        <button id="backToList" class="toolbar-button" type="button">返回列表</button>
        <span class="current-id" id="readerId">--</span>
        <div class="view-toggle" aria-label="左侧面板">
          <button id="analysisMode" class="active" type="button">分析</button>
          <button id="cnPdfMode" type="button">中文PDF</button>
        </div>
      </div>
      <div class="toolbar-right">
        <button id="readToggle" class="toolbar-button primary" type="button">标记已读</button>
        <button id="intensiveToggle" class="toolbar-button" type="button">精读</button>
        <a id="sourceLink" class="toolbar-button" href="#" target="_blank" rel="noopener">打开源文件</a>
      </div>
    </div>
    <div class="reader-grid">
      <section class="reader-pane">
        <article id="analysis"><div class="empty">从列表选择一篇论文开始阅读。</div></article>
        <iframe id="cnPdfFrame" class="hidden" title="中文 PDF"></iframe>
        <div id="cnAnnotator" class="cn-annotator hidden">
          <div class="note-toolbar">
            <button id="noteTool" class="active" type="button">文字便签</button>
            <button id="highlightTool" type="button">高亮框</button>
            <button id="saveCnPdf" class="save" type="button">保存到PDF</button>
            <button id="clearCnNotes" type="button">清空未保存</button>
            <span id="cnNoteStatus" class="note-status"></span>
          </div>
          <div id="cnPages" class="cn-pages"></div>
        </div>
        <div id="cnEmpty" class="empty hidden"></div>
      </section>
      <section class="pdf-pane">
        <iframe id="pdfFrame" title="PDF"></iframe>
      </section>
    </div>
  </main>
  </div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/pdf-lib@1.17.1/dist/pdf-lib.min.js"></script>
  <script>
    const manifest = {manifest_json};
    const archive = {archive_json};
    const entries = archive.entries || [];
    let activeScope = {{ type: "date", key: archive.active_key || (entries[0] && entries[0].key) || "" }};
    let listMode = "reading";
    let statusByEntry = Object.fromEntries(entries.map((entry) => [entry.key, loadStatus(entry)]));
    let selectionByEntry = Object.fromEntries(entries.map((entry) => [entry.key, loadSelectionState(entry)]));
    let current = null;
    let leftMode = "analysis";
    let cnState = {{
      paperKey: "",
      pdfBytes: null,
      pdfDocument: null,
      annotations: [],
      pages: [],
      tool: "note",
      drawing: null
    }};

    const listView = document.querySelector("#listView");
    const readerView = document.querySelector("#readerView");
    const appShell = document.querySelector(".app-shell");
    const list = document.querySelector("#paperList");
    const query = document.querySelector("#query");
    const priority = document.querySelector("#priority");
    query.addEventListener("input", renderList);
    priority.addEventListener("change", renderList);
    document.querySelector("#tagFilter").addEventListener("change", renderList);
    document.querySelector("#readingMode").addEventListener("click", () => setListMode("reading"));
    document.querySelector("#selectionMode").addEventListener("click", () => setListMode("selection"));
    document.querySelector("#saveSelection").addEventListener("click", saveSelection);
    document.querySelector("#backToList").addEventListener("click", showList);
    document.querySelector("#readToggle").addEventListener("click", () => {{
      if (current) setRead(current, !isRead(current));
    }});
    document.querySelector("#intensiveToggle").addEventListener("click", () => {{
      if (current) setIntensive(current, !isIntensive(current));
    }});
    document.querySelector("#analysisMode").addEventListener("click", () => setLeftMode("analysis"));
    document.querySelector("#cnPdfMode").addEventListener("click", () => setLeftMode("cn"));
    document.querySelector("#noteTool").addEventListener("click", () => setNoteTool("note"));
    document.querySelector("#highlightTool").addEventListener("click", () => setNoteTool("highlight"));
    document.querySelector("#saveCnPdf").addEventListener("click", saveCnPdfNotes);
    document.querySelector("#clearCnNotes").addEventListener("click", clearCnNotes);

    function entryStatusKey(entry) {{
      return `paper-reading-status:${{entry.run_date}}:${{entry.arxiv_date}}`;
    }}
    function entrySelectionKey(entry) {{
      return `vla-planning-selection-${{entry.run_date}}-${{entry.arxiv_date}}`;
    }}
    function loadStatus(entry) {{
      const initial = Object.fromEntries(Object.entries(entry.status || {{}}).map(([key, item]) => [key, {{
        read: Boolean(item.read),
        read_at: item.read_at || "",
        intensive: Boolean(item.intensive),
        intensive_at: item.intensive_at || ""
      }}]));
      try {{ return {{ ...initial, ...JSON.parse(localStorage.getItem(entryStatusKey(entry)) || "{{}}") }}; }}
      catch (_) {{ return initial; }}
    }}
    function loadSelectionState(entry) {{
      const initial = {{}};
      for (const paper of entry.candidates || []) {{
        const key = candidateKey(paper);
        initial[key] = {{ priority: paper.priority || "", notes: paper.notes || "" }};
      }}
      try {{ return {{ ...initial, ...JSON.parse(localStorage.getItem(entrySelectionKey(entry)) || "{{}}") }}; }}
      catch (_) {{ return initial; }}
    }}
    function saveLocalStatus(entry) {{
      localStorage.setItem(entryStatusKey(entry), JSON.stringify(statusByEntry[entry.key] || {{}}));
      renderProgress();
    }}
    function saveLocalSelection(entry) {{
      localStorage.setItem(entrySelectionKey(entry), JSON.stringify(selectionByEntry[entry.key] || {{}}));
      renderSelectionCount();
    }}
    function currentEntries() {{
      if (activeScope.type === "year") return entries.filter((entry) => entry.year === activeScope.key);
      if (activeScope.type === "month") return entries.filter((entry) => entry.month === activeScope.key);
      return entries.filter((entry) => entry.key === activeScope.key);
    }}
    function visibleReadingPapers() {{
      return currentEntries().flatMap((entry) => entry.papers || []);
    }}
    function visibleCandidates() {{
      return currentEntries().flatMap((entry) => entry.candidates || []);
    }}
    function visibleItems() {{
      return listMode === "selection" ? visibleCandidates() : visibleReadingPapers();
    }}
    function entryForPaper(paper) {{
      return entries.find((entry) => entry.key === paper.entry_key) || entries[0] || {{}};
    }}
    async function loadServerStatus(entry) {{
      try {{
        const response = await fetch(`/reading-status?run_date=${{encodeURIComponent(entry.run_date)}}&arxiv_date=${{encodeURIComponent(entry.arxiv_date)}}`);
        const result = await response.json();
        if (response.ok && result.ok && result.status && Array.isArray(result.status.read_papers)) {{
          const next = {{}};
          for (const item of result.status.read_papers) {{
            if (item.reading_id) next[item.reading_id] = {{
              read: Boolean(item.read),
              read_at: item.read_at || "",
              intensive: Boolean(item.intensive),
              intensive_at: item.intensive_at || ""
            }};
          }}
          statusByEntry[entry.key] = next;
          saveLocalStatus(entry);
          renderList();
        }}
      }} catch (_) {{}}
    }}
    async function saveServerStatus(entry) {{
      const status = statusByEntry[entry.key] || {{}};
      const read_papers = (entry.papers || []).map((paper) => ({{
        reading_id: paper.reading_id,
        selector_id: paper.selector_id || "",
        arxiv_id: paper.arxiv_id,
        read: Boolean(status[paper.reading_id]?.read),
        read_at: status[paper.reading_id]?.read_at || "",
        intensive: Boolean(status[paper.reading_id]?.intensive),
        intensive_at: status[paper.reading_id]?.intensive_at || ""
      }}));
      try {{
        await fetch("/save-reading-status", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json;charset=utf-8" }},
          body: JSON.stringify({{
            run_date: entry.run_date,
            arxiv_date: entry.arxiv_date,
            updated_at: new Date().toISOString(),
            read_papers
          }})
        }});
      }} catch (_) {{}}
    }}
    function setRead(paper, read) {{
      const entry = entryForPaper(paper);
      const entryStatus = statusByEntry[entry.key] || {{}};
      const prior = entryStatus[paper.reading_id] || {{}};
      entryStatus[paper.reading_id] = {{ ...prior, read, read_at: read ? new Date().toISOString() : "" }};
      statusByEntry[entry.key] = entryStatus;
      saveLocalStatus(entry);
      saveServerStatus(entry);
      renderList();
      if (current && current.reading_id === paper.reading_id) renderReadToggle();
    }}
    function isRead(paper) {{ return Boolean(statusByEntry[paper.entry_key]?.[paper.reading_id]?.read); }}
    function setIntensive(paper, intensive) {{
      const entry = entryForPaper(paper);
      const entryStatus = statusByEntry[entry.key] || {{}};
      const prior = entryStatus[paper.reading_id] || {{}};
      entryStatus[paper.reading_id] = {{
        ...prior,
        intensive,
        intensive_at: intensive ? new Date().toISOString() : ""
      }};
      statusByEntry[entry.key] = entryStatus;
      saveLocalStatus(entry);
      saveServerStatus(entry);
      renderList();
      if (current && current.reading_id === paper.reading_id) renderIntensiveToggle();
    }}
    function isIntensive(paper) {{ return Boolean(statusByEntry[paper.entry_key]?.[paper.reading_id]?.intensive); }}
    function renderReadToggle() {{
      const button = document.querySelector("#readToggle");
      const read = current ? isRead(current) : false;
      button.textContent = read ? "已读" : "标记已读";
      button.classList.toggle("read", read);
      button.classList.toggle("primary", !read);
    }}
    function renderIntensiveToggle() {{
      const button = document.querySelector("#intensiveToggle");
      const intensive = current ? isIntensive(current) : false;
      button.textContent = intensive ? "精读中" : "精读";
      button.classList.toggle("intensive", intensive);
    }}
    function renderLeftMode() {{
      document.querySelector("#analysisMode").classList.toggle("active", leftMode === "analysis");
      document.querySelector("#cnPdfMode").classList.toggle("active", leftMode === "cn");
      const analysis = document.querySelector("#analysis");
      const cnPdf = document.querySelector("#cnPdfFrame");
      const cnAnnotator = document.querySelector("#cnAnnotator");
      const cnEmpty = document.querySelector("#cnEmpty");
      analysis.classList.toggle("hidden", leftMode !== "analysis");
      cnPdf.classList.add("hidden");
      cnAnnotator.classList.add("hidden");
      cnEmpty.classList.add("hidden");
      if (leftMode === "cn" && current) {{
        if (current.cn_pdf_path) {{
          cnPdf.removeAttribute("src");
          cnAnnotator.classList.remove("hidden");
          loadCnAnnotator(current);
        }} else {{
          cnPdf.removeAttribute("src");
          cnEmpty.classList.remove("hidden");
          cnEmpty.textContent = `${{current.reading_id}} 还没有生成中文 PDF。执行“继续指令”处理精读论文后会出现在这里。`;
        }}
      }}
    }}
    function setLeftMode(mode) {{
      leftMode = mode;
      renderLeftMode();
    }}
    function cnStorageKey() {{
      const entry = current ? entryForPaper(current) : null;
      return current && entry ? `paper-cn-notes:${{entry.run_date}}:${{entry.arxiv_date}}:${{current.reading_id}}` : "";
    }}
    function setNoteStatus(message) {{
      document.querySelector("#cnNoteStatus").textContent = message || "";
    }}
    function setNoteTool(tool) {{
      cnState.tool = tool;
      document.querySelector("#noteTool").classList.toggle("active", tool === "note");
      document.querySelector("#highlightTool").classList.toggle("active", tool === "highlight");
      setNoteStatus(tool === "note" ? "点击页面添加文字便签" : "拖拽页面添加高亮框");
    }}
    function loadStoredAnnotations() {{
      try {{ return JSON.parse(localStorage.getItem(cnStorageKey()) || "[]"); }}
      catch (_) {{ return []; }}
    }}
    function storeAnnotations() {{
      if (!current) return;
      localStorage.setItem(cnStorageKey(), JSON.stringify(cnState.annotations));
    }}
    async function loadCnAnnotator(paper) {{
      if (!window.PDFLib) {{
        setNoteStatus("PDF 保存组件加载失败，请检查网络或刷新页面。");
        return;
      }}
      const paperKey = `${{paper.run_date}}:${{paper.reading_id}}:${{paper.cn_pdf_path}}`;
      if (cnState.paperKey === paperKey && cnState.pdfDocument) {{
        renderAllAnnotationLayers();
        return;
      }}
      cnState = {{
        ...cnState,
        paperKey,
        pdfBytes: null,
        pdfDocument: null,
        annotations: loadStoredAnnotations(),
        pages: [],
        drawing: null
      }};
      const pages = document.querySelector("#cnPages");
      pages.innerHTML = `<div class="empty">正在加载中文 PDF...</div>`;
      setNoteStatus("");
      try {{
        const response = await fetch(paper.cn_pdf_path, {{ cache: "no-store" }});
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        const bytes = new Uint8Array(await response.arrayBuffer());
        cnState.pdfBytes = bytes;
        const rawPath = paper.cn_pdf_raw_path || paper.cn_pdf_path;
        const infoResponse = await fetch(`/cn-pdf-info?run_date=${{encodeURIComponent(paper.run_date || "")}}&path=${{encodeURIComponent(rawPath)}}`, {{ cache: "no-store" }});
        const info = await infoResponse.json();
        if (!infoResponse.ok || !info.ok) throw new Error(info.error || `HTTP ${{infoResponse.status}}`);
        cnState.pdfDocument = info;
        await renderCnPages();
        setNoteTool(cnState.tool);
      }} catch (error) {{
        pages.innerHTML = `<div class="empty">无法加载中文 PDF：${{escapeHtml(error.message)}}<br>${{escapeHtml(paper.cn_pdf_path)}}</div>`;
      }}
    }}
    async function renderCnPages() {{
      const pages = document.querySelector("#cnPages");
      pages.innerHTML = "";
      cnState.pages = [];
      const maxWidth = Math.max(320, pages.clientWidth - 28);
      for (let pageIndex = 0; pageIndex < cnState.pdfDocument.page_count; pageIndex += 1) {{
        const pageMeta = cnState.pdfDocument.pages[pageIndex] || {{}};
        const pageWidth = Number(pageMeta.width || 612);
        const zoom = Math.min(1.55, Math.max(0.7, maxWidth / pageWidth));
        const wrapper = document.createElement("div");
        wrapper.className = "cn-page";
        const image = document.createElement("img");
        image.alt = `中文 PDF 第 ${{pageIndex + 1}} 页`;
        const rawPath = current.cn_pdf_raw_path || current.cn_pdf_path;
        image.src = `/cn-pdf-page?run_date=${{encodeURIComponent(current.run_date || "")}}&path=${{encodeURIComponent(rawPath)}}&page=${{pageIndex}}&zoom=${{zoom.toFixed(3)}}&v=${{Date.now()}}`;
        const layer = document.createElement("canvas");
        layer.className = "cn-annotation-layer";
        layer.dataset.pageIndex = String(pageIndex);
        wrapper.append(image, layer);
        pages.append(wrapper);
        await new Promise((resolve, reject) => {{
          image.onload = resolve;
          image.onerror = () => reject(new Error(`无法渲染第 ${{pageIndex + 1}} 页`));
        }});
        wrapper.style.width = `${{image.naturalWidth}}px`;
        wrapper.style.height = `${{image.naturalHeight}}px`;
        layer.width = image.naturalWidth;
        layer.height = image.naturalHeight;
        cnState.pages.push({{ pageIndex, layer, width: layer.width, height: layer.height }});
        attachAnnotationEvents(layer);
      }}
      renderAllAnnotationLayers();
    }}
    function attachAnnotationEvents(layer) {{
      layer.addEventListener("pointerdown", (event) => {{
        if (cnState.tool === "note") {{
          const point = layerPoint(layer, event);
          const text = prompt("输入这条笔记：");
          if (!text || !text.trim()) return;
          cnState.annotations.push({{
            type: "note",
            pageIndex: Number(layer.dataset.pageIndex),
            x: point.x / layer.width,
            y: point.y / layer.height,
            text: text.trim()
          }});
          storeAnnotations();
          renderAllAnnotationLayers();
          setNoteStatus("已添加文字便签，点击“保存到PDF”写回文件");
          return;
        }}
        const point = layerPoint(layer, event);
        cnState.drawing = {{
          pageIndex: Number(layer.dataset.pageIndex),
          layer,
          startX: point.x,
          startY: point.y,
          endX: point.x,
          endY: point.y
        }};
        layer.setPointerCapture(event.pointerId);
      }});
      layer.addEventListener("pointermove", (event) => {{
        if (!cnState.drawing || cnState.drawing.layer !== layer) return;
        const point = layerPoint(layer, event);
        cnState.drawing.endX = point.x;
        cnState.drawing.endY = point.y;
        renderAllAnnotationLayers();
        drawHighlight(layer, cnState.drawing.startX, cnState.drawing.startY, cnState.drawing.endX, cnState.drawing.endY);
      }});
      layer.addEventListener("pointerup", (event) => {{
        if (!cnState.drawing || cnState.drawing.layer !== layer) return;
        const drawing = cnState.drawing;
        cnState.drawing = null;
        const x = Math.min(drawing.startX, drawing.endX);
        const y = Math.min(drawing.startY, drawing.endY);
        const w = Math.abs(drawing.endX - drawing.startX);
        const h = Math.abs(drawing.endY - drawing.startY);
        if (w < 8 || h < 8) {{
          renderAllAnnotationLayers();
          return;
        }}
        cnState.annotations.push({{
          type: "highlight",
          pageIndex: drawing.pageIndex,
          x: x / layer.width,
          y: y / layer.height,
          w: w / layer.width,
          h: h / layer.height
        }});
        storeAnnotations();
        renderAllAnnotationLayers();
        setNoteStatus("已添加高亮框，点击“保存到PDF”写回文件");
        try {{ layer.releasePointerCapture(event.pointerId); }} catch (_) {{}}
      }});
    }}
    function layerPoint(layer, event) {{
      const rect = layer.getBoundingClientRect();
      return {{
        x: Math.max(0, Math.min(layer.width, (event.clientX - rect.left) * layer.width / rect.width)),
        y: Math.max(0, Math.min(layer.height, (event.clientY - rect.top) * layer.height / rect.height))
      }};
    }}
    function renderAllAnnotationLayers() {{
      for (const page of cnState.pages) {{
        const ctx = page.layer.getContext("2d");
        ctx.clearRect(0, 0, page.width, page.height);
        for (const annotation of cnState.annotations.filter((item) => item.pageIndex === page.pageIndex)) {{
          drawAnnotation(ctx, page.width, page.height, annotation);
        }}
      }}
    }}
    function drawHighlight(layer, x1, y1, x2, y2) {{
      const ctx = layer.getContext("2d");
      ctx.save();
      ctx.fillStyle = "rgba(255, 221, 73, 0.32)";
      ctx.strokeStyle = "rgba(166, 118, 0, 0.75)";
      ctx.lineWidth = 2;
      ctx.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
      ctx.strokeRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
      ctx.restore();
    }}
    function drawAnnotation(ctx, width, height, annotation) {{
      if (annotation.type === "highlight") {{
        drawHighlight(ctx.canvas, annotation.x * width, annotation.y * height, (annotation.x + annotation.w) * width, (annotation.y + annotation.h) * height);
        return;
      }}
      const x = annotation.x * width;
      const y = annotation.y * height;
      const boxWidth = Math.min(260, Math.max(150, width - x - 12));
      const lines = wrapCanvasText(ctx, annotation.text || "", boxWidth - 16);
      const lineHeight = 18;
      const boxHeight = Math.max(34, lines.length * lineHeight + 14);
      ctx.save();
      ctx.fillStyle = "rgba(255, 246, 173, 0.92)";
      ctx.strokeStyle = "rgba(116, 88, 0, 0.85)";
      ctx.lineWidth = 1.5;
      ctx.fillRect(x, y, boxWidth, boxHeight);
      ctx.strokeRect(x, y, boxWidth, boxHeight);
      ctx.fillStyle = "#2f2b16";
      ctx.font = "14px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
      ctx.textBaseline = "top";
      lines.forEach((line, index) => ctx.fillText(line, x + 8, y + 7 + index * lineHeight));
      ctx.restore();
    }}
    function wrapCanvasText(ctx, text, maxWidth) {{
      ctx.font = "14px -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
      const lines = [];
      let currentLine = "";
      for (const char of text) {{
        const nextLine = currentLine + char;
        if (currentLine && ctx.measureText(nextLine).width > maxWidth) {{
          lines.push(currentLine);
          currentLine = char;
        }} else {{
          currentLine = nextLine;
        }}
      }}
      if (currentLine) lines.push(currentLine);
      return lines.slice(0, 8);
    }}
    async function saveCnPdfNotes() {{
      if (!current || !current.cn_pdf_path || !cnState.pdfBytes) return;
      if (!cnState.annotations.length) {{
        setNoteStatus("没有未保存的标注");
        return;
      }}
      try {{
        setNoteStatus("正在写入 PDF...");
        const pdfDoc = await PDFLib.PDFDocument.load(cnState.pdfBytes);
        const pages = pdfDoc.getPages();
        for (const pageInfo of cnState.pages) {{
          const pageAnnotations = cnState.annotations.filter((item) => item.pageIndex === pageInfo.pageIndex);
          if (!pageAnnotations.length) continue;
          const overlay = document.createElement("canvas");
          overlay.width = pageInfo.width;
          overlay.height = pageInfo.height;
          const ctx = overlay.getContext("2d");
          pageAnnotations.forEach((annotation) => drawAnnotation(ctx, overlay.width, overlay.height, annotation));
          const pngBytes = await canvasToPngBytes(overlay);
          const png = await pdfDoc.embedPng(pngBytes);
          const page = pages[pageInfo.pageIndex];
          page.drawImage(png, {{ x: 0, y: 0, width: page.getWidth(), height: page.getHeight() }});
        }}
        const savedBytes = await pdfDoc.save();
        const response = await fetch("/save-cn-pdf", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json;charset=utf-8" }},
          body: JSON.stringify({{
            run_date: current.run_date || "",
            path: current.cn_pdf_raw_path || current.cn_pdf_path,
            pdf_base64: bytesToBase64(savedBytes)
          }})
        }});
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${{response.status}}`);
        cnState.pdfBytes = new Uint8Array(savedBytes);
        cnState.pdfDocument = null;
        cnState.paperKey = "";
        cnState.annotations = [];
        storeAnnotations();
        await loadCnAnnotator(current);
        setNoteStatus(`已保存到本地 PDF，备份：${{result.backup_path || ""}}`);
      }} catch (error) {{
        setNoteStatus(`保存失败：${{error.message}}`);
      }}
    }}
    async function canvasToPngBytes(canvas) {{
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
      return new Uint8Array(await blob.arrayBuffer());
    }}
    function bytesToBase64(bytes) {{
      let binary = "";
      const chunkSize = 0x8000;
      for (let i = 0; i < bytes.length; i += chunkSize) {{
        binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
      }}
      return btoa(binary);
    }}
    function clearCnNotes() {{
      if (!cnState.annotations.length) return;
      if (!confirm("清空当前未保存的 PDF 标注？已写入 PDF 的内容不会被删除。")) return;
      cnState.annotations = [];
      storeAnnotations();
      renderAllAnnotationLayers();
      setNoteStatus("未保存标注已清空");
    }}
    function candidateKey(paper) {{
      return paper.arxiv_id || paper.paper_id || paper.title;
    }}
    function candidateState(paper) {{
      const entry = entryForPaper(paper);
      const key = candidateKey(paper);
      selectionByEntry[entry.key] = selectionByEntry[entry.key] || {{}};
      selectionByEntry[entry.key][key] = selectionByEntry[entry.key][key] || {{ priority: paper.priority || "", notes: paper.notes || "" }};
      return selectionByEntry[entry.key][key];
    }}
    function candidateSelected(paper) {{
      const state = candidateState(paper);
      return Boolean(state.priority || (state.notes || "").trim());
    }}
    function selectedCandidates(entry) {{
      return (entry.candidates || []).filter(candidateSelected).map((paper) => {{
        const state = candidateState(paper);
        return {{
          paper_id: paper.paper_id || "",
          arxiv_id: paper.arxiv_id || "",
          title: paper.title || "",
          pdf_url: paper.pdf_url || "",
          priority: state.priority || "",
          notes: (state.notes || "").trim()
        }};
      }});
    }}
    function setListMode(mode) {{
      listMode = mode;
      document.querySelector("#readingMode").classList.toggle("active", mode === "reading");
      document.querySelector("#selectionMode").classList.toggle("active", mode === "selection");
      document.querySelector("#selectionActions").classList.toggle("visible", mode === "selection");
      list.classList.toggle("selection-list", mode === "selection");
      renderList();
    }}
    function scopeMatches(entry, type, key) {{
      if (type === "year") return entry.year === key;
      if (type === "month") return entry.month === key;
      return entry.key === key;
    }}
    function setScope(type, key) {{
      activeScope = {{ type, key }};
      current = null;
      showList();
      renderArchive();
    }}
    function renderArchive() {{
      const tree = document.querySelector("#archiveTree");
      tree.innerHTML = "";
      const years = [...new Set(entries.map((entry) => entry.year))].sort().reverse();
      for (const year of years) {{
        const yearBtn = document.createElement("button");
        yearBtn.className = `archive-button${{activeScope.type === "year" && activeScope.key === year ? " active" : ""}}`;
        yearBtn.textContent = `${{year}} 年`;
        yearBtn.addEventListener("click", () => setScope("year", year));
        tree.append(yearBtn);
        const months = [...new Set(entries.filter((entry) => entry.year === year).map((entry) => entry.month))].sort().reverse();
        for (const month of months) {{
          const monthBtn = document.createElement("button");
          monthBtn.className = `archive-button archive-month${{activeScope.type === "month" && activeScope.key === month ? " active" : ""}}`;
          monthBtn.textContent = month;
          monthBtn.addEventListener("click", () => setScope("month", month));
          tree.append(monthBtn);
          for (const entry of entries.filter((item) => item.month === month).sort((a, b) => b.run_date.localeCompare(a.run_date))) {{
            const dateBtn = document.createElement("button");
            dateBtn.className = `archive-button archive-date${{activeScope.type === "date" && activeScope.key === entry.key ? " active" : ""}}`;
            dateBtn.textContent = `${{entry.run_date}} · ${{entry.papers.length}} 篇`;
            dateBtn.addEventListener("click", () => setScope("date", entry.key));
            tree.append(dateBtn);
          }}
        }}
      }}
    }}
    function renderTagOptions() {{
      const tagSelect = document.querySelector("#tagFilter");
      for (const tag of archive.tags || []) {{
        const option = document.createElement("option");
        option.value = tag;
        option.textContent = tag;
        tagSelect.append(option);
      }}
    }}
    function renderProgress() {{
      const papers = visibleReadingPapers();
      const readCount = papers.filter(isRead).length;
      document.querySelector("#progress").textContent = `${{readCount}}/${{papers.length}}`;
    }}
    function renderSelectionCount() {{
      const selected = currentEntries().reduce((count, entry) => count + selectedCandidates(entry).length, 0);
      const total = visibleCandidates().length;
      document.querySelector("#selectionNotice").textContent = `已选择 ${{selected}} / ${{total}} 篇`;
    }}
    function renderList() {{
      const q = query.value.trim().toLowerCase();
      const p = priority.value;
      const tag = document.querySelector("#tagFilter").value;
      list.innerHTML = "";
      const rows = visibleItems().filter((paper) => {{
        const haystack = `${{paper.reading_id || paper.paper_id || ""}} ${{paper.arxiv_id}} ${{paper.title}} ${{(paper.topics || []).join(" ")}}`.toLowerCase();
        const itemPriority = listMode === "selection" ? candidateState(paper).priority : paper.priority;
        return (!q || haystack.includes(q)) && (!p || itemPriority === p) && (!tag || (paper.topics || []).includes(tag));
      }});
      for (const paper of rows) {{
        if (listMode === "selection") {{
          renderCandidateRow(paper);
          continue;
        }}
        const row = document.createElement("div");
        row.className = `paper-row${{paper === current ? " active" : ""}}${{isRead(paper) ? " read" : ""}}${{isIntensive(paper) ? " intensive" : ""}}`;
        const body = document.createElement("div");
        body.className = "row-body";
        const intensive = isIntensive(paper);
        body.innerHTML = `
          <div class="row-id">${{escapeHtml(paper.reading_id)}} · arXiv:${{escapeHtml(paper.arxiv_id)}}</div>
          <div class="row-title">${{escapeHtml(paper.title)}}</div>
          <div class="row-meta">
            <span class="pill priority-${{escapeHtml((paper.priority || "").toLowerCase())}}">级别 ${{escapeHtml(paper.priority || "-")}}</span>
            ${{intensive ? `<span class="pill intensive-state">精读</span>` : ""}}
            ${{(paper.topics || []).map((topic) => `<span class="pill">${{escapeHtml(topic)}}</span>`).join("")}}
          </div>
        `;
        row.append(body);
        row.addEventListener("click", () => selectPaper(paper));
        list.append(row);
      }}
      if (!rows.length) list.innerHTML = `<div class="empty">没有匹配的论文。</div>`;
      renderProgress();
      renderSelectionCount();
    }}
    function renderCandidateRow(paper) {{
      const row = document.createElement("div");
      row.className = `paper-row candidate${{candidateSelected(paper) ? " selected" : ""}}`;
      const state = candidateState(paper);
      const status = document.createElement("div");
      status.className = "candidate-status";
      status.textContent = candidateSelected(paper) ? "已选择" : "未选择";
      const body = document.createElement("div");
      body.className = "row-body";
      const authors = (paper.authors || []).join(", ") || "未获取到作者";
      const institutions = paper.institutions || "机构待补充；可从 arXiv HTML 或 TeX source 确认。";
      const summaryZh = paper.summary_zh || "中文摘要待补充；可先参考英文摘要。";
      body.innerHTML = `
        <div class="row-id">${{escapeHtml(paper.paper_id || "")}} · arXiv:${{escapeHtml(paper.arxiv_id || "")}}</div>
        <div class="row-title">${{escapeHtml(paper.title || "")}}</div>
        <div class="row-meta">
          ${{(paper.topics || []).map((topic) => `<span class="pill">${{escapeHtml(topic)}}</span>`).join("")}}
        </div>
        <div class="candidate-info">
          <p><strong>作者：</strong>${{escapeHtml(authors)}}</p>
          <p><strong>机构：</strong>${{escapeHtml(institutions)}}</p>
          <p><strong>推荐理由：</strong>${{escapeHtml(paper.reason || "")}}</p>
          <p class="candidate-summary"><strong>中文摘要：</strong>${{escapeHtml(summaryZh)}}</p>
        </div>
      `;
      const controls = document.createElement("div");
      controls.className = "candidate-controls";
      const select = document.createElement("select");
      select.innerHTML = `<option value="">不选择</option><option value="A">A：精读</option><option value="B">B：有时间看</option><option value="C">C：保留</option>`;
      select.value = state.priority || "";
      const notes = document.createElement("textarea");
      notes.placeholder = "备注";
      notes.value = state.notes || "";
      select.addEventListener("change", () => {{
        state.priority = select.value;
        saveLocalSelection(entryForPaper(paper));
        renderList();
      }});
      notes.addEventListener("input", () => {{
        state.notes = notes.value;
        saveLocalSelection(entryForPaper(paper));
        row.classList.toggle("selected", candidateSelected(paper));
        status.textContent = candidateSelected(paper) ? "已选择" : "未选择";
      }});
      controls.append(select, notes);
      body.append(controls);
      row.append(status, body);
      list.append(row);
    }}
    async function saveSelection() {{
      const targetEntries = currentEntries();
      for (const entry of targetEntries) {{
        const selected = selectedCandidates(entry);
        await fetch("/save-selection", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json;charset=utf-8" }},
          body: JSON.stringify({{
            source: `dashboard:${{entry.run_date}}:${{entry.arxiv_date}}`,
            run_date: entry.run_date,
            arxiv_date: entry.arxiv_date,
            selected_at: new Date().toISOString(),
            selected_papers: selected
          }})
        }});
      }}
      document.querySelector("#selectionNotice").textContent = "已保存选择 JSON";
    }}
    function showList() {{
      appShell.classList.remove("reader-active");
      listView.classList.remove("hidden");
      readerView.classList.add("hidden");
      renderList();
    }}
    async function selectPaper(paper) {{
      current = paper;
      appShell.classList.add("reader-active");
      listView.classList.add("hidden");
      readerView.classList.remove("hidden");
      document.querySelector("#readerId").textContent = paper.reading_id;
      document.querySelector("#sourceLink").href = paper.pdf_path;
      document.querySelector("#pdfFrame").src = paper.pdf_path;
      renderReadToggle();
      renderIntensiveToggle();
      renderList();
      const analysis = document.querySelector("#analysis");
      analysis.innerHTML = `<div class="empty">正在加载 ${{escapeHtml(paper.reading_id)}} 的分析...</div>`;
      try {{
        const response = await fetch(paper.analysis_path);
        if (!response.ok) throw new Error(`HTTP ${{response.status}}`);
        const markdown = await response.text();
        analysis.innerHTML = renderMarkdown(markdown, paper.analysis_path);
      }} catch (error) {{
        analysis.innerHTML = `<div class="empty">无法加载分析文件：${{escapeHtml(error.message)}}<br>${{escapeHtml(paper.analysis_path)}}</div>`;
      }}
      renderLeftMode();
    }}
    function renderMarkdown(markdown, basePath) {{
      const lines = markdown.replace(/\\r\\n/g, "\\n").split("\\n");
      const html = [];
      let inCode = false;
      let code = [];
      let table = [];
      function flushCode() {{
        if (code.length) html.push(`<pre><code>${{escapeHtml(code.join("\\n"))}}</code></pre>`);
        code = [];
      }}
      function flushTable() {{
        if (!table.length) return;
        const rows = table.filter((line) => !/^\\|?\\s*:?-{{3,}}/.test(line.replace(/\\|/g, "")));
        html.push("<table>");
        rows.forEach((line, index) => {{
          const cells = line.replace(/^\\||\\|$/g, "").split("|").map((cell) => cell.trim());
          html.push(index === 0 ? "<thead><tr>" : "<tbody><tr>");
          for (const cell of cells) html.push(index === 0 ? `<th>${{inlineMd(cell, basePath)}}</th>` : `<td>${{inlineMd(cell, basePath)}}</td>`);
          html.push(index === 0 ? "</tr></thead>" : "</tr></tbody>");
        }});
        html.push("</table>");
        table = [];
      }}
      for (const line of lines) {{
        if (line.startsWith("```")) {{
          if (inCode) {{ flushCode(); inCode = false; }} else {{ flushTable(); inCode = true; }}
          continue;
        }}
        if (inCode) {{ code.push(line); continue; }}
        if (/^\\|.*\\|$/.test(line.trim())) {{ table.push(line.trim()); continue; }}
        flushTable();
        const trimmed = line.trim();
        if (!trimmed) {{ html.push(""); continue; }}
        const heading = trimmed.match(/^(#{{1,4}})\\s+(.*)$/);
        if (heading) {{
          const level = heading[1].length;
          html.push(`<h${{level}}>${{inlineMd(heading[2], basePath)}}</h${{level}}>`);
        }} else if (/^[-*]\\s+/.test(trimmed)) {{
          html.push(`<p>• ${{inlineMd(trimmed.replace(/^[-*]\\s+/, ""), basePath)}}</p>`);
        }} else {{
          html.push(`<p>${{inlineMd(trimmed, basePath)}}</p>`);
        }}
      }}
      flushTable();
      flushCode();
      return html.join("\\n");
    }}
    function inlineMd(value, basePath) {{
      let out = escapeHtml(value);
      out = out.replace(/!\\[([^\\]]*)\\]\\(([^)]+)\\)/g, (_, alt, path) => `<img alt="${{escapeHtml(alt)}}" src="${{resolveRelative(path, basePath)}}">`);
      out = out.replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g, (_, text, path) => `<a href="${{resolveRelative(path, basePath)}}" target="_blank" rel="noopener">${{escapeHtml(text)}}</a>`);
      out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
      return out;
    }}
    function resolveRelative(path, basePath) {{
      if (/^(https?:|file:|\\/)/.test(path)) return path;
      return new URL(path, new URL(basePath, window.location.href)).href;
    }}
    function escapeHtml(value) {{
      return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }}
    renderArchive();
    renderTagOptions();
    renderList();
    entries.forEach((entry) => loadServerStatus(entry));
  </script>
</body>
</html>
"""


def write_reading_dashboard(
    root: Path,
    run_dir: Path,
    arxiv_date: str,
    analysis_items: List[Dict[str, object]],
) -> Dict[str, Path]:
    manifest = build_manifest(root, run_dir, arxiv_date, analysis_items)
    manifest_path = run_dir / f"reading_manifest_{arxiv_date}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dashboard_path = write_global_dashboard(root, manifest)
    status_path = run_dir / f"reading_status_{arxiv_date}.json"
    status_payload = {
        "run_date": run_dir.name,
        "arxiv_date": arxiv_date,
        "updated_at": "",
        "read_papers": [],
    }
    if status_path.exists():
        try:
            status_payload.update(json.loads(status_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass

    selector_by_reading_id = {
        str(paper["reading_id"]): str(paper.get("selector_id", "")) for paper in manifest["papers"]
    }
    migrated_read_papers = []
    for item in status_payload.get("read_papers", []):
        if not isinstance(item, dict):
            continue
        item_reading_id = str(item.get("reading_id") or "").strip()
        migrated_read_papers.append(
            {
                "reading_id": item_reading_id,
                "selector_id": str(
                    item.get("selector_id") or item.get("paper_id") or selector_by_reading_id.get(item_reading_id, "")
                ).strip(),
                "arxiv_id": str(item.get("arxiv_id") or "").strip(),
                "read": bool(item.get("read")),
                "read_at": str(item.get("read_at") or "").strip(),
                "intensive": bool(item.get("intensive")),
                "intensive_at": str(item.get("intensive_at") or "").strip(),
            }
        )
    status_payload["run_date"] = run_dir.name
    status_payload["arxiv_date"] = arxiv_date
    status_payload["read_papers"] = migrated_read_papers
    status_path.write_text(json.dumps(status_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"manifest": manifest_path, "dashboard": dashboard_path, "status": status_path}


def refresh_cn_pdf_paths(manifest_path: Path) -> Dict[str, Path]:
    run_dir = manifest_path.resolve().parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for paper in manifest.get("papers", []):
        if not isinstance(paper, dict):
            continue
        paper["cn_pdf_path"] = find_cn_pdf(
            run_dir,
            str(paper.get("reading_id", "")),
            str(paper.get("arxiv_id", "")),
        )
    manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
    arxiv_date = str(manifest.get("arxiv_date") or manifest_path.name.removeprefix("reading_manifest_").removesuffix(".json"))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    root = run_dir.parent.parent if run_dir.parent.name == "runs" else Path.cwd().resolve()
    dashboard_path = write_global_dashboard(root, manifest)
    return {"manifest": manifest_path, "dashboard": dashboard_path}


def write_shortlist_dashboard(root: Path, shortlist_path: Path) -> Dict[str, Path]:
    shortlist = json.loads(shortlist_path.read_text(encoding="utf-8"))
    run_dir = shortlist_path.resolve().parent
    arxiv_date = str(shortlist.get("arxiv_date") or shortlist_path.name.removeprefix("shortlist_vla_planning_").removesuffix(".json"))
    manifest_path = run_dir / f"reading_manifest_{arxiv_date}.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
    else:
        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run_date": run_dir.name,
            "arxiv_date": arxiv_date,
            "root": relpath(root.resolve(), run_dir.resolve()),
            "paper_count": 0,
            "papers": [],
        }
    dashboard_path = write_global_dashboard(root, manifest)
    return {"dashboard": dashboard_path}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render reading dashboard from an analysis task.")
    parser.add_argument("analysis_task", type=Path, nargs="?", help="llm_analysis_task_<scope>.md")
    parser.add_argument("--refresh-manifest", type=Path, help="Refresh cn_pdf_path values in an existing reading manifest.")
    parser.add_argument("--shortlist", type=Path, help="Render a reading dashboard from a shortlist JSON before paper selection.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project root. Default: current directory.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.refresh_manifest:
        paths = refresh_cn_pdf_paths(args.refresh_manifest)
        print(f"Reading manifest refreshed: {paths['manifest']}")
        print(f"Reading dashboard refreshed: {paths['dashboard']}")
        return 0
    if args.shortlist:
        paths = write_shortlist_dashboard(args.root.resolve(), args.shortlist)
        print(f"Reading dashboard rendered: {paths['dashboard']}")
        return 0
    raise SystemExit("Use write_reading_dashboard from process_selection.py, or pass --refresh-manifest.")


if __name__ == "__main__":
    raise SystemExit(main())
