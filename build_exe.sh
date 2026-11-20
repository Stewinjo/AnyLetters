#!/usr/bin/env bash
set -euo pipefail
# Build AnyLetters as a single-file executable (macOS/Linux)
# Requires: pip install -r requirements.txt (pyinstaller)
#
# Optional bake flags (forwarded to bake_defaults.py):
#   --lang de --length 6 --difficulty easy --require-solutions
#   --exe-name AnyLettersDE --disable-solution-filters
#
# The AnyLetters.spec file includes:
#   - defaults.json (baked CLI defaults)
#   - solutions/ folder (solutions/<lang><length>.txt)
#   - dictionaries submodule
#   - filters/

echo "Baking defaults (if any bake flags were provided)..."
python bake_defaults.py "$@"

NAME="$(python -c "import json; print(json.load(open('defaults.json', encoding='utf-8')).get('exe_name', 'AnyLetters') or 'AnyLetters')")"

echo "Building $NAME..."
echo "Using spec file: AnyLetters.spec"
echo "(All data files are included automatically by the spec file)"
echo ""

pyinstaller --noconfirm --clean AnyLetters.spec

echo "Testing executable..."
if [ ! -f "dist/$NAME" ]; then
  echo "ERROR: Executable not found!"
  exit 1
fi

echo "Testing --list argument..."
set +e
TMP_OUTPUT="$(mktemp)"
# Python's timeout works on macOS, where the timeout(1) command is often absent.
python -c "import subprocess, sys
cmd = ['dist/${NAME}', '--list']
try:
    result = subprocess.run(cmd, timeout=5, capture_output=True)
except subprocess.TimeoutExpired as exc:
    sys.stdout.buffer.write(exc.stdout or b'')
    sys.stderr.buffer.write(exc.stderr or b'')
    sys.exit(124)
sys.stdout.buffer.write(result.stdout)
sys.stderr.buffer.write(result.stderr)
sys.exit(result.returncode)" >"$TMP_OUTPUT" 2>&1
EXIT=$?
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

echo "Testing baked defaults via --help..."
HELP_OUTPUT="$(mktemp)"
"dist/$NAME" --help >"$HELP_OUTPUT" 2>&1 || true
if grep -q "default:" "$HELP_OUTPUT"; then
  echo "[OK] --help shows defaults"
else
  echo "WARNING: could not confirm baked defaults in --help output"
fi
rm -f "$HELP_OUTPUT"
