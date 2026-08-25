@echo off
REM Non-interactive refresh, for the scheduled task. No pause, no prompts:
REM output goes to .mirror\mirror.log and mirror-status.md.
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if %errorlevel%==0 (
    uv run --script mendeley_mirror.py --quiet %*
    exit /b %errorlevel%
)

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 mendeley_mirror.py --quiet %*
    exit /b %errorlevel%
)

exit /b 9
