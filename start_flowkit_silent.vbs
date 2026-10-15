Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
currentDir = fso.GetParentFolderName(WScript.ScriptFullName)

venvPythonw = currentDir & "\.venv\Scripts\pythonw.exe"
runnerScript = currentDir & "\flowkit\run_background.py"
flowkitDir = currentDir & "\flowkit"

If fso.FileExists(venvPythonw) Then
    cmd = """" & venvPythonw & """ """ & runnerScript & """"
Else
    cmd = "pythonw.exe """ & runnerScript & """"
End If

WshShell.CurrentDirectory = flowkitDir
WshShell.Run cmd, 0, False
