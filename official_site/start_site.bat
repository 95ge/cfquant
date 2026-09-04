@echo off
setlocal
cd /d "%~dp0\.."
if "%CFQUANT_SITE_HOST%"=="" set "CFQUANT_SITE_HOST=127.0.0.1"
if "%CFQUANT_SITE_PORT%"=="" set "CFQUANT_SITE_PORT=8780"
if "%CFQUANT_SITE_ADMIN_USER%"=="" set "CFQUANT_SITE_ADMIN_USER=admin"
if "%CFQUANT_SITE_ADMIN_PASSWORD%"=="" echo Warning: CFQUANT_SITE_ADMIN_PASSWORD is not set. Admin login will be disabled.
start "cfquant official site" /min python official_site\backend\server.py --host %CFQUANT_SITE_HOST% --port %CFQUANT_SITE_PORT%
echo cfquant official site started:
echo http://%CFQUANT_SITE_HOST%:%CFQUANT_SITE_PORT%/
echo http://%CFQUANT_SITE_HOST%:%CFQUANT_SITE_PORT%/95ge
