#!/usr/bin/env python3
"""Remove disposable PaperReading artifacts without touching reading outputs."""

import argparse
import shutil
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Set


TMP_PATTERNS = [
    "arxiv_html_*",
    "arxiv_src_*",
    "pdf_text",
    "pdf-overflow-check",
    "latex-test",
    "docling_probe",
    "pycache",
]
LATEX_AUX_PATTERNS = [
    "*.aux",
    "*.log",
    "*.out",
    "*.toc",
    "*.fls",
    "*.fdb_latexmk",
    "*.xdv",
    "*.synctex.gz",
]


@dataclass(frozen=True)
class CleanupTarget:
    path: Path
    reason: str


def unique_targets(targets: Iterable[CleanupTarget]) -> List[CleanupTarget]:
    seen = set()
    unique: List[CleanupTarget] = []
    for target in targets:
        key = target.path.resolve()
        if key in seen:
            continue
        seen.add(key)
        unique.append(target)
    return sorted(unique, key=lambda item: str(item.path))


def run_age_cutoff(days: int) -> date:
    return datetime.now(timezone.utc).date() - timedelta(days=days)


def run_date_for(run_dir: Path) -> date | None:
    try:
        return date.fromisoformat(run_dir.name)
    except ValueError:
        return None


def referenced_analysis_assets(run_dir: Path) -> Set[str]:
    analyses_dir = run_dir / "analyses"
    if not analyses_dir.exists():
        return set()
    text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in analyses_dir.glob("*.md"))
    references = set()
    for asset_dir_name in ("figures", "tables"):
        asset_dir = run_dir / asset_dir_name
        if not asset_dir.exists():
            continue
        for path in asset_dir.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(run_dir).as_posix()
            if rel in text or path.name in text:
                references.add(rel)
    return references


def collect_unused_analysis_assets(runs_dir: Path, days: int) -> List[CleanupTarget]:
    cutoff = run_age_cutoff(days)
    targets: List[CleanupTarget] = []
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        parsed_date = run_date_for(run_dir)
        if parsed_date is not None and parsed_date >= cutoff:
            continue
        if not any((run_dir / "analyses").glob("*.md")):
            continue
        references = referenced_analysis_assets(run_dir)
        for asset_dir_name in ("figures", "tables"):
            asset_dir = run_dir / asset_dir_name
            if not asset_dir.exists():
                continue
            for path in asset_dir.rglob("*"):
                if not path.is_file():
                    continue
                if path.relative_to(run_dir).as_posix() in references:
                    continue
                if parsed_date is None:
                    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date()
                    if mtime >= cutoff:
                        continue
                targets.append(CleanupTarget(path, f"unused-{asset_dir_name}:{days}d"))
    return targets


def collect_targets(root: Path, backup_days: int, unused_artifact_days: int, include_model_cache: bool) -> List[CleanupTarget]:
    targets: List[CleanupTarget] = []
    tmp_dir = root / "tmp"
    if tmp_dir.exists():
        for pattern in TMP_PATTERNS:
            targets.extend(CleanupTarget(path, f"tmp:{pattern}") for path in tmp_dir.glob(pattern))
        if include_model_cache:
            targets.extend(CleanupTarget(path, "tmp:model-cache") for path in tmp_dir.glob("docling_models"))

    runs_dir = root / "runs"
    if runs_dir.exists():
        for pattern in LATEX_AUX_PATTERNS:
            targets.extend(CleanupTarget(path, f"latex-aux:{pattern}") for path in runs_dir.rglob(pattern))

        cutoff = datetime.now(timezone.utc) - timedelta(days=backup_days)
        for path in runs_dir.rglob("paper_cn.before_notes_*.pdf"):
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                targets.append(CleanupTarget(path, f"old-note-backup:{backup_days}d"))

        targets.extend(collect_unused_analysis_assets(runs_dir, unused_artifact_days))

    return unique_targets(targets)


def remove_target(target: CleanupTarget) -> None:
    if target.path.is_dir():
        shutil.rmtree(target.path)
    else:
        target.path.unlink()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean disposable PaperReading artifacts.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project root. Default: current directory.")
    parser.add_argument("--apply", action="store_true", help="Actually delete files. Default only prints the plan.")
    parser.add_argument(
        "--backup-days",
        type=int,
        default=30,
        help="Delete paper_cn.before_notes_*.pdf backups older than this many days. Default: 30.",
    )
    parser.add_argument(
        "--unused-artifact-days",
        type=int,
        default=30,
        help="Delete unreferenced runs/*/figures and runs/*/tables files from runs older than this many days. Default: 30.",
    )
    parser.add_argument(
        "--include-model-cache",
        action="store_true",
        help="Also remove tmp/docling_models. This may require re-downloading models later.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    targets = collect_targets(root, args.backup_days, args.unused_artifact_days, args.include_model_cache)
    action = "DELETE" if args.apply else "DRY-RUN"

    if not targets:
        print("No cleanup targets found.")
        return 0

    for target in targets:
        rel = target.path.relative_to(root) if target.path.is_relative_to(root) else target.path
        print(f"{action}\t{target.reason}\t{rel}")
        if args.apply:
            remove_target(target)

    print(f"{action} complete: {len(targets)} target(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
