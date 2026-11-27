@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo Abroad - start Flask + Cloudflare tunnel
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv\Scripts\python.exe was not found.
    echo        Run this script from the D:\abroad folder.
    echo.
    pause
    exit /b 1
)
if not exist "instance\cloudflared.exe" (
    echo ERROR: instance\cloudflared.exe was not found.
    echo.
    pause
    exit /b 1
)
if not exist "instance" mkdir "instance"

echo [1/4] Clearing old logs ...
type nul > "instance\flask.log"
type nul > "instance\tunnel.log"

echo [2/4] Starting Flask on http://127.0.0.1:5000 ...
start "Abroad Flask" /min cmd /c ".venv\Scripts\python.exe app.py > instance\flask.log 2>&1"

echo       Waiting for Flask to answer ...
set "UP="
for /l %%I in (1,1,40) do (
    if not defined UP (
        timeout /t 1 /nobreak >nul
        findstr /c:"Running on http://127.0.0.1:5000" "instance\flask.log" >nul 2>&1
        if not errorlevel 1 set "UP=1"
    )
)
if defined UP (
    echo       Flask is listening.
) else (
    echo       WARNING: Flask has not reported that it is listening. Check instance\flask.log
)

echo [3/4] Starting Cloudflare quick tunnel ...
start "Abroad Tunnel" /min cmd /c "instance\cloudflared.exe tunnel --url http://127.0.0.1:5000 > instance\tunnel.log 2>&1"

echo [4/4] Waiting for the public URL ...
set "LINE="
for /l %%I in (1,1,60) do (
    if not defined LINE (
        timeout /t 1 /nobreak >nul
        for /f "delims=" %%L in ('findstr /i /c:"trycloudflare.com" "instance\tunnel.log" 2^>nul') do set "LINE=%%L"
    )
)

echo.
if defined LINE (
    echo Tunnel line from the log ^(the https address is your link^):
    echo   !LINE!
) else (
    echo Tunnel URL not found yet. Open instance\tunnel.log in a few seconds.
)
echo.
echo Logs:  instance\flask.log    instance\tunnel.log
echo Stop:  stop-abroad.cmd
echo.
echo Keep this window closed only if you do not need the logs; closing it does not stop the app.
echo.
pause
