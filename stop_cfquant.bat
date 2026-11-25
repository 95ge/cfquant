@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"

rem Hidden automation callers can explicitly skip the final display delay.
for %%A in (%*) do if /i "%%~A"=="--no-pause" set "CFQUANT_STOP_NO_PAUSE=1"
echo [STEP] Stop operation started. Please wait...

echo Stopping cfquant local services...

set "CFQUANT_KEEP_LTTX=0"
if /i "%~1"=="--keep-lttx" set "CFQUANT_KEEP_LTTX=1"
if /i "%~1"=="/keep-lttx" set "CFQUANT_KEEP_LTTX=1"

set "WEB_PORT=8765"
set "CFQUANT_STOP_ROOT=%~dp0"
for /f "usebackq delims=" %%P in (`powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$p=8765; $root=$env:CFQUANT_STOP_ROOT; $files=@((Join-Path $root 'runtime\config\cfquant_web_config.json'), (Join-Path $root 'cfquant_web_config.json')); foreach ($f in $files) { if (Test-Path -LiteralPath $f) { try { $c=Get-Content -Raw -LiteralPath $f | ConvertFrom-Json; if ($c.web_port) { $p=[int]$c.web_port } elseif ($c.web_server -and $c.web_server.port) { $p=[int]$c.web_server.port }; break } catch {} } }; Write-Output $p"`) do set "WEB_PORT=%%P"
set "CFQUANT_STOP_ROOT="
if not defined WEB_PORT set "WEB_PORT=8765"
if defined CFQUANT_WEB_PORT set "WEB_PORT=%CFQUANT_WEB_PORT%"
if defined CFQUANT_START_WEB_PORT set "WEB_PORT=%CFQUANT_START_WEB_PORT%"

call :stop_cfquant_center
set "CENTER_STOP_CODE=0"
if errorlevel 1 set "CENTER_STOP_CODE=1"

call :stop_python_script "%~dp0cfquant_web_server.py" "cfquant Web"
set "WEB_STOP_CODE=0"
if errorlevel 1 set "WEB_STOP_CODE=1"

call :stop_cfquant_web_port %WEB_PORT%
set "WEB_PORT_STOP_CODE=0"
if errorlevel 1 set "WEB_PORT_STOP_CODE=1"

call :stop_python_script "%~dp0cfquant_pipe_hub.py" "cfquant PipeHub"
set "PIPE_STOP_CODE=0"
if errorlevel 1 set "PIPE_STOP_CODE=1"

if "%CFQUANT_KEEP_LTTX%"=="1" (
    echo Keeping cfquant LTtx running.
    set "LTTX_STOP_CODE=0"
) else (
    call :stop_python_script "%~dp0LTtx\tx\LTtx_server.py" "cfquant LTtx"
    set "LTTX_STOP_CODE=0"
    if errorlevel 1 set "LTTX_STOP_CODE=1"
)

if "%CENTER_STOP_CODE%"=="0" if "%WEB_STOP_CODE%"=="0" if "%WEB_PORT_STOP_CODE%"=="0" if "%PIPE_STOP_CODE%"=="0" if "%LTTX_STOP_CODE%"=="0" (
    if "%CFQUANT_KEEP_LTTX%"=="1" (
        echo cfquant Web and PipeHub stopped. LTtx is still running.
    ) else (
        echo cfquant local services stopped.
    )
    call :pause_on_success
    endlocal
    exit /b 0
)

echo cfquant stop completed with errors. Please check messages above.
call :pause_on_error
endlocal
exit /b 1

:stop_cfquant_center
rem Validate both PID and process creation time before stopping A and its owned worker.
set "CFQUANT_STOP_ROOT=%~dp0"
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$root=if ($env:CFQUANT_HOME) { $env:CFQUANT_HOME } elseif ($env:CFQUANT_STATE_DIR) { $env:CFQUANT_STATE_DIR } else { $env:CFQUANT_STOP_ROOT }; $root=[IO.Path]::GetFullPath($root).TrimEnd('\'); $runtime=if ($env:CFQUANT_RUNTIME_DIR) { $env:CFQUANT_RUNTIME_DIR } else { Join-Path $root 'runtime' }; $file=if ($env:CFQUANT_PIPE_HUB_STATUS_FILE) { $env:CFQUANT_PIPE_HUB_STATUS_FILE } else { Join-Path $runtime 'status\cfquant_pipe_hub_status.json' }; if (-not (Test-Path -LiteralPath $file)) { exit 0 }; try { $state=Get-Content -Raw -Encoding UTF8 -LiteralPath $file | ConvertFrom-Json; if (-not $state.process_created -or -not $state.state_dir -or [IO.Path]::GetFullPath($state.state_dir).TrimEnd('\') -ne $root) { Write-Output 'Center state identity unavailable; using legacy stop checks.'; exit 0 }; $center=Get-Process -Id ([int]$state.pid) -ErrorAction SilentlyContinue; if (-not $center) { exit 0 }; $created=($center.StartTime.ToUniversalTime()-[datetime]'1970-01-01').TotalSeconds; if ([Math]::Abs($created-[double]$state.process_created) -gt 0.05) { Write-Output 'Center PID was reused; skipping stale state.'; exit 0 }; $info=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $center.Id); if ($info.CommandLine -notmatch 'cfquant\.(center_runtime|center_restart)|cfquant_web_server(?:\.py|\s|$)|cfquant_pipe_hub(?:\.py|\s|$)|cfquant(-web|-pipe-hub)?\.exe|cfquant.* (center|serve|run|web)') { Write-Output 'Center command identity mismatch.'; exit 1 }; $child=$null; $childId=[int]$state.center.services.pid; if ($childId -gt 0) { $childInfo=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $childId) -ErrorAction SilentlyContinue; if ($childInfo -and $childInfo.ParentProcessId -eq $center.Id -and $childInfo.CommandLine -match 'cfquant\.runtime_services') { $child=Get-Process -Id $childId -ErrorAction SilentlyContinue } }; Stop-Process -InputObject $center -Force -ErrorAction Stop; $center | Wait-Process -Timeout 20 -ErrorAction Stop; if ($child) { try { $child | Wait-Process -Timeout 5 -ErrorAction Stop } catch { if (-not $child.HasExited) { Stop-Process -InputObject $child -Force -ErrorAction Stop; $child | Wait-Process -Timeout 10 -ErrorAction Stop } } }; Write-Output ('Stopped cfquant center pid=' + $center.Id); exit 0 } catch { Write-Output ('Failed to stop cfquant center: ' + $_.Exception.Message); exit 1 }"
set "STOP_RESULT=0"
if errorlevel 1 set "STOP_RESULT=1"
set "CFQUANT_STOP_ROOT="
exit /b %STOP_RESULT%

:stop_python_script
set "CFQUANT_STOP_TARGET=%~f1"
set "CFQUANT_STOP_NAME=%~2"
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$targetName=[System.IO.Path]::GetFileName($env:CFQUANT_STOP_TARGET); $module=[System.IO.Path]::GetFileNameWithoutExtension($targetName); $modulePattern='(?:^|\s)-m\s+(?:LTtx\.tx\.)?' + [regex]::Escape($module) + '(?:\s|$)'; $entry=if ($module -eq 'cfquant_pipe_hub') { 'cfquant-pipe-hub.exe' } elseif ($module -eq 'cfquant_web_server') { 'cfquant-web.exe' } else { 'LTtx_server.exe' }; $name=$env:CFQUANT_STOP_NAME; $procs=@(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { ($_.Name -like 'python*.exe' -and $_.CommandLine -and ($_.CommandLine.ToLower().Contains($targetName.ToLower()) -or $_.CommandLine -match $modulePattern)) -or $_.Name -eq $entry }); if (-not $procs.Count) { Write-Output ($name + ' not running.'); exit 0 }; $failed=$false; foreach ($p in $procs) { if (-not $p.CommandLine -or -not $p.CommandLine.ToLower().Contains($targetName.ToLower())) { $failed=$true; Write-Output ('Unverified legacy ' + $name + ' pid=' + $p.ProcessId + '; stop this instance with its original launcher before restarting.'); continue }; try { $process=Get-Process -Id $p.ProcessId -ErrorAction Stop; Stop-Process -InputObject $process -Force -ErrorAction Stop; $process | Wait-Process -Timeout 20 -ErrorAction Stop; Write-Output ('Stopped ' + $name + ' pid=' + $p.ProcessId) } catch { $failed=$true; Write-Output ('Failed to stop ' + $name + ' pid=' + $p.ProcessId + ': ' + $_.Exception.Message) } }; if ($failed) { exit 1 } else { exit 0 }"
set "STOP_RESULT=0"
if errorlevel 1 set "STOP_RESULT=1"
set "CFQUANT_STOP_TARGET="
set "CFQUANT_STOP_NAME="
exit /b %STOP_RESULT%

:stop_cfquant_web_port
set "CFQUANT_STOP_WEB_PORT=%~1"
set "CFQUANT_STOP_ROOT=%~dp0"
powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$port=[int]$env:CFQUANT_STOP_WEB_PORT; $root=($env:CFQUANT_STOP_ROOT -replace '\\\\','/').TrimEnd('/').ToLowerInvariant(); $rows=@(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue); if (-not $rows.Count) { Write-Output ('cfquant Web port ' + $port + ' not listening.'); exit 0 }; $failed=$false; $left=$false; foreach ($row in $rows) { $pidValue=$row.OwningProcess; $proc=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $pidValue) -ErrorAction SilentlyContinue; $name=if ($proc) { [string]$proc.Name } else { 'unknown' }; $cmd=if ($proc) { [string]$proc.CommandLine } else { '' }; $exe=if ($proc) { [string]$proc.ExecutablePath } else { '' }; $text=($name + ' ' + $cmd + ' ' + $exe).ToLowerInvariant(); $pathText=$text -replace '\\\\','/'; $isCfquant=$text.Contains('cfquant_web_server.py') -or $text.Contains('cfquant-web') -or $text.Contains('cfquant.exe') -or ($text.Contains('cfquant') -and ($text.Contains(' run') -or $text.Contains(' serve') -or $text.Contains(' web'))) -or ($root -and $pathText.Contains($root) -and $text.Contains('python')); if ($isCfquant) { try { $process=Get-Process -Id $pidValue -ErrorAction Stop; Stop-Process -InputObject $process -Force -ErrorAction Stop; $process | Wait-Process -Timeout 20 -ErrorAction Stop; Write-Output ('Stopped cfquant Web port owner pid=' + $pidValue) } catch { $failed=$true; Write-Output ('Failed to stop cfquant Web port owner pid=' + $pidValue + ': ' + $_.Exception.Message) } } else { $left=$true; Write-Output ('Port ' + $port + ' is owned by non-cfquant process pid=' + $pidValue + ' name=' + $name) } }; if ($failed -or $left) { exit 1 } else { exit 0 }"
set "STOP_RESULT=0"
if errorlevel 1 set "STOP_RESULT=1"
set "CFQUANT_STOP_WEB_PORT="
set "CFQUANT_STOP_ROOT="
exit /b %STOP_RESULT%

:pause_on_error
if "%CFQUANT_STOP_NO_PAUSE%"=="1" exit /b 0
if "%CFQUANT_START_NO_PAUSE%"=="1" exit /b 0
echo.
echo Stop failed. Closing in 5 seconds...
powershell -NoProfile -NonInteractive -Command "Start-Sleep -Seconds 5"
exit /b 0

:pause_on_success
if "%CFQUANT_STOP_NO_PAUSE%"=="1" exit /b 0
if "%CFQUANT_START_NO_PAUSE%"=="1" exit /b 0
if "%CFQUANT_RESTART_NO_PAUSE%"=="1" exit /b 0
echo.
echo cfquant services stopped. Closing in 5 seconds...
powershell -NoProfile -NonInteractive -Command "Start-Sleep -Seconds 5"
exit /b 0
