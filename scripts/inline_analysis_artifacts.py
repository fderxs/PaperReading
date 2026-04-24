#!/usr/bin/env python3
"""Inline selected figures/tables into analysis Markdown and remove appendix dumps."""

import argparse
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional


ROOT_DIR = Path(__file__).resolve().parent.parent
METHOD_START = "<!-- inline-artifacts:method:start -->"
METHOD_END = "<!-- inline-artifacts:method:end -->"
EXPERIMENT_START = "<!-- inline-artifacts:experiments:start -->"
EXPERIMENT_END = "<!-- inline-artifacts:experiments:end -->"


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


def arxiv_id_from_path(path: Path) -> str:
    return path.name.split("_", 1)[0]


def load_json(path: Path) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def relpath(target: str, analysis_path: Path) -> str:
    return Path(os.path.relpath(Path(target).resolve(), analysis_path.parent.resolve())).as_posix()


def normalize(text: str) -> str:
    return " ".join(text.split())


def strip_between_markers(content: str, start: str, end: str) -> str:
    pattern = re.compile(rf"\n?{re.escape(start)}[\s\S]*?{re.escape(end)}\n?", re.M)
    return pattern.sub("\n", content)


def strip_artifact_appendix(content: str) -> str:
    return re.sub(r"\n## 11\. PDF 图表与表格附件[\s\S]*$", "\n", content, flags=re.M)


def choose_first(
    captions: List[Dict[str, object]],
    *,
    kind: str,
    include: List[str],
    exclude: Optional[List[str]] = None,
    used_paths: Optional[set[str]] = None,
) -> Optional[Dict[str, object]]:
    exclude = exclude or []
    used_paths = used_paths or set()
    for caption in captions:
        if caption.get("kind") != kind:
            continue
        crop_path = str(caption.get("crop_path") or "")
        if not crop_path or crop_path in used_paths:
            continue
        text = normalize(str(caption.get("text") or "")).lower()
        if exclude and any(keyword in text for keyword in exclude):
            continue
        if any(keyword in text for keyword in include):
            return caption
    return None


def choose_fallback(
    captions: List[Dict[str, object]],
    *,
    kind: str,
    used_paths: Optional[set[str]] = None,
) -> Optional[Dict[str, object]]:
    used_paths = used_paths or set()
    for caption in captions:
        if caption.get("kind") != kind:
            continue
        crop_path = str(caption.get("crop_path") or "")
        if crop_path and crop_path not in used_paths:
            return caption
    return None


def score_method_caption(caption: Dict[str, object]) -> int:
    if caption.get("kind") != "Figure":
        return -10_000

    text = normalize(str(caption.get("text") or ""))
    lower = text.lower()
    page = int(caption.get("page") or 0)
    score = 0

    strong_positive = {
        "model architecture": 14,
        "architecture": 12,
        "operational workflow": 12,
        "workflow": 10,
        "pipeline": 10,
        "system overview": 10,
        "framework": 7,
        "overview": 7,
        "diagram": 6,
    }
    medium_positive = {
        "illustrating": 5,
        "proposed": 4,
        "composed of": 5,
        "consists of": 5,
        "encoder": 5,
        "decoder": 5,
        "fusion": 5,
        "module": 4,
        "policy": 4,
        "value head": 4,
        "attention": 3,
        "disentangled": 4,
        "reward function": 4,
        "occupancy measure": 4,
        "latent space": 3,
    }
    strong_negative = {
        "success rate": -14,
        "performance comparison": -14,
        "comparison across": -12,
        "comparison between": -12,
        "benchmark": -10,
        "evaluation results": -12,
        "retrieval performance": -12,
        "results": -10,
        "brier score": -14,
        "roc-auc": -12,
        "ablation": -12,
        "qualitative comparison": -10,
        "real-world task": -8,
        "real-robot tasks": -8,
        "task executions": -8,
        "distribution analysis": -10,
        "data distribution": -10,
        "dataset statistics": -10,
    }

    for keyword, weight in strong_positive.items():
        if keyword in lower:
            score += weight
    for keyword, weight in medium_positive.items():
        if keyword in lower:
            score += weight
    for keyword, weight in strong_negative.items():
        if keyword in lower:
            score += weight

    if page == 1:
        score += 1
    elif 2 <= page <= 5:
        score += 3
    elif 6 <= page <= 8:
        score += 1

    if lower.startswith("figure 1") or lower.startswith("fig. 1"):
        score += 1

    return score


def select_method_caption(captions: List[Dict[str, object]]) -> Optional[Dict[str, object]]:
    figure_captions = [caption for caption in captions if caption.get("kind") == "Figure"]
    if not figure_captions:
        return None

    scored = sorted(
        ((score_method_caption(caption), caption) for caption in figure_captions),
        key=lambda item: item[0],
        reverse=True,
    )
    best_score, best_caption = scored[0]
    return best_caption if best_score >= 8 else None


def method_note(text: str) -> str:
    lower = text.lower()
    if any(keyword in lower for keyword in ["overview", "system"]):
        return "图：系统总览图。阅读时重点看训练阶段、数据流和模块分工分别承担什么作用。"
    if any(keyword in lower for keyword in ["architecture", "framework", "pipeline"]):
        return "图：方法架构图。阅读时重点看输入表征、核心模块之间的信息流，以及最终动作/规划输出是怎样汇聚出来的。"
    return "图：论文关键方法图。阅读时重点看模型输入、核心机制和输出之间的连接关系。"


def result_note(text: str, kind: str) -> str:
    lower = text.lower()
    if "ablation" in lower:
        return "表：消融实验。重点核对去掉关键模块或数据来源后性能是否稳定下降，用来判断创新点到底来自结构、数据还是训练策略。"
    if any(keyword in lower for keyword in ["real-world", "real robot", "perturbation", "robustness"]):
        return "图：真实机器人或扰动结果。阅读时优先核对方法在分布变化、初始化变化或环境扰动下是否还能保持稳定优势。"
    if any(keyword in lower for keyword in ["comparison", "benchmark", "evaluation results", "success rate", "performance"]):
        prefix = "表" if kind == "Table" else "图"
        return f"{prefix}：主结果比较。阅读时优先核对作者方法相对最强 baseline 的绝对提升，以及优势是否在多个子任务或设置上都成立。"
    return "图：关键实验结果可视化。阅读时重点看正文里的核心判断是否有直接证据支撑。" if kind == "Figure" else "表：关键实验结果。阅读时重点看正文里的核心判断是否有直接证据支撑。"


def make_method_block(caption: Dict[str, object], analysis_path: Path) -> str:
    crop_path = relpath(str(caption["crop_path"]), analysis_path)
    title = normalize(str(caption.get("text") or f"Figure {caption.get('number', '')}"))
    return (
        f"{METHOD_START}\n\n"
        f"![{title}]({crop_path})\n"
        f"{method_note(title)}\n\n"
        f"{METHOD_END}"
    )


def make_experiment_block(captions: List[Dict[str, object]], analysis_path: Path) -> str:
    lines = [EXPERIMENT_START, ""]
    for caption in captions:
        crop_path = relpath(str(caption["crop_path"]), analysis_path)
        title = normalize(str(caption.get("text") or f"{caption.get('kind')} {caption.get('number', '')}"))
        lines.append(f"![{title}]({crop_path})")
        lines.append(result_note(title, str(caption.get("kind") or "")))
        table_path = str(caption.get("table_path") or "")
        if table_path:
            lines.append(f"表格文本参考：[查看 Markdown 表格]({relpath(table_path, analysis_path)})")
        lines.append("")
    lines.append(EXPERIMENT_END)
    return "\n".join(lines)


def replace_method_section(content: str, block: str) -> str:
    content = strip_between_markers(content, METHOD_START, METHOD_END)
    pattern = re.compile(r"(### 5\.1 总体框架\s*\n\n)")
    if pattern.search(content):
        return pattern.sub(rf"\1{block}\n\n", content, count=1)
    return content


def replace_experiment_section(content: str, block: str) -> str:
    content = strip_between_markers(content, EXPERIMENT_START, EXPERIMENT_END)
    pattern = re.compile(r"### 6\.1 [^\n]+\n[\s\S]*?(?=\n## 7\.)", re.M)
    replacement = f"### 6.1 关键图表解读\n\n{block}\n"
    if pattern.search(content):
        return pattern.sub(replacement, content, count=1)
    insert_pattern = re.compile(r"(## 6\. 实验与结果\s*\n)")
    if insert_pattern.search(content):
        return insert_pattern.sub(rf"\1\n### 6.1 关键图表解读\n\n{block}\n", content, count=1)
    return content


def refresh_header_note(content: str) -> str:
    new_note = (
        "> 本文件由 LLM-in-the-loop 流程生成。只在正文中插入真正有助于理解论文的关键图表；"
        "完整抽取结果保留在同日的 `artifacts/`、`figures/` 和 `tables/` 目录中。"
    )
    return re.sub(r"^> 本文件由 .*?$", new_note, content, count=1, flags=re.M)


def curate_captions(artifact: Dict[str, object]) -> tuple[Optional[Dict[str, object]], List[Dict[str, object]]]:
    captions = list(artifact.get("captions", []))
    used_paths: set[str] = set()

    method_caption = select_method_caption(captions)
    if method_caption and method_caption.get("crop_path"):
        used_paths.add(str(method_caption["crop_path"]))

    def is_main_table_candidate(caption: Dict[str, object]) -> bool:
        number = str(caption.get("number") or "")
        text = normalize(str(caption.get("text") or "")).lower()
        if re.fullmatch(r"[A-Z]|T\d+", number):
            return False
        if len(text) < 25:
            return False
        banned = [
            "task description",
            "details of the dataset",
            "details of the datasets",
            "task list",
            "dataset used",
            "datasets used",
            "full evaluation results",
        ]
        return not any(keyword in text for keyword in banned)

    main_result = choose_first(
        [caption for caption in captions if is_main_table_candidate(caption)],
        kind="Table",
        include=["quantitative comparison", "evaluation results", "success rate", "accuracy", "f1 score", "comparison", "performance"],
        exclude=["ablation"],
        used_paths=used_paths,
    ) or choose_fallback(
        [caption for caption in captions if is_main_table_candidate(caption)],
        kind="Table",
        used_paths=used_paths,
    )
    if main_result and main_result.get("crop_path"):
        used_paths.add(str(main_result["crop_path"]))

    ablation = choose_first(
        captions,
        kind="Table",
        include=["ablation"],
        used_paths=used_paths,
    )
    if ablation and ablation.get("crop_path"):
        used_paths.add(str(ablation["crop_path"]))

    result_figure = choose_first(
        captions,
        kind="Figure",
        include=["real-world", "real robot", "real-robot", "results", "performance", "benchmark", "tasks", "robustness", "perturbation", "success rate", "comparison of baseline"],
        exclude=["architecture", "framework", "overview", "system", "pipeline", "distribution", "dataset statistics", "data distribution"],
        used_paths=used_paths,
    )

    experiment_captions = [item for item in [main_result, ablation, result_figure] if item]
    return method_caption, experiment_captions


def process_analysis(analysis_path: Path, artifact_path: Path) -> None:
    content = analysis_path.read_text(encoding="utf-8")
    artifact = load_json(artifact_path)
    method_caption, experiment_captions = curate_captions(artifact)

    content = refresh_header_note(content)
    content = strip_artifact_appendix(content)
    content = strip_between_markers(content, METHOD_START, METHOD_END)
    content = strip_between_markers(content, EXPERIMENT_START, EXPERIMENT_END)
    if method_caption:
        content = replace_method_section(content, make_method_block(method_caption, analysis_path))
    if experiment_captions:
        content = replace_experiment_section(content, make_experiment_block(experiment_captions, analysis_path))

    analysis_path.write_text(content.rstrip() + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inline key PDF artifacts into analysis Markdown.")
    parser.add_argument("--root", type=Path, default=ROOT_DIR, help="PaperReading root directory.")
    parser.add_argument("--run-dir", type=Path, default=None, help="Run directory. Default: latest under runs/.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    run_dir = args.run_dir.resolve() if args.run_dir else find_latest_run_dir(root)
    analyses_dir = run_dir / "analyses"
    artifacts_dir = run_dir / "artifacts"

    processed = 0
    for analysis_path in sorted(analyses_dir.glob("*.md")):
        arxiv_id = arxiv_id_from_path(analysis_path)
        artifact_path = artifacts_dir / f"{arxiv_id}_artifacts.json"
        if not artifact_path.exists():
            print(f"Skip {analysis_path.name}: artifact JSON not found")
            continue
        process_analysis(analysis_path, artifact_path)
        processed += 1
        print(f"Updated {analysis_path.name}")

    print(f"Processed analyses: {processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
