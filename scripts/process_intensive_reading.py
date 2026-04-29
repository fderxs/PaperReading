#!/usr/bin/env python3
"""Prepare full-paper translation work for papers marked as intensive reading."""

import argparse
import gzip
import json
import os
import re
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List
from urllib.request import Request, urlopen


USER_AGENT = "paperreading-intensive/1.0 (+https://arxiv.org)"
ROOT_DIR = Path(__file__).resolve().parent.parent


def find_latest_run_dir(root: Path) -> Path:
    runs_dir = root / "runs"
    dirs = [
        child
        for child in runs_dir.iterdir()
        if child.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", child.name)
    ]
    if not dirs:
        raise FileNotFoundError("No YYYY-MM-DD run directory found under runs/.")
    return max(dirs, key=lambda path: path.name)


def find_latest_manifest(run_dir: Path) -> Path:
    matches = sorted(
        run_dir.glob("reading_manifest_*.json"),
        key=lambda path: (path.stat().st_mtime, path.name),
    )
    if not matches:
        raise FileNotFoundError(f"No reading_manifest_*.json found in {run_dir}")
    return matches[-1]


def arxiv_scope_from_manifest(path: Path) -> str:
    return path.name.removeprefix("reading_manifest_").removesuffix(".json")


def load_json(path: Path) -> Dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")


def safe_extract_tar(archive: tarfile.TarFile, output_dir: Path) -> None:
    output_root = output_dir.resolve()
    for member in archive.getmembers():
        member_path = (output_dir / member.name).resolve()
        if not str(member_path).startswith(str(output_root) + os.sep) and member_path != output_root:
            raise RuntimeError(f"Unsafe path in arXiv source archive: {member.name}")
    archive.extractall(output_dir)


def copytree_clean(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def read_status(run_dir: Path, arxiv_scope: str) -> Dict[str, Dict[str, object]]:
    status_path = run_dir / f"reading_status_{arxiv_scope}.json"
    if not status_path.exists():
        return {}
    payload = load_json(status_path)
    status: Dict[str, Dict[str, object]] = {}
    for item in payload.get("read_papers", []):
        if isinstance(item, dict) and item.get("reading_id"):
            status[str(item["reading_id"])] = item
    return status


def intensive_papers(manifest: Dict[str, object], status: Dict[str, Dict[str, object]]) -> List[Dict[str, object]]:
    papers = []
    for paper in manifest.get("papers", []):
        if not isinstance(paper, dict):
            continue
        paper_status = status.get(str(paper.get("reading_id", "")), {})
        if paper_status.get("intensive"):
            merged = dict(paper)
            merged["intensive_at"] = str(paper_status.get("intensive_at") or "")
            merged["read"] = bool(paper_status.get("read"))
            merged["read_at"] = str(paper_status.get("read_at") or "")
            papers.append(merged)
    return papers


def rewrite_intensive_preferences(root: Path, run_date: str, arxiv_scope: str, papers: Iterable[Dict[str, object]]) -> Path:
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
                and item.get("arxiv_date") == arxiv_scope
                and item.get("preference_stage") == "intensive_translation"
            ):
                continue
            existing.append(item)

    now = datetime.now(timezone.utc).isoformat()
    intensive_records = []
    for paper in papers:
        intensive_records.append(
            {
                "recorded_at": now,
                "run_date": run_date,
                "arxiv_date": arxiv_scope,
                "preference_stage": "intensive_translation",
                "decision": "intensive",
                "reading_id": paper.get("reading_id", ""),
                "selector_id": paper.get("selector_id", ""),
                "arxiv_id": paper.get("arxiv_id", ""),
                "title": paper.get("title", ""),
                "priority": paper.get("priority", ""),
                "tags": paper.get("tags", []),
                "intensive_at": paper.get("intensive_at", ""),
                "reason": "Marked for full Chinese translation in reading dashboard.",
            }
        )

    path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in existing + intensive_records),
        encoding="utf-8",
    )
    return path


def download_arxiv_source(arxiv_id: str, archive_path: Path, timeout: int) -> Path:
    if archive_path.exists() and archive_path.stat().st_size > 0:
        return archive_path
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    request = Request(
        f"https://arxiv.org/e-print/{arxiv_id}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/eprint,application/octet-stream,*/*;q=0.1"},
    )
    with urlopen(request, timeout=timeout) as response:
        data = response.read()
    with tempfile.NamedTemporaryFile("wb", dir=archive_path.parent, prefix=".source_", suffix=".tmp", delete=False) as handle:
        temp_path = Path(handle.name)
        handle.write(data)
    os.replace(temp_path, archive_path)
    return archive_path


def unpack_source(archive_path: Path, output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if tarfile.is_tarfile(archive_path):
        with tarfile.open(archive_path) as archive:
            safe_extract_tar(archive, output_dir)
        return

    raw = archive_path.read_bytes()
    try:
        decoded = gzip.decompress(raw)
        (output_dir / "main.tex").write_bytes(decoded)
    except OSError:
        (output_dir / "main.tex").write_bytes(raw)


def detect_latex_tools() -> List[str]:
    candidates = ["latexmk", "xelatex", "lualatex", "pdflatex", "tectonic"]
    extra_paths = [
        str(Path.home() / ".local" / "bin"),
        str(Path.home() / "Library" / "TinyTeX" / "bin" / "universal-darwin"),
    ]
    search_path = os.pathsep.join(extra_paths + [os.environ.get("PATH", "")])
    return [tool for tool in candidates if shutil.which(tool, path=search_path)]


def write_compile_script(work_dir: Path, tools: List[str]) -> Path:
    script_path = work_dir / "compile_cn.sh"
    preferred = tools[0] if tools else "latexmk"
    script_path.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
export PATH="$HOME/.local/bin:$HOME/Library/TinyTeX/bin/universal-darwin:$PATH"
cd "$(dirname "$0")/source_cn"

main_tex="${{1:-}}"
if [[ -z "$main_tex" ]]; then
  main_tex="$(find . -maxdepth 2 -name '*.tex' | sort | head -n 1)"
fi

if [[ -z "$main_tex" ]]; then
  echo "No .tex file found under source_cn" >&2
  exit 2
fi

if command -v latexmk >/dev/null 2>&1; then
  latexmk -xelatex -interaction=nonstopmode -file-line-error "$main_tex"
elif command -v xelatex >/dev/null 2>&1; then
  xelatex -interaction=nonstopmode -file-line-error "$main_tex"
  xelatex -interaction=nonstopmode -file-line-error "$main_tex"
elif command -v tectonic >/dev/null 2>&1; then
  tectonic "$main_tex"
else
  echo "No LaTeX compiler found. Install MacTeX or tectonic, then rerun this script." >&2
  echo "Expected tool, based on current detection: {preferred}" >&2
  exit 3
fi

base="${{main_tex%.tex}}"
log="${{base}}.log"
if [[ -f "$log" ]] && grep -q "Overfull \\\\hbox" "$log"; then
  echo "PDF compiled, but LaTeX reported overfull lines in $log." >&2
  echo "Fix these before accepting paper_cn.pdf; common causes are long Chinese text inside \\\\uline{...}, unbreakable URLs, long English tokens, or oversized tables." >&2
  grep -n -A2 -B1 "Overfull \\\\hbox" "$log" >&2 || true
  exit 4
fi

pdf="${base}.pdf"
if [[ ! -f "$pdf" ]]; then
  pdf="$(find . -maxdepth 1 -name '*.pdf' | sort | head -n 1)"
fi
if [[ -n "$pdf" ]]; then
  cp "$pdf" ../paper_cn.pdf
  echo "Wrote ../paper_cn.pdf"
  run_dir="$(cd ../../.. && pwd)"
  root_dir="$(cd ../../../../.. && pwd)"
  manifest="$(find "$run_dir" -maxdepth 1 -name 'reading_manifest_*.json' | sort | tail -n 1)"
  if [[ -n "$manifest" && -f "$root_dir/scripts/render_reading_dashboard.py" ]]; then
    python3 "$root_dir/scripts/render_reading_dashboard.py" --refresh-manifest "$manifest"
  fi
fi
""",
        encoding="utf-8",
    )
    script_path.chmod(0o755)
    return script_path


def write_translation_task(work_dir: Path, paper: Dict[str, object], tools: List[str]) -> Path:
    task_path = work_dir / "TRANSLATION_TASK.md"
    task_path.write_text(
        f"""# 中文全文翻译任务：{paper.get('reading_id')} / {paper.get('arxiv_id')}

标题：{paper.get('title', '')}

## 目录

- 原始 arXiv 源码：`source_original/`
- 待翻译源码：`source_cn/`
- 编译脚本：`compile_cn.sh`
- 目标 PDF：`paper_cn.pdf`

## 翻译要求

1. 以 `source_cn/` 为唯一编辑目录，不要改 `source_original/`。
2. 英文正文、标题、章节名、图注、表注、必要的算法/代码注释翻译成中文。
3. 数学公式、引用 key、label、ref、cite、url、文件路径、宏定义结构保持可编译。
4. 人名、机构名、数据集名、方法专名在必要时保留英文，可在首次出现处加中文解释。
5. 表格和图片内容不强制逐字翻译，只翻译 caption 和读者理解所需的文字。
6. 翻译完成后运行 `./compile_cn.sh`，确认生成 `paper_cn.pdf`。
7. 编译失败时优先修复 LaTeX 语法，不要删除关键内容来绕过错误。
8. 最后检查所有 `.tex` 文件，确认没有明显漏翻的长英文段落。
9. 如果需要加入 `ctex`/中文字体支持，优先使用 TinyTeX 自带字体，例如 `\\documentclass[UTF8,fontset=fandol]{{ctexart}}` 或 `\\usepackage[fontset=fandol]{{ctex}}`，避免依赖系统字体。
10. 不要用 `\\uline{{...}}` 包裹中文长句或整段中文；`ulem` 对中文断行不可靠，容易造成文字超出页面。需要强调时优先用 `\\textbf{{...}}`，短词级别下划线才可使用 `\\uline`。
11. 编译后必须检查日志中是否有 `Overfull \\hbox`。生成的 `compile_cn.sh` 会把这类问题作为失败处理；修复后再重新编译。

## LaTeX 环境

检测到的编译工具：{', '.join(tools) if tools else '未检测到；建议安装 MacTeX 或 tectonic'}
""",
        encoding="utf-8",
    )
    return task_path


def prepare_translation_workspace(root: Path, run_dir: Path, paper: Dict[str, object], timeout: int, download_source: bool) -> Dict[str, str]:
    reading_id = str(paper.get("reading_id", "RXX"))
    arxiv_id = str(paper.get("arxiv_id", "unknown"))
    work_dir = run_dir / "paper_cn" / f"{reading_id}_{safe_name(arxiv_id)}"
    archive_path = work_dir / "source_archive"
    source_original = work_dir / "source_original"
    source_cn = work_dir / "source_cn"
    work_dir.mkdir(parents=True, exist_ok=True)

    if download_source:
        download_arxiv_source(arxiv_id, archive_path, timeout=timeout)
        unpack_source(archive_path, source_original)
        copytree_clean(source_original, source_cn)
    else:
        source_original.mkdir(exist_ok=True)
        source_cn.mkdir(exist_ok=True)

    tools = detect_latex_tools()
    compile_script = write_compile_script(work_dir, tools)
    task_path = write_translation_task(work_dir, paper, tools)
    return {
        "reading_id": reading_id,
        "arxiv_id": arxiv_id,
        "work_dir": str(work_dir),
        "source_original": str(source_original),
        "source_cn": str(source_cn),
        "translation_task": str(task_path),
        "compile_script": str(compile_script),
        "paper_cn_pdf": str(work_dir / "paper_cn.pdf"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare full Chinese translation workspaces for intensive papers.")
    parser.add_argument("--root", type=Path, default=ROOT_DIR, help="PaperReading root directory.")
    parser.add_argument("--run-dir", type=Path, default=None, help="Run folder. Default: latest YYYY-MM-DD folder.")
    parser.add_argument("--manifest", type=Path, default=None, help="Reading manifest path. Default: latest in run folder.")
    parser.add_argument("--timeout", type=int, default=120, help="arXiv source download timeout.")
    parser.add_argument("--no-download-source", action="store_true", help="Only write task folders; do not fetch arXiv source.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    run_dir = args.run_dir.resolve() if args.run_dir else find_latest_run_dir(root)
    manifest_path = args.manifest.resolve() if args.manifest else find_latest_manifest(run_dir)
    arxiv_scope = arxiv_scope_from_manifest(manifest_path)
    manifest = load_json(manifest_path)
    status = read_status(run_dir, arxiv_scope)
    papers = intensive_papers(manifest, status)

    preference_path = rewrite_intensive_preferences(root, str(manifest.get("run_date") or run_dir.name), arxiv_scope, papers)
    outputs = [
        prepare_translation_workspace(root, run_dir, paper, args.timeout, not args.no_download_source)
        for paper in papers
    ]

    task_path = run_dir / f"llm_intensive_translation_task_{arxiv_scope}.md"
    lines = [
        f"# 精读论文中文全文翻译任务：{arxiv_scope}",
        "",
        f"- 阅读 manifest：`{manifest_path}`",
        f"- 阅读状态：`{run_dir / f'reading_status_{arxiv_scope}.json'}`",
        f"- 偏好记录：`{preference_path}`",
        f"- 精读论文数：{len(outputs)}",
        "",
        "## 论文",
        "",
    ]
    for output in outputs:
        lines.extend(
            [
                f"### {output['reading_id']} / {output['arxiv_id']}",
                "",
                f"- 工作目录：`{output['work_dir']}`",
                f"- 翻译任务：`{output['translation_task']}`",
                f"- 编译脚本：`{output['compile_script']}`",
                f"- 目标中文 PDF：`{output['paper_cn_pdf']}`",
                "",
            ]
        )
    task_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"Run dir: {run_dir}")
    print(f"Manifest: {manifest_path}")
    print(f"Intensive papers: {len(outputs)}")
    print(f"Preference records updated: {preference_path}")
    print(f"Translation task: {task_path}")
    for output in outputs:
        print(f"- {output['reading_id']} {output['arxiv_id']}: {output['work_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
