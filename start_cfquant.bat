@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"

echo Starting LTtx server...
start "cfquant LTtx" /min "%PYTHON_EXE%" "%~dp0LTtx\tx\LTtx_server.py"

timeout /t 2 /nobreak >nul

echo Starting cfquant web dashboard...
start "cfquant Web" /min "%PYTHON_EXE%" "%~dp0cfquant_web_server.py" --host 127.0.0.1 --port 8765

timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765/"

echo cfquant started. Open http://127.0.0.1:8765/ if the browser did not open.
endlocal
