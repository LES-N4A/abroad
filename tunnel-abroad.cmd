@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

rem Always use the Windows tools, never the Unix ones a Git Bash / MSYS PATH can shadow.
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem"
set "PING=%SystemRoot%\System32\ping.exe"
set "NETSTAT=%SystemRoot%\System32\netstat.exe"
set "FINDSTR=%SystemRoot%\System32\findstr.exe"
set "TASKLIST=%SystemRoot%\System32\tasklist.exe"
set "CLIP=%SystemRoot%\System32\clip.exe"
set "CURL=%SystemRoot%\System32\curl.exe"

echo ============================================
echo Abroad - public link (Cloudflare quick tunnel)
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
    echo        Put cloudflared.exe in the instance folder and try again.
    echo.
    pause
    exit /b 1
)
if not exist "instance" mkdir "instance"

rem ------------------------------------------------- one tunnel at a time
"%TASKLIST%" /fi "imagename eq cloudflared.exe" 2>nul | "%FINDSTR%" /i "cloudflared.exe" >nul
if not errorlevel 1 (
    echo A tunnel is already running. Its link, from instance\tunnel.log:
    echo.
    "%FINDSTR%" /i /c:"trycloudflare.com" "instance\tunnel.log" 2>nul
    echo.
    echo Run stop-abroad.cmd first if you want a brand new link.
    echo.
    pause
    exit /b 0
)

rem ------------------------------------------------------- which app port?
rem Optional argument: tunnel-abroad.cmd 5001
set "PORT=%~1"
if not defined PORT (
    "%NETSTAT%" -ano | "%FINDSTR%" /c:"127.0.0.1:5000" | "%FINDSTR%" /i "LISTENING" >nul 2>&1 && set "PORT=5000"
)
if not defined PORT (
    "%NETSTAT%" -ano | "%FINDSTR%" /c:"127.0.0.1:5001" | "%FINDSTR%" /i "LISTENING" >nul 2>&1 && set "PORT=5001"
)

if defined PORT (
    echo [1/3] Using the app already listening on http://127.0.0.1:!PORT!
) else (
    echo [1/3] Starting Flask on http://127.0.0.1:5000 ...
    type nul > "instance\flask.log"
    start "Abroad Flask" /min cmd /c ".venv\Scripts\python.exe app.py > instance\flask.log 2>&1"
    set "PORT=5000"
    set "UP="
    for /l %%I in (1,1,45) do (
        if not defined UP (
            "%PING%" -n 2 127.0.0.1 >nul
            "%NETSTAT%" -ano | "%FINDSTR%" /c:"127.0.0.1:5000" | "%FINDSTR%" /i "LISTENING" >nul 2>&1
            if not errorlevel 1 set "UP=1"
        )
    )
    if defined UP (
        echo       Flask is listening.
    ) else (
        echo       WARNING: port 5000 is not listening. Check instance\flask.log
    )
)

rem ------------------------------------------------------------- the tunnel
echo [2/3] Pointing the tunnel at http://127.0.0.1:!PORT! ...
type nul > "instance\tunnel.log"
start "Abroad Tunnel" /min cmd /c "instance\cloudflared.exe tunnel --url http://127.0.0.1:!PORT! > instance\tunnel.log 2>&1"

echo [3/3] Waiting for the public address ...
set "URL="
set "LINE="
for /l %%I in (1,1,90) do (
    if not defined URL (
        "%PING%" -n 2 127.0.0.1 >nul
        set "LINE="
        for /f "delims=" %%L in ('findstr /i /c:"trycloudflare.com" "instance\tunnel.log" 2^>nul') do set "LINE=%%L"
        if defined LINE (
            if not "!LINE:https://=!"=="!LINE!" (
                set "URL=!LINE:*https://=https://!"
                for /f "tokens=1 delims= " %%A in ("!URL!") do set "URL=%%A"
            )
        )
    )
)

echo.
if not defined URL (
    echo The public address is not in the log yet.
    echo.
    if defined LINE (
        echo Last tunnel.log line:
        echo   !LINE!
        echo.
    )
    echo Wait a few seconds, then open instance\tunnel.log - the line with
    echo trycloudflare.com in it is your link.
    echo.
    pause
    exit /b 1
)

echo ============================================
echo   SHARE THIS LINK WITH YOUR FRIENDS
echo.
echo     !URL!
echo ============================================
echo.
if exist "%CLIP%" (
    echo !URL!| "%CLIP%"
    echo The link is on your clipboard.
)
echo It is public: anyone who has it can open the site, so close this tunnel
echo ^(stop-abroad.cmd^) when you are done.
echo.

rem --------------------------------------------------- is it reachable yet?
if not exist "%CURL%" (
    echo Public check skipped ^(curl.exe not found^). Open the link to test it.
    goto :summary
)
set "LIVE="
for /l %%I in (1,1,20) do (
    if not defined LIVE (
        "%CURL%" -s -f -o nul -m 10 "!URL!" >nul 2>&1
        if not errorlevel 1 (set "LIVE=1") else ("%PING%" -n 4 127.0.0.1 >nul)
    )
)
if defined LIVE (
    echo Public check: the link answers. Send it out.
) else (
    echo Public check: not answering yet. Cloudflare can need up to a minute;
    echo               reload the link once or twice.
)

:summary
echo.
echo Demo accounts (password demo1234):
echo   sarra@abroad.tn  store@abroad.tn  ahmed@abroad.tn  pro@abroad.tn  admin@abroad.tn
echo.
echo Link changes every time you start a new tunnel.
echo Logs:  instance\flask.log   instance\tunnel.log
echo Stop:  stop-abroad.cmd   (closes the app and the tunnel)
echo.
pause
