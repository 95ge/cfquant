@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHONDONTWRITEBYTECODE=1"
set "PYTHONIOENCODING=utf-8"
if not defined CFQUANT_START_WAIT_SECONDS set "CFQUANT_START_WAIT_SECONDS=90"
set "LOG_DIR=%~dp0log"
set "START_LOG=%LOG_DIR%\cfquant_startup.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul
set "WEB_LOG_RUN_ID="
for /f "usebackq delims=" %%T in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format 'yyyyMMdd_HHmmss_ffff'"`) do set "WEB_LOG_RUN_ID=%%T"
if not defined WEB_LOG_RUN_ID set "WEB_LOG_RUN_ID=%RANDOM%"
set "WEB_LOG_RUN_ID=%WEB_LOG_RUN_ID%_%RANDOM%"
set "WEB_STDOUT=%LOG_DIR%\cfquant_web_server.%WEB_LOG_RUN_ID%.stdout.log"
set "WEB_STDERR=%LOG_DIR%\cfquant_web_server.%WEB_LOG_RUN_ID%.stderr.log"
call :log "start_cfquant.bat invoked"

set "PYTHON_EXE=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%~dp0cfquant_web_server.py" (
    echo [ERROR] cfquant_web_server.py not found in "%~dp0".
    call :log "cfquant_web_server.py not found"
    call :show_logs
    call :pause_on_error
    endlocal
    exit /b 1
)

"%PYTHON_EXE%" --version >>"%START_LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not available. Please install Python or create .venv first.
    echo [ERROR] Tried: %PYTHON_EXE%
    call :log "python unavailable"
    call :show_logs
    call :pause_on_error
    endlocal
    exit /b 1
)

call :ensure_cfquant_package
if errorlevel 1 (
    echo [ERROR] cfquant package is not installed and automatic installation failed.
    call :show_logs
    call :pause_on_error
    endlocal
    exit /b 1
)

set "WEB_PORT=8765"
set "CFQUANT_START_ROOT=%~dp0"
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=8765; $root=$env:CFQUANT_START_ROOT; $files=@((Join-Path $root 'runtime\config\cfquant_web_config.json'), (Join-Path $root 'cfquant_web_config.json')); foreach ($f in $files) { if (Test-Path -LiteralPath $f) { try { $c=Get-Content -Raw -LiteralPath $f | ConvertFrom-Json; if ($c.web_port) { $p=[int]$c.web_port } elseif ($c.web_server -and $c.web_server.port) { $p=[int]$c.web_server.port }; break } catch {} } }; Write-Output $p"`) do set "WEB_PORT=%%P"
set "CFQUANT_START_ROOT="
if not defined WEB_PORT set "WEB_PORT=8765"
if defined CFQUANT_WEB_PORT set "WEB_PORT=%CFQUANT_WEB_PORT%"
if defined CFQUANT_START_WEB_PORT set "WEB_PORT=%CFQUANT_START_WEB_PORT%"
set "CFQUANT_WEB_PORT=%WEB_PORT%"
if not defined CFQUANT_START_REUSE_WAIT_SECONDS set "CFQUANT_START_REUSE_WAIT_SECONDS=10"
call :log "web stdout/stderr run logs stdout=%WEB_STDOUT% stderr=%WEB_STDERR%"

if /i "%~1"=="--foreground" goto foreground
if /i "%~1"=="--debug" goto foreground

echo Starting cfquant web dashboard on port %WEB_PORT%...
echo Logs:
echo   %WEB_STDOUT%
echo   %WEB_STDERR%
echo The web server will start LTtx first, then start PipeHub when the saved mode needs it.
call :log "starting web dashboard port=%WEB_PORT%"

call :is_port_open %WEB_PORT%
if not errorlevel 1 (
    call :wait_for_cfquant_web %WEB_PORT% %CFQUANT_START_REUSE_WAIT_SECONDS%
    if not errorlevel 1 (
        echo cfquant web dashboard already runs on %WEB_PORT%, reuse it.
        call :log "existing cfquant web reused port=%WEB_PORT%"
        call :open_browser
        endlocal
        exit /b 0
    )
    echo [ERROR] Port %WEB_PORT% is already used by another process, not cfquant.
    echo [ERROR] Please stop that process or set CFQUANT_WEB_PORT to another port.
    call :log "port occupied by non-cfquant process port=%WEB_PORT%"
    call :show_port_owner
    call :pause_on_error
    endlocal
    exit /b 1
)

start "cfquant Web" /min cmd /d /s /c ""%PYTHON_EXE%" "%~dp0cfquant_web_server.py" --port %WEB_PORT% 1>>"%WEB_STDOUT%" 2>>"%WEB_STDERR%""

call :wait_for_cfquant_web %WEB_PORT% %CFQUANT_START_WAIT_SECONDS%
if errorlevel 1 (
    echo [ERROR] cfquant web dashboard did not start within %CFQUANT_START_WAIT_SECONDS% seconds.
    echo [ERROR] Please check the logs below.
    call :log "web dashboard failed to become ready port=%WEB_PORT%"
    call :show_logs
    call :pause_on_error
    endlocal
    exit /b 1
)

call :open_browser
endlocal
exit /b 0

:open_browser
if not "%CFQUANT_START_NO_BROWSER%"=="1" start "" "http://127.0.0.1:%WEB_PORT%/"
echo cfquant started. Open http://127.0.0.1:%WEB_PORT%/ if the browser did not open.
call :log "start completed port=%WEB_PORT%"
exit /b 0

:foreground
echo Starting cfquant web dashboard in foreground mode on port %WEB_PORT%...
echo Press Ctrl+C to stop the service.
echo.
call :log "starting foreground web dashboard port=%WEB_PORT%"
"%PYTHON_EXE%" "%~dp0cfquant_web_server.py" --port %WEB_PORT%
set "WEB_EXIT_CODE=%errorlevel%"
if not "%WEB_EXIT_CODE%"=="0" (
    echo.
    echo [ERROR] cfquant web dashboard exited with code %WEB_EXIT_CODE%.
    call :log "foreground web dashboard exited code=%WEB_EXIT_CODE%"
    call :show_logs
    call :pause_on_error
)
endlocal & exit /b %WEB_EXIT_CODE%

:ensure_cfquant_package
echo Checking the cfquant package in the selected Python environment...
call :log "checking cfquant package python=%PYTHON_EXE%"
set "CFQUANT_INSTALL_HELPER=%~dp0cfquant\_editable_install.py"
if not exist "%CFQUANT_INSTALL_HELPER%" (
    echo [ERROR] cfquant install helper was not found: "%CFQUANT_INSTALL_HELPER%"
    call :log "cfquant install helper missing"
    set "CFQUANT_INSTALL_HELPER="
    exit /b 1
)
"%PYTHON_EXE%" "%CFQUANT_INSTALL_HELPER%" . >>"%START_LOG%" 2>&1
if errorlevel 1 (
    call :log "cfquant package check or installation failed"
    set "CFQUANT_INSTALL_HELPER="
    exit /b 1
)
echo cfquant package is ready.
call :log "cfquant package ready"
set "CFQUANT_INSTALL_HELPER="
exit /b 0

:is_port_open
set "CFQUANT_START_PORT=%~1"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$port=[int]$env:CFQUANT_START_PORT; try { $client=[Net.Sockets.TcpClient]::new(); $iar=$client.BeginConnect('127.0.0.1',$port,$null,$null); if ($iar.AsyncWaitHandle.WaitOne(500,$false)) { $client.EndConnect($iar); $client.Close(); exit 0 }; $client.Close(); exit 1 } catch { exit 1 }"
set "PORT_RESULT=%errorlevel%"
set "CFQUANT_START_PORT="
exit /b %PORT_RESULT%

:wait_for_cfquant_web
set "CFQUANT_START_PORT=%~1"
set "CFQUANT_START_WAIT=%~2"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$port=[int]$env:CFQUANT_START_PORT; $wait=[int]$env:CFQUANT_START_WAIT; $deadline=(Get-Date).AddSeconds($wait); $url='http://127.0.0.1:' + $port + '/api/health'; while ((Get-Date) -lt $deadline) { try { $req=[Net.WebRequest]::Create($url); $req.Method='GET'; $req.Timeout=1000; $req.ReadWriteTimeout=1000; $req.UserAgent='cfquant-start'; $res=$req.GetResponse(); try { if ([int]$res.StatusCode -eq 200) { $reader=[IO.StreamReader]::new($res.GetResponseStream(), [Text.Encoding]::UTF8); $content=$reader.ReadToEnd(); $reader.Close(); $payload=$content | ConvertFrom-Json; if ($payload.ok -eq $true -and $payload.data.status -eq 'ok') { exit 0 } } } finally { $res.Close() } } catch {}; Start-Sleep -Milliseconds 500 }; exit 1"
set "WAIT_RESULT=%errorlevel%"
set "CFQUANT_START_PORT="
set "CFQUANT_START_WAIT="
exit /b %WAIT_RESULT%

:show_port_owner
set "CFQUANT_START_PORT=%WEB_PORT%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$port=[int]$env:CFQUANT_START_PORT; try { $rows=Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue; foreach ($row in $rows) { $pidValue=$row.OwningProcess; $name='unknown'; try { $name=(Get-Process -Id $pidValue -ErrorAction Stop).ProcessName } catch {}; Write-Output ('Port owner PID={0} Process={1}' -f $pidValue,$name) } } catch {}"
set "CFQUANT_START_PORT="
exit /b 0

:show_logs
echo.
echo ===== startup log =====
if exist "%START_LOG%" powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -LiteralPath $env:START_LOG -Tail 40 -ErrorAction SilentlyContinue"
echo.
echo ===== stderr log =====
if exist "%WEB_STDERR%" powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -LiteralPath $env:WEB_STDERR -Tail 80 -ErrorAction SilentlyContinue"
echo.
exit /b 0

:pause_on_error
if "%CFQUANT_START_NO_PAUSE%"=="1" exit /b 0
echo.
echo This window stays open because startup failed.
pause
exit /b 0

:log
set "CFQUANT_LOG_TS="
for /f "usebackq delims=" %%T in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format 'yyyy-MM-ddTHH:mm:ss'"`) do set "CFQUANT_LOG_TS=%%T"
if not defined CFQUANT_LOG_TS set "CFQUANT_LOG_TS=%time%"
>>"%START_LOG%" echo [%CFQUANT_LOG_TS%] %~1
set "CFQUANT_LOG_TS="
exit /b 0
