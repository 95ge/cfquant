@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Stopping cfquant local services...

set "CFQUANT_KEEP_LTTX=0"
if /i "%~1"=="--keep-lttx" set "CFQUANT_KEEP_LTTX=1"
if /i "%~1"=="/keep-lttx" set "CFQUANT_KEEP_LTTX=1"

set "WEB_PORT=8765"
set "CFQUANT_STOP_ROOT=%~dp0"
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=8765; $root=$env:CFQUANT_STOP_ROOT; $files=@((Join-Path $root 'runtime\config\cfquant_web_config.json'), (Join-Path $root 'cfquant_web_config.json')); foreach ($f in $files) { if (Test-Path -LiteralPath $f) { try { $c=Get-Content -Raw -LiteralPath $f | ConvertFrom-Json; if ($c.web_port) { $p=[int]$c.web_port } elseif ($c.web_server -and $c.web_server.port) { $p=[int]$c.web_server.port }; break } catch {} } }; Write-Output $p"`) do set "WEB_PORT=%%P"
set "CFQUANT_STOP_ROOT="
if not defined WEB_PORT set "WEB_PORT=8765"
if defined CFQUANT_WEB_PORT set "WEB_PORT=%CFQUANT_WEB_PORT%"
if defined CFQUANT_START_WEB_PORT set "WEB_PORT=%CFQUANT_START_WEB_PORT%"

call :stop_python_script "%~dp0cfquant_web_server.py" "cfquant Web"
set "WEB_STOP_CODE=%errorlevel%"

call :stop_cfquant_web_port %WEB_PORT%
set "WEB_PORT_STOP_CODE=%errorlevel%"

call :stop_python_script "%~dp0cfquant_pipe_hub.py" "cfquant PipeHub"
set "PIPE_STOP_CODE=%errorlevel%"

if "%CFQUANT_KEEP_LTTX%"=="1" (
    echo Keeping cfquant LTtx running.
    set "LTTX_STOP_CODE=0"
) else (
    call :stop_python_script "%~dp0LTtx\tx\LTtx_server.py" "cfquant LTtx"
    set "LTTX_STOP_CODE=%errorlevel%"
)

if "%WEB_STOP_CODE%"=="0" if "%WEB_PORT_STOP_CODE%"=="0" if "%PIPE_STOP_CODE%"=="0" if "%LTTX_STOP_CODE%"=="0" (
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
set "STOP_RESULT=%errorlevel%"
set "CFQUANT_STOP_TARGET="
set "CFQUANT_STOP_NAME="
exit /b %STOP_RESULT%

:stop_cfquant_web_port
set "CFQUANT_STOP_WEB_PORT=%~1"
set "CFQUANT_STOP_ROOT=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$port=[int]$env:CFQUANT_STOP_WEB_PORT; $root=($env:CFQUANT_STOP_ROOT -replace '\\\\','/').TrimEnd('/').ToLowerInvariant(); $rows=@(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue); if (-not $rows.Count) { Write-Output ('cfquant Web port ' + $port + ' not listening.'); exit 0 }; $failed=$false; $left=$false; foreach ($row in $rows) { $pidValue=$row.OwningProcess; $proc=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $pidValue) -ErrorAction SilentlyContinue; $name=if ($proc) { [string]$proc.Name } else { 'unknown' }; $cmd=if ($proc) { [string]$proc.CommandLine } else { '' }; $exe=if ($proc) { [string]$proc.ExecutablePath } else { '' }; $text=($name + ' ' + $cmd + ' ' + $exe).ToLowerInvariant(); $pathText=$text -replace '\\\\','/'; $isCfquant=$text.Contains('cfquant_web_server.py') -or $text.Contains('cfquant-web') -or $text.Contains('cfquant.exe') -or ($text.Contains('cfquant') -and ($text.Contains(' run') -or $text.Contains(' serve') -or $text.Contains(' web'))) -or ($root -and $pathText.Contains($root) -and $text.Contains('python')); if ($isCfquant) { try { Stop-Process -Id $pidValue -Force -ErrorAction Stop; Write-Output ('Stopped cfquant Web port owner pid=' + $pidValue) } catch { $failed=$true; Write-Output ('Failed to stop cfquant Web port owner pid=' + $pidValue + ': ' + $_.Exception.Message) } } else { $left=$true; Write-Output ('Port ' + $port + ' is owned by non-cfquant process pid=' + $pidValue + ' name=' + $name) } }; if ($failed -or $left) { exit 1 } else { exit 0 }"
set "STOP_RESULT=%errorlevel%"
set "CFQUANT_STOP_WEB_PORT="
set "CFQUANT_STOP_ROOT="
exit /b %STOP_RESULT%

:pause_on_error
if "%CFQUANT_STOP_NO_PAUSE%"=="1" exit /b 0
if "%CFQUANT_START_NO_PAUSE%"=="1" exit /b 0
echo.
echo This window stays open because stop failed.
pause
exit /b 0
