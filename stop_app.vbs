Set WshShell = CreateObject("WScript.Shell")

' Stop any process listening on port 8088 as well as run.py / uvicorn reloader processes
cmd = "powershell -NoProfile -WindowStyle Hidden -Command """ & _
    "$pids = @(); " & _
    "Get-NetTCPConnection -LocalPort 8088 -ErrorAction SilentlyContinue | ForEach-Object { if ($_.OwningProcess -gt 4) { $pids += $_.OwningProcess } }; " & _
    "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -match 'run\.py|backend\.app:app' } | ForEach-Object { $pids += $_.ProcessId }; " & _
    "$pids | Select-Object -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }" & _
    """"
WshShell.Run cmd, 0, True
