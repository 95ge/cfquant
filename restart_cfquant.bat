@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "WEB_PORT=8765"
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=8765; $root='%~dp0'; $files=@((Join-Path $root 'runtime\config\cfquant_web_config.json'), (Join-Path $root 'cfquant_web_config.json')); foreach ($f in $files) { if (Test-Path -LiteralPath $f) { try { $c=Get-Content -Raw -LiteralPath $f | ConvertFrom-Json; if ($c.web_port) { $p=[int]$c.web_port } elseif ($c.web_server -and $c.web_server.port) { $p=[int]$c.web_server.port }; break } catch {} } }; Write-Output $p"`) do set "WEB_PORT=%%P"
if not defined WEB_PORT set "WEB_PORT=8765"

echo Restarting cfquant local services...
call "%~dp0stop_cfquant.bat"
set "STOP_CODE=%errorlevel%"
if not "%STOP_CODE%"=="0" (
    echo cfquant stop returned %STOP_CODE%. Will continue only if web port %WEB_PORT% is released.
)

set "CFQUANT_RESTART_WEB_PORT=%WEB_PORT%"
set "CFQUANT_RESTART_WAIT_SECONDS=20"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$port=[int]$env:CFQUANT_RESTART_WEB_PORT; $wait=[int]$env:CFQUANT_RESTART_WAIT_SECONDS; $deadline=(Get-Date).AddSeconds($wait); while ((Get-Date) -lt $deadline) { $conn=@(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue); if (-not $conn.Count) { exit 0 }; Start-Sleep -Milliseconds 500 }; exit 1"
set "WAIT_CODE=%errorlevel%"
set "CFQUANT_RESTART_WEB_PORT="
set "CFQUANT_RESTART_WAIT_SECONDS="

if not "%WAIT_CODE%"=="0" (
    echo Web port %WEB_PORT% is still listening. Restart aborted to avoid duplicate services.
    endlocal
    exit /b 1
)

timeout /t 1 /nobreak >nul
call "%~dp0start_cfquant.bat" %*
set "START_CODE=%errorlevel%"
if "%START_CODE%"=="0" (
    echo cfquant restart completed.
) else (
    echo cfquant restart failed with code %START_CODE%.
)
endlocal
exit /b %START_CODE%
