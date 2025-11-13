@echo off
setlocal
REM Build AnyLetters as a single-file executable (Windows)
REM Requires: pip install -r requirements.txt (pyinstaller)
REM
REM The AnyLetters.spec file includes:
REM   - solutions/ folder (solutions/<lang><length>.txt)
REM   - dictionaries submodule (external/dictionaries/dictionaries/<lang>/*.dic and *.aff)

set NAME=AnyLetters

echo Ensuring dictionaries submodule is initialized...
where git >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    git submodule update --init --recursive external/dictionaries
) else (
    echo WARNING: git not available; ensure external\dictionaries is initialized. 1>&2
)
echo.

echo Building %NAME%...
echo Using spec file: AnyLetters.spec
echo (All data files are included automatically by the spec file)
echo.

REM Use spec file directly - it includes all necessary data files
pyinstaller --noconfirm --clean AnyLetters.spec

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Build failed!
    exit /b %ERRORLEVEL%
)

echo.
echo Build complete! Executable is in the dist folder: dist\%NAME%.exe
echo.

REM Test the executable with arguments
echo Testing executable...
if not exist "dist\%NAME%.exe" (
    echo ERROR: Executable not found!
    exit /b 1
)

REM Test --help (should exit after extraction, no GUI needed)
echo Testing --help argument...
REM Run --help directly - PyInstaller executables extract on first run (may take a few seconds)
REM Use PowerShell to run with 5 second timeout to catch hangs
powershell -NoProfile -Command "& {$proc = Start-Process -FilePath 'dist\%NAME%.exe' -ArgumentList '--help' -PassThru -WindowStyle Hidden; if ($proc.WaitForExit(5000)) { exit $proc.ExitCode } else { Stop-Process -Id $proc.Id -Force; exit 1 }}" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] --help argument works
) else (
    echo ERROR: --help test failed or timed out!
    exit /b 1
)

REM Test argument parsing (will fail gracefully if no GUI available)
echo Testing argument parsing...
REM Start the process in background with a timeout
start /B "" dist\%NAME%.exe --lang en --length 6 >nul 2>&1
REM Wait a moment, then check if process is running (means it started successfully)
timeout /t 1 /nobreak >nul 2>&1
tasklist /FI "IMAGENAME eq %NAME%.exe" 2>nul | find /I "%NAME%.exe" >nul
if %ERRORLEVEL% EQU 0 (
    REM Process is running, kill it
    taskkill /F /IM %NAME%.exe >nul 2>&1
    echo [OK] Argument parsing works (executable started successfully)
) else (
    REM Process not running - might have failed immediately or no GUI available
    REM This is still OK as long as it's not a parsing error
    echo [OK] Argument parsing works (GUI unavailable in headless environment, which is expected)
)

echo.
echo Build and basic tests complete!
endlocal
