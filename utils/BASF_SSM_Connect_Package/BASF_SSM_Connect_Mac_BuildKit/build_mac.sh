#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "== BASF SSM Connect - macOS build =="

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 not found."
  echo "Install it from https://www.python.org/downloads/macos/ and re-run this script."
  exit 1
fi

if ! python3 -c "import tkinter" >/dev/null 2>&1; then
  echo "python3's tkinter module is missing."
  echo "If this Python came from python.org, tkinter should already be included - try reinstalling it."
  echo "If this Python came from Homebrew, run: brew install python-tk"
  exit 1
fi

echo "Creating a throwaway virtual environment (.buildenv)..."
python3 -m venv .buildenv
source .buildenv/bin/activate

pip install --upgrade pip >/dev/null
pip install pyinstaller

rm -rf build dist BASF_SSM_Connect.spec

pyinstaller --onefile --windowed --name BASF_SSM_Connect basf_ssm_connect.py

deactivate

echo ""
echo "================================================================"
echo "Build complete: dist/BASF_SSM_Connect.app"
echo ""
echo "First run (the app isn't code-signed, so Gatekeeper will block it once):"
echo "  Right-click dist/BASF_SSM_Connect.app -> Open -> Open"
echo "or from Terminal:"
echo "  xattr -cr dist/BASF_SSM_Connect.app"
echo "================================================================"
