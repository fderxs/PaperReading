#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/Users/fderxs/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"

"$PYTHON_BIN" "$ROOT_DIR/scripts/extract_pdf_artifacts.py" --root "$ROOT_DIR" "$@"
