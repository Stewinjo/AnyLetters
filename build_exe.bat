@echo off
setlocal EnableExtensions
REM Build AnyLetters as a single-file executable (Windows)
REM Requires: pip install -r requirements.txt (pyinstaller)
REM
REM Optional bake flags (forwarded to bake_defaults.py):
REM   --lang de --length 6 --difficulty easy --require-solutions
REM   --exe-name AnyLettersDE --disable-solution-filters
REM
REM The AnyLetters.spec file includes:
REM   - defaults.json (baked CLI defaults)
REM   - solutions/ folder (solutions/<lang><length>.txt)
REM   - dictionaries submodule
REM   - filters/

echo Baking defaults (if any bake flags were provided)...
python bake_defaults.py %*
if errorlevel 1 (
    echo.
    echo Baking defaults failed!
    exit /b %ERRORLEVEL%
)

for /f "usebackq delims=" %%I in (`python -c "import json; print(json.load(open('defaults.json', encoding='utf-8')).get('exe_name', 'AnyLetters'))"`) do set "NAME=%%I"
if "%NAME%"=="" set "NAME=AnyLetters"

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

echo Testing baked defaults via --help...
dist\%NAME%.exe --help >"%TMP_OUTPUT%" 2>&1
findstr /C:"default:" "%TMP_OUTPUT%" >nul
if errorlevel 1 (
    echo WARNING: could not confirm baked defaults in --help output
) else (
    echo [OK] --help shows defaults
)
del "%TMP_OUTPUT%" 2>nul
