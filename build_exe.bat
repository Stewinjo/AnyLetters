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
set "TMP_OUTPUT=%TEMP%\anyletters_list_%RANDOM%.log"
dist\%NAME%.exe --list >"%TMP_OUTPUT%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" (
    echo [OK] --list argument works
) else (
    echo ERROR: --list test failed (exit code: %EXIT_CODE%)
    echo ----- command output -----
    type "%TMP_OUTPUT%"
    echo --------------------------
    del "%TMP_OUTPUT%"
    exit /b %EXIT_CODE%
)
del "%TMP_OUTPUT%"
