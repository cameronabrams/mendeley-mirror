@echo off
REM Double-click to refresh the Mendeley mirror in this folder.
REM Prefers uv (which installs the one dependency itself, per the PEP 723
REM header in mendeley_mirror.py); falls back to the py launcher.
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if %errorlevel%==0 (
    uv run --script mendeley_mirror.py %*
    goto :done
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 mendeley_mirror.py %*
    goto :done
)

echo Could not find uv or the py launcher on PATH.
echo Install uv from https://docs.astral.sh/uv/ or run the script with your
echo own interpreter:  python mendeley_mirror.py

:done
echo.
pause
