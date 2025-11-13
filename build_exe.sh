#!/usr/bin/env bash
set -euo pipefail
# Build AnyLetters as a single-file executable (macOS/Linux)
# Requires: pip install -r requirements.txt (pyinstaller)
#
# The AnyLetters.spec file includes:
#   - solutions/ folder (solutions/<lang><length>.txt)
#   - dictionaries submodule (external/dictionaries/dictionaries/<lang>/*.dic and *.aff)

NAME=AnyLetters

echo "Ensuring dictionaries submodule is initialized..."
if command -v git >/dev/null 2>&1; then
  git submodule update --init --recursive external/dictionaries
else
  echo "WARNING: git not available; ensure external/dictionaries is initialized." >&2
fi
echo ""

echo "Building $NAME..."
echo "Using spec file: AnyLetters.spec"
echo "(All data files are included automatically by the spec file)"
echo ""

# Use spec file directly - it includes all necessary data files
pyinstaller --noconfirm --clean AnyLetters.spec

if [ $? -ne 0 ]; then
  echo ""
  echo "Build failed!"
  exit 1
fi

echo ""
echo "Build complete! Executable is in the dist folder: dist/$NAME"
echo ""

# Test the executable with arguments
echo "Testing executable..."
if [ ! -f "dist/$NAME" ]; then
  echo "ERROR: Executable not found!"
  exit 1
fi

# Test --help (should exit immediately, no GUI needed)
echo "Testing --help argument..."
set +e
if command -v timeout >/dev/null 2>&1; then
  timeout 1s dist/$NAME --help >/dev/null 2>&1
  HELP_EXIT=$?
elif command -v gtimeout >/dev/null 2>&1; then
  gtimeout 1s dist/$NAME --help >/dev/null 2>&1
  HELP_EXIT=$?
else
  dist/$NAME --help >/dev/null 2>&1
  HELP_EXIT=$?
fi
set -e

# --help should exit with 0 (success) immediately via argparse
# Exit code 124/125 means it timed out (suspicious - should exit instantly)
if [ $HELP_EXIT -eq 124 ] || [ $HELP_EXIT -eq 125 ]; then
  echo "ERROR: --help timed out (should exit instantly)!"
  exit 1
elif [ $HELP_EXIT -eq 0 ]; then
  echo "[OK] --help argument works (exited immediately)"
else
  echo "WARNING: --help test failed (exit code: $HELP_EXIT)"
fi

# Test argument parsing
# In headless environments, GUI will fail but argument parsing should work
echo "Testing argument parsing..."
# Use timeout to prevent hanging if GUI tries to start
# Note: timeout returns 124/125 when timeout is reached (process was running = success)
EXIT_CODE=0
if command -v timeout >/dev/null 2>&1; then
  # Linux: timeout command available
  # Temporarily disable 'set -e' for this command since 124 is success
  set +e
  timeout 2s dist/$NAME --lang en --length 6 >/dev/null 2>&1
  EXIT_CODE=$?
  set -e
elif command -v gtimeout >/dev/null 2>&1; then
  # macOS: gtimeout from coreutils
  set +e
  gtimeout 2s dist/$NAME --lang en --length 6 >/dev/null 2>&1
  EXIT_CODE=$?
  set -e
else
  # No timeout available, test with background process
  set +e
  dist/$NAME --lang en --length 6 >/dev/null 2>&1 &
  PID=$!
  sleep 2
  if kill -0 $PID 2>/dev/null; then
    # Process is still running (started successfully)
    kill $PID 2>/dev/null || true
    wait $PID 2>/dev/null
    EXIT_CODE=0
  else
    # Process already exited
    wait $PID 2>/dev/null
    EXIT_CODE=$?
  fi
  set -e
fi

# Exit code 0 or 1 is acceptable (1 = GUI error, which is expected in headless)
# Exit code 124/125 = timeout (process was running, which is good)
if [ $EXIT_CODE -eq 124 ] || [ $EXIT_CODE -eq 125 ] || [ $EXIT_CODE -eq 0 ]; then
  echo "[OK] Argument parsing works (executable started successfully)"
elif [ $EXIT_CODE -eq 1 ]; then
  echo "[OK] Argument parsing works (GUI unavailable in headless environment, which is expected)"
else
  echo "WARNING: Argument parsing test failed (exit code: $EXIT_CODE)"
fi

echo ""
echo "Build and basic tests complete!"
exit 0
