#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
PORT="${SELECTOR_PORT:-8765}"
RUN_DIR=""
OPEN_BROWSER=1

usage() {
  cat <<'USAGE'
Usage: ./start_dashboard.sh [--run-dir runs/YYYY-MM-DD] [--port PORT] [--no-open]

Start the global PaperReading dashboard server.

Options:
  --run-dir PATH   Active run directory for saving reading/selection state.
                   Defaults to the latest runs/YYYY-MM-DD directory.
  --port PORT      Preferred port. If occupied, the script picks the next free port.
                   Defaults to SELECTOR_PORT or 8765.
  --no-open        Do not open the browser automatically.
  -h, --help       Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-dir)
      RUN_DIR="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --no-open)
      OPEN_BROWSER=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

RUN_DIR="$("$PYTHON_BIN" - "$ROOT_DIR" "$RUN_DIR" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
requested = sys.argv[2].strip()

if requested:
    run_dir = Path(requested)
    if not run_dir.is_absolute():
        run_dir = root / run_dir
    if not run_dir.exists() or not run_dir.is_dir():
        raise SystemExit(f"Run directory not found: {run_dir}")
    print(run_dir)
    raise SystemExit

runs_dir = root / "runs"
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

DASHBOARD_PATH="$ROOT_DIR/dashboard/reading_dashboard.html"
if [[ ! -f "$DASHBOARD_PATH" ]]; then
  echo "No global dashboard found at: $DASHBOARD_PATH" >&2
  echo "Render it first with the daily workflow or process_selected_papers.sh." >&2
  exit 1
fi

PORT="$("$PYTHON_BIN" - "$PORT" <<'PY'
import socket
import sys

start = int(sys.argv[1])
for port in range(start, start + 100):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            continue
        print(port)
        break
else:
    raise SystemExit(f"No free port found in range {start}-{start + 99}.")
PY
)"

URL="http://127.0.0.1:$PORT/dashboard/reading_dashboard.html"

echo "PaperReading dashboard:"
echo "$URL"
echo
echo "Active run dir: $RUN_DIR"
echo "Press Ctrl-C to stop the dashboard server."
echo

if [[ "$OPEN_BROWSER" == "1" ]]; then
  if command -v open >/dev/null 2>&1; then
    (sleep 1; open "$URL" >/dev/null 2>&1 || true) &
  elif command -v xdg-open >/dev/null 2>&1; then
    (sleep 1; xdg-open "$URL" >/dev/null 2>&1 || true) &
  fi
fi

exec "$PYTHON_BIN" "$ROOT_DIR/scripts/selector_server.py" \
  --run-dir "$RUN_DIR" \
  --host 127.0.0.1 \
  --port "$PORT"
