@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "LOG_DIR=%~dp0log"
set "START_LOG=%LOG_DIR%\cfquant_startup.log"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul
call :log "restart_cfquant.bat invoked"

set "WEB_PORT=8765"
set "CFQUANT_RESTART_ROOT=%~dp0"
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=8765; $root=$env:CFQUANT_RESTART_ROOT; $files=@((Join-Path $root 'runtime\config\cfquant_web_config.json'), (Join-Path $root 'cfquant_web_config.json')); foreach ($f in $files) { if (Test-Path -LiteralPath $f) { try { $c=Get-Content -Raw -LiteralPath $f | ConvertFrom-Json; if ($c.web_port) { $p=[int]$c.web_port } elseif ($c.web_server -and $c.web_server.port) { $p=[int]$c.web_server.port }; break } catch {} } }; Write-Output $p"`) do set "WEB_PORT=%%P"
set "CFQUANT_RESTART_ROOT="
if not defined WEB_PORT set "WEB_PORT=8765"
if defined CFQUANT_WEB_PORT set "WEB_PORT=%CFQUANT_WEB_PORT%"
if defined CFQUANT_START_WEB_PORT set "WEB_PORT=%CFQUANT_START_WEB_PORT%"

echo Restarting cfquant local services, keeping LTtx running...
set "CFQUANT_STOP_NO_PAUSE=1"
call "%~dp0stop_cfquant.bat" --keep-lttx
set "STOP_CODE=%errorlevel%"
if not "%STOP_CODE%"=="0" (
    echo cfquant stop returned %STOP_CODE%. Will continue only if web port %WEB_PORT% is released.
    call :log "stop returned code=%STOP_CODE%"
)

set "CFQUANT_RESTART_WAIT_SECONDS=20"
call :wait_for_port_release %WEB_PORT% %CFQUANT_RESTART_WAIT_SECONDS%
set "WAIT_CODE=%errorlevel%"
set "CFQUANT_RESTART_WAIT_SECONDS="

if not "%WAIT_CODE%"=="0" (
    echo Web port %WEB_PORT% is still listening. Restart aborted to avoid duplicate services.
    call :log "restart aborted because port still listening port=%WEB_PORT%"
    call :pause_on_error
    endlocal
    exit /b 1
)

timeout /t 1 /nobreak >nul
call "%~dp0start_cfquant.bat" %*
set "START_CODE=%errorlevel%"
if "%START_CODE%"=="0" (
    echo cfquant restart completed.
    call :log "restart completed port=%WEB_PORT%"
) else (
    echo cfquant restart failed with code %START_CODE%.
    call :log "restart failed code=%START_CODE%"
)
endlocal
exit /b %START_CODE%

:wait_for_port_release
set "CFQUANT_RESTART_PORT=%~1"
set "CFQUANT_RESTART_WAIT=%~2"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$port=[int]$env:CFQUANT_RESTART_PORT; $wait=[int]$env:CFQUANT_RESTART_WAIT; $deadline=(Get-Date).AddSeconds($wait); while ((Get-Date) -lt $deadline) { try { $client=[Net.Sockets.TcpClient]::new(); $iar=$client.BeginConnect('127.0.0.1',$port,$null,$null); if ($iar.AsyncWaitHandle.WaitOne(500,$false)) { $client.EndConnect($iar); $client.Close() } else { $client.Close(); exit 0 } } catch { exit 0 }; Start-Sleep -Milliseconds 500 }; exit 1"
set "CFQUANT_RESTART_PORT="
set "CFQUANT_RESTART_WAIT="
exit /b %errorlevel%

:pause_on_error
if "%CFQUANT_RESTART_NO_PAUSE%"=="1" exit /b 0
if "%CFQUANT_START_NO_PAUSE%"=="1" exit /b 0
echo.
echo This window stays open because restart failed.
pause
exit /b 0

:log
set "CFQUANT_LOG_TS="
for /f "usebackq delims=" %%T in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'"`) do set "CFQUANT_LOG_TS=%%T"
if not defined CFQUANT_LOG_TS set "CFQUANT_LOG_TS=%time%"
>>"%START_LOG%" echo [%CFQUANT_LOG_TS%] %~1
set "CFQUANT_LOG_TS="
exit /b 0
