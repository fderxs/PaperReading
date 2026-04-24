#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SELECTOR_PORT="${SELECTOR_PORT:-8765}"
RUN_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-dir)
      RUN_DIR="$2"
      shift 2
      ;;
    --port)
      SELECTOR_PORT="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$RUN_DIR" ]]; then
  RUN_DIR="$("$PYTHON_BIN" - "$ROOT_DIR" <<'PY'
import re
import sys
from pathlib import Path

runs_dir = Path(sys.argv[1]) / "runs"
dirs = [
    child
    for child in runs_dir.iterdir()
    if child.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", child.name)
]
if not dirs:
    raise SystemExit("No run directory found under runs/.")
print(max(dirs, key=lambda path: path.name))
PY
)"
fi

HTML_PATH="$("$PYTHON_BIN" - "$RUN_DIR" <<'PY'
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])
matches = sorted(
    run_dir.glob("vla_planning_selector_*.html"),
    key=lambda path: (path.stat().st_mtime, path.name),
)
if not matches:
    raise SystemExit(
        f"No selector HTML found in {run_dir}. Ask Codex to complete the llm_filter_task first."
    )
print(matches[-1])
PY
)"

HTML_NAME="$(basename "$HTML_PATH")"

echo "Selector URL:"
echo "http://127.0.0.1:$SELECTOR_PORT/$HTML_NAME"
echo
echo "Keep this terminal open while selecting papers. Press Ctrl-C after saving."

"$PYTHON_BIN" "$ROOT_DIR/scripts/selector_server.py" \
  --run-dir "$RUN_DIR" \
  --host 127.0.0.1 \
  --port "$SELECTOR_PORT"
