@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'official_site[\\\\/]backend[\\\\/]server.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo cfquant official site stopped if it was running.
