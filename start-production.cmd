@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo Abroad - start PRODUCTION app (app_production.py)
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv\Scripts\python.exe was not found.
    echo        Run this script from the D:\abroad folder.
    echo.
    pause
    exit /b 1
)
if not exist "instance" mkdir "instance"
if not exist ".env" (
    echo WARNING: .env was not found. SECRET_KEY must be set before the app will run
    echo          with FLASK_ENV=production; locally it falls back to development.
    echo.
)

rem Read the host and port from .env so this script and app_production.py agree.
set "HOST=127.0.0.1"
set "PORT=5001"
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        if /i "%%A"=="FLASK_RUN_HOST" set "HOST=%%B"
        if /i "%%A"=="FLASK_RUN_PORT" set "PORT=%%B"
    )
)

set "PROD_LOG=instance\production.log"

echo [1/3] Clearing old log ...
type nul > "%PROD_LOG%"

echo [2/3] Starting app_production.py on http://!HOST!:!PORT! ...
start "Abroad Production" /min cmd /c ".venv\Scripts\python.exe app_production.py > %PROD_LOG% 2>&1"

echo       Waiting for port !PORT! to accept connections ...
set "UP="
for /l %%I in (1,1,40) do (
    if not defined UP (
        timeout /t 1 /nobreak >nul
        netstat -ano | findstr /c:"!HOST!:!PORT!" | findstr /i "LISTENING" >nul 2>&1
        if not errorlevel 1 set "UP=1"
    )
)
if defined UP (
    echo       Listening on http://!HOST!:!PORT!
) else (
    echo       WARNING: nothing is listening on port !PORT! yet.
    echo                Last lines of %PROD_LOG%:
    echo.
    powershell -NoProfile -Command "Get-Content '%PROD_LOG%' -Tail 12" 2>nul
    echo.
)

echo [3/3] Up.
echo.
echo Open:    http://!HOST!:!PORT!
echo Health:  http://!HOST!:!PORT!/health
echo Log:     %PROD_LOG%
echo Stop:    close the "Abroad Production" window, or run:
echo            taskkill /FI "WINDOWTITLE eq Abroad Production*" /T /F
echo.
echo Host and port come from FLASK_RUN_HOST / FLASK_RUN_PORT in .env.
echo.
pause
