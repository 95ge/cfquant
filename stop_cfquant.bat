@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Stopping cfquant local services...

set "CFQUANT_KEEP_LTTX=0"
if /i "%~1"=="--keep-lttx" set "CFQUANT_KEEP_LTTX=1"
if /i "%~1"=="/keep-lttx" set "CFQUANT_KEEP_LTTX=1"

call :stop_python_script "%~dp0cfquant_web_server.py" "cfquant Web"
set "WEB_STOP_CODE=%errorlevel%"

call :stop_python_script "%~dp0cfquant_pipe_hub.py" "cfquant PipeHub"
set "PIPE_STOP_CODE=%errorlevel%"

if "%CFQUANT_KEEP_LTTX%"=="1" (
    echo Keeping cfquant LTtx running.
    set "LTTX_STOP_CODE=0"
) else (
    call :stop_python_script "%~dp0LTtx\tx\LTtx_server.py" "cfquant LTtx"
    set "LTTX_STOP_CODE=%errorlevel%"
)

if "%WEB_STOP_CODE%"=="0" if "%PIPE_STOP_CODE%"=="0" if "%LTTX_STOP_CODE%"=="0" (
    if "%CFQUANT_KEEP_LTTX%"=="1" (
        echo cfquant Web and PipeHub stopped. LTtx is still running.
    ) else (
        echo cfquant local services stopped.
    )
    endlocal
    exit /b 0
)

echo cfquant stop completed with errors. Please check messages above.
call :pause_on_error
endlocal
exit /b 1

:stop_python_script
set "CFQUANT_STOP_TARGET=%~f1"
set "CFQUANT_STOP_NAME=%~2"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$targetName=[System.IO.Path]::GetFileName($env:CFQUANT_STOP_TARGET); $name=$env:CFQUANT_STOP_NAME; $procs=@(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'python*.exe' -and $_.CommandLine -and $_.CommandLine.ToLower().Contains($targetName.ToLower()) }); if (-not $procs.Count) { Write-Output ($name + ' not running.'); exit 0 }; $failed=$false; foreach ($p in $procs) { try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop; Write-Output ('Stopped ' + $name + ' pid=' + $p.ProcessId) } catch { $failed=$true; Write-Output ('Failed to stop ' + $name + ' pid=' + $p.ProcessId + ': ' + $_.Exception.Message) } }; if ($failed) { exit 1 } else { exit 0 }"
set "CFQUANT_STOP_TARGET="
set "CFQUANT_STOP_NAME="
exit /b %errorlevel%

:pause_on_error
if "%CFQUANT_STOP_NO_PAUSE%"=="1" exit /b 0
if "%CFQUANT_START_NO_PAUSE%"=="1" exit /b 0
echo.
echo This window stays open because stop failed.
pause
exit /b 0
