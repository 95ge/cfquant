@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"

echo Starting LTtx server...
call :is_port_listening 2049
if errorlevel 1 (
    start "cfquant LTtx" /min "%PYTHON_EXE%" "%~dp0LTtx\tx\LTtx_server.py"
) else (
    echo LTtx server already listening on 2049, skip start.
)

timeout /t 2 /nobreak >nul

echo Starting cfquant web dashboard...
call :is_port_listening 8765
if errorlevel 1 (
    start "cfquant Web" /min "%PYTHON_EXE%" "%~dp0cfquant_web_server.py" --host 127.0.0.1 --port 8765
) else (
    echo cfquant web dashboard already listening on 8765, skip start.
)

timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765/"

echo cfquant started. Open http://127.0.0.1:8765/ if the browser did not open.
endlocal
exit /b 0

:is_port_listening
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort %1 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }"
exit /b %errorlevel%
