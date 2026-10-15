@echo off
title Stop FlowKit Bridge
echo ===============================================================
echo Stopping FlowKit Bridge (Ports 8100 ^& 9222)...
echo ===============================================================

powershell -NoProfile -Command "$pids = Get-NetTCPConnection -LocalPort 8100,9222 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; if ($pids) { foreach ($p in $pids) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue; Write-Host ('[OK] Terminated FlowKit PID ' + $p) } } else { Write-Host '[INFO] No running FlowKit process found on ports 8100 / 9222.' }"

echo ===============================================================
echo Done.
ping -n 3 127.0.0.1 >nul
