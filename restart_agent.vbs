Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Set working directory to this script's directory
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

' 1. Stop any running AniStory AI agent processes (port 8088 listeners + run.py / backend.app:app reloader & workers)
stopCmd = "powershell -NoProfile -WindowStyle Hidden -Command """ & _
    "$pids = @(); " & _
    "Get-NetTCPConnection -LocalPort 8088 -ErrorAction SilentlyContinue | ForEach-Object { if ($_.OwningProcess -gt 4) { $pids += $_.OwningProcess } }; " & _
    "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -match 'run\.py|backend\.app:app' } | ForEach-Object { $pids += $_.ProcessId }; " & _
    "$pids | Select-Object -Unique | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }" & _
    """"
WshShell.Run stopCmd, 0, True

' Wait briefly for port 8088 and child processes to fully release
WScript.Sleep 1500

' 2. Detect python executable (virtualenv or system python)
Dim pythonExe
If fso.FileExists(scriptDir & "\venv\Scripts\python.exe") Then
    pythonExe = """" & scriptDir & "\venv\Scripts\python.exe"""
ElseIf fso.FileExists(scriptDir & "\.venv\Scripts\python.exe") Then
    pythonExe = """" & scriptDir & "\.venv\Scripts\python.exe"""
Else
    pythonExe = "python"
End If

' 3. Collect any optional arguments passed to restart_agent.vbs
args = ""
For i = 0 To WScript.Arguments.Count - 1
    args = args & " " & WScript.Arguments(i)
Next

' 4. Relaunch agent hidden in background (0 = SW_HIDE, False = async)
WshShell.Run pythonExe & " run.py" & args, 0, False
