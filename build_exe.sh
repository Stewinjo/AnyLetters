#!/usr/bin/env bash
set -euo pipefail
# Build AnyLetters as a single-file executable (macOS/Linux)
# Requires: pip install -r requirements.txt (pyinstaller)
#
# The AnyLetters.spec file includes:
#   - solutions/ folder (solutions/<lang><length>.txt)
#   - dictionaries submodule (external/dictionaries/dictionaries/<lang>/*.dic and *.aff)

NAME=AnyLetters

echo "Building $NAME..."
echo "Using spec file: AnyLetters.spec"
echo "(All data files are included automatically by the spec file)"
echo ""

pyinstaller --noconfirm --clean AnyLetters.spec

if [ $? -ne 0 ]; then
  echo ""
  echo "Build failed!"
  exit 1
fi

echo "Testing executable..."
if [ ! -f "dist/$NAME" ]; then
  echo "ERROR: Executable not found!"
  exit 1
fi

echo "Testing --list argument..."
set +e
TMP_OUTPUT="$(mktemp)"
if command -v timeout >/dev/null 2>&1; then
  timeout 5s dist/$NAME --list >"$TMP_OUTPUT" 2>&1
  EXIT=$?
fi
set -e

if [ "${EXIT:-1}" -eq 0 ]; then
  echo "[OK] --list argument works (exited immediately)"
else
  echo "ERROR: --list test failed (exit code: ${EXIT:-1})"
  echo "----- command output -----"
  cat "$TMP_OUTPUT"
  echo "--------------------------"
  rm -f "$TMP_OUTPUT"
  exit 1
fi
rm -f "$TMP_OUTPUT"
