Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Set working directory to this script's directory
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

' 1. Stop any running AniStory AI agent processes (ports 8088-8097 listeners + run.py / backend.app:app reloader & orphaned multiprocessing workers)
stopCmd = "powershell -NoProfile -WindowStyle Hidden -Command """ & _
    "$pids = New-Object System.Collections.Generic.HashSet[int]; " & _
    "Get-NetTCPConnection -LocalPort (8088..8097) -State Listen -ErrorAction SilentlyContinue | ForEach-Object { if ($_.OwningProcess -gt 4) { [void]$pids.Add([int]$_.OwningProcess) } }; " & _
    "$pyProcs = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'python*' }); " & _
    "foreach ($p in $pyProcs) { if ($p.CommandLine -match '(?<![a-zA-Z0-9_])run\.py\b|backend\.app:app' -and $p.CommandLine -notmatch 'flowkit[\\/]run_background\.py') { [void]$pids.Add([int]$p.ProcessId) } }; " & _
    "do { $added = $false; foreach ($p in $pyProcs) { $pidInt = [int]$p.ProcessId; if (-not $pids.Contains($pidInt)) { $isChild = $pids.Contains([int]$p.ParentProcessId); if (-not $isChild -and $p.CommandLine -match 'parent_pid=(\d+)') { $isChild = $pids.Contains([int]$Matches[1]) }; if ($isChild) { [void]$pids.Add($pidInt); $added = $true } } } } while ($added); " & _
    "foreach ($targetPid in $pids) { Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue }; " & _
    "for ($i = 0; $i -lt 24; $i++) { if (-not (Get-NetTCPConnection -LocalPort (8088..8097) -State Listen -ErrorAction SilentlyContinue)) { break }; Start-Sleep -Milliseconds 250 }" & _
    """"
WshShell.Run stopCmd, 0, True

' 2. Detect python executable (virtualenv or system python)
Dim pythonExe
If fso.FileExists(scriptDir & "\venv\Scripts\python.exe") Then
    pythonExe = """" & scriptDir & "\venv\Scripts\python.exe"""
ElseIf fso.FileExists(scriptDir & "\.venv\Scripts\python.exe") Then
    pythonExe = """" & scriptDir & "\.venv\Scripts\python.exe"""
Else
    pythonExe = "python"
End If

' 3. Collect any optional arguments passed to restart_agent.vbs (e.g. --no-browser, --port=8090)
args = ""
For i = 0 To WScript.Arguments.Count - 1
    args = args & " " & WScript.Arguments(i)
Next

' 4. Relaunch agent hidden in background, logging output to output\agent.log for troubleshooting
logDir = scriptDir & "\output"
If Not fso.FolderExists(logDir) Then fso.CreateFolder(logDir)
logFile = logDir & "\agent.log"
launchCmd = "cmd /c set PYTHONIOENCODING=utf-8 && " & pythonExe & " run.py" & args & " > """ & logFile & """ 2>&1"
WshShell.Run launchCmd, 0, False

' 5. Verify the server came up (poll ports 8088-8097 for up to ~25s); alert only on failure
checkCmd = "powershell -NoProfile -WindowStyle Hidden -Command """ & _
    "for ($i = 0; $i -lt 50; $i++) { if (Get-NetTCPConnection -LocalPort (8088..8097) -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.OwningProcess -gt 4 }) { exit 0 }; Start-Sleep -Milliseconds 500 }; exit 1" & _
    """"
rc = WshShell.Run(checkCmd, 0, True)
If rc <> 0 Then
    WshShell.Popup "AniStory AI agent did not start within 25 seconds." & vbCrLf & vbCrLf & _
        "See the log for details:" & vbCrLf & logFile, 15, "AniStory AI - Restart Failed", 48
End If
