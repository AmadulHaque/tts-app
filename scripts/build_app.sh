#!/usr/bin/env bash
# Build 'Kokoro Studio' into a macOS .app bundle with PyInstaller.
#
#   ./scripts/build_app.sh
#
# The result lands in  dist/Kokoro Studio.app.
# NOTE: bundling torch is slow and produces a several-GB app. Run once, offline
# afterwards. Install with `uv pip install -e '.[dev]'` first.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"

PY="${PROJECT_ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
    echo "-> creating venv and installing dependencies (first run is slow)…"
    uv venv .venv --python 3.12
    UV_PYTHON=.venv/bin/python uv pip install -e '.[dev]'
fi
# Ensure PyInstaller + runtime deps are present even if the venv predates the dev extra.
UV_PYTHON=.venv/bin/python uv pip install --upgrade -e '.[dev]' pyinstaller || true

echo "-> building with PyInstaller (this can take several minutes)…"
UV_PYTHON=.venv/bin/python "${PY}" -m PyInstaller --clean --noconfirm kokoro-studio.spec

echo
echo "Done. App bundle:"
ls -d "${PROJECT_ROOT}"/dist/*.app 2>/dev/null || ls -R "${PROJECT_ROOT}"/dist
echo
echo "Launch it with:  open '${PROJECT_ROOT}/dist/Kokoro Studio.app'"
