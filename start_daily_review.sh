#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
RUNS_DIR="$ROOT_DIR/runs"
RUN_DATE="$("$PYTHON_BIN" - <<'PY'
from datetime import date
print(date.today().isoformat())
PY
)"
START_DATE="$("$PYTHON_BIN" - "$ROOT_DIR" "$RUN_DATE" <<'PY'
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

runs_dir = Path(sys.argv[1]) / "runs"
today = date.fromisoformat(sys.argv[2])
run_dates = []
covered_dates = []
if runs_dir.exists():
    for child in runs_dir.iterdir():
        if child.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", child.name):
            run_dates.append(date.fromisoformat(child.name))
            for json_path in child.glob("cs_ro_papers_*.json"):
                try:
                    payload = json.loads(json_path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                end_value = payload.get("arxiv_end_date") or payload.get("target_date")
                if isinstance(end_value, str):
                    match = re.search(r"(\d{4}-\d{2}-\d{2})$", end_value)
                    if match:
                        covered_dates.append(date.fromisoformat(match.group(1)))

if covered_dates:
    candidate = max(covered_dates) + timedelta(days=1)
    print(min(candidate, today).isoformat())
elif not run_dates:
    print(today.isoformat())
else:
    candidate = max(run_dates) + timedelta(days=1)
    print(min(candidate, today).isoformat())
PY
)"
RUN_DIR="$RUNS_DIR/$RUN_DATE"

mkdir -p "$RUN_DIR" "$ROOT_DIR/tmp"

echo "Run date:    $RUN_DATE"
echo "Start date:  $START_DATE"
echo "Output dir:  $RUN_DIR"

"$PYTHON_BIN" "$ROOT_DIR/scripts/arxiv_cs_ro_today.py" \
  --start-date "$START_DATE" \
  --run-date "$RUN_DATE" \
  --output-dir "$RUN_DIR"

SCRAPED_JSON="$("$PYTHON_BIN" - "$RUN_DIR" <<'PY'
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])
matches = sorted(
    run_dir.glob("cs_ro_papers_*.json"),
    key=lambda path: (path.stat().st_mtime, path.name),
)
if not matches:
    raise SystemExit(f"No cs_ro_papers_*.json found in {run_dir}")
print(matches[-1])
PY
)"

"$PYTHON_BIN" "$ROOT_DIR/scripts/prepare_llm_filter_task.py" "$SCRAPED_JSON" --root "$ROOT_DIR"

TASK_PATH="$("$PYTHON_BIN" - "$RUN_DIR" <<'PY'
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])
matches = sorted(
    run_dir.glob("llm_filter_task_*.md"),
    key=lambda path: (path.stat().st_mtime, path.name),
)
if not matches:
    raise SystemExit(f"No llm_filter_task_*.md found in {run_dir}")
print(matches[-1])
PY
)"

echo
echo "Next step:"
echo "Ask Codex to complete the LLM-in-the-loop filtering task:"
echo "$TASK_PATH"
echo
echo "After Codex generates the selector HTML, run:"
echo "./serve_selector.sh --run-dir \"$RUN_DIR\""
