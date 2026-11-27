@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo Abroad - stop Flask + Cloudflare tunnel
echo ============================================
echo.

echo Stopping Flask (python.exe) and cloudflared.exe ...
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM cloudflared.exe /T >nul 2>&1
echo       done (this also stops other python.exe processes on this machine).

echo Clearing the logs so the next start shows a fresh tunnel link ...
if exist "instance" (
    type nul > "instance\flask.log"
    type nul > "instance\tunnel.log"
)
echo.
echo To restart:  start-abroad.cmd
echo.
pause
