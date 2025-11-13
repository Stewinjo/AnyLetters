@echo off
setlocal
REM Build AnyLetters as a single-file executable (Windows)
REM Requires: pip install -r requirements.txt (pyinstaller)
REM
REM The AnyLetters.spec file includes:
REM   - solutions/ folder (solutions/<lang><length>.txt)
REM   - dictionaries submodule (external/dictionaries/dictionaries/<lang>/*.dic and *.aff)

set NAME=AnyLetters

echo Building %NAME%...
echo Using spec file: AnyLetters.spec
echo (All data files are included automatically by the spec file)
echo.

pyinstaller --noconfirm --clean AnyLetters.spec

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Build failed!
    exit /b %ERRORLEVEL%
)

echo Testing executable...
if not exist "dist\%NAME%.exe" (
    echo ERROR: Executable not found!
    exit /b 1
)

echo Testing --list argument...
powershell -NoProfile -Command "& {$proc = Start-Process -FilePath 'dist\%NAME%.exe' -ArgumentList '--list' -PassThru -WindowStyle Hidden; if ($proc.WaitForExit(5000)) { exit $proc.ExitCode } else { Stop-Process -Id $proc.Id -Force; exit 1 }}" >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo [OK] --list argument works
) else (
    echo ERROR: --list test failed or timed out!
    exit /b 1
)
