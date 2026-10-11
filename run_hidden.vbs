Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

' Set working directory to this script's directory
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

' Detect python executable (virtualenv or system python)
Dim pythonExe
If fso.FileExists(scriptDir & "\venv\Scripts\python.exe") Then
    pythonExe = """" & scriptDir & "\venv\Scripts\python.exe"""
ElseIf fso.FileExists(scriptDir & "\.venv\Scripts\python.exe") Then
    pythonExe = """" & scriptDir & "\.venv\Scripts\python.exe"""
Else
    pythonExe = "python"
End If

' Collect any optional arguments
args = ""
For i = 0 To WScript.Arguments.Count - 1
    args = args & " " & WScript.Arguments(i)
Next

' 0 = Hide window (SW_HIDE), False = Return immediately without waiting
WshShell.Run pythonExe & " run.py" & args, 0, False
