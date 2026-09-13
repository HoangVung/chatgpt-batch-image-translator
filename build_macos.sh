#!/usr/bin/env bash
set -euo pipefail

APP_NAME="ChatGPT Batch Translator"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_APP="$ROOT/dist/$APP_NAME.app"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$ROOT"

"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 9) else 1)'
"$PYTHON_BIN" -c 'import tkinter; tkinter.Tcl().eval("info patchlevel")'
"$PYTHON_BIN" -m pip install --upgrade pip
"$PYTHON_BIN" -m pip install -r requirements.txt

rm -rf "$ROOT/build" "$DIST_APP"

"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --clean \
  --onedir \
  --windowed \
  --name "$APP_NAME" \
  --collect-all playwright \
  --hidden-import run_chatgpt_batch \
  app.pyw

if [[ ! -d "$DIST_APP" ]]; then
  echo "PyInstaller did not create the application bundle." >&2
  exit 1
fi

BROWSER_DIR="$DIST_APP/Contents/MacOS/ms-playwright"
PLAYWRIGHT_BROWSERS_PATH="$BROWSER_DIR" "$PYTHON_BIN" -m playwright install chromium

if ! find "$BROWSER_DIR" -type f \( -name 'Chromium' -o -name 'chrome' \) | grep -q .; then
  echo "Playwright Chromium was not installed into the application bundle." >&2
  exit 1
fi

echo "DONE"
echo "Application: $DIST_APP"
