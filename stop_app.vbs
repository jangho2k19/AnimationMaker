Set WshShell = CreateObject("WScript.Shell")

' Stop any process listening on port 8088 (default port for run.py)
cmd = "powershell -NoProfile -WindowStyle Hidden -Command ""Get-NetTCPConnection -LocalPort 8088 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }"""
WshShell.Run cmd, 0, True
