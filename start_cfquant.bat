@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
set "WEB_PORT=8765"
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=8765; $f='%~dp0cfquant_web_config.json'; if (Test-Path -LiteralPath $f) { try { $c=Get-Content -Raw -LiteralPath $f | ConvertFrom-Json; if ($c.web_port) { $p=[int]$c.web_port } elseif ($c.web_server -and $c.web_server.port) { $p=[int]$c.web_server.port } } catch {} }; Write-Output $p"`) do set "WEB_PORT=%%P"
if not defined WEB_PORT set "WEB_PORT=8765"

echo Starting cfquant web dashboard...
echo The web server will start PipeHub or LTtx according to the saved mode.
call :is_port_listening %WEB_PORT%
if errorlevel 1 (
    start "cfquant Web" /min "%PYTHON_EXE%" "%~dp0cfquant_web_server.py"
) else (
    echo cfquant web dashboard already listening on %WEB_PORT%, skip start.
)

timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:%WEB_PORT%/"

echo cfquant started. Open http://127.0.0.1:%WEB_PORT%/ if the browser did not open.
endlocal
exit /b 0

:is_port_listening
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort %1 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
exit /b %errorlevel%
