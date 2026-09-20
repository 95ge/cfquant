Option Explicit
Dim shell, fso, scriptPath
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptPath = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "stop_cfquant.bat")
If fso.FileExists(scriptPath) Then
  shell.Run "wscript.exe """ & fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "run_hidden_batch.vbs") & """ """ & scriptPath & """", 0, False
End If
