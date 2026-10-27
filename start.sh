#!/usr/bin/env bash
# start.sh — convenience launcher for DeepSeek Agent.
#
# Usage:
#   ./start.sh                        # interactive mode
#   ./start.sh "build a REST API"     # run a single task
#   ./start.sh --headless "task"      # any deepseek-agent flag works
#
# Can be run from any directory — the task's working directory defaults to
# wherever you call this script from (just like running `deepseek-agent` directly).
set -euo pipefail

# Resolve this script's own directory, even if called via a symlink.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"

if ! command -v uv >/dev/null 2>&1; then
    echo "[start.sh] 'uv' is not installed." >&2
    echo "           Install it from https://docs.astral.sh/uv/ and try again." >&2
    exit 1
fi

# First-time setup: create the virtual environment and download the
# Playwright Chromium browser (only happens once).
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "[start.sh] First run — setting up the virtual environment..."
    uv sync --project "$SCRIPT_DIR"

    echo "[start.sh] Downloading Playwright's Chromium browser (one time, ~150 MB)..."
    uv run --project "$SCRIPT_DIR" playwright install chromium
fi

exec uv run --project "$SCRIPT_DIR" deepseek-agent "$@"
