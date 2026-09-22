Option Explicit

Dim shell, fso, scriptPath, command, i
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

If WScript.Arguments.Count < 1 Then WScript.Quit 2
scriptPath = fso.GetAbsolutePathName(WScript.Arguments(0))
If Not fso.FileExists(scriptPath) Then WScript.Quit 3

command = "cmd.exe /d /c call """ & scriptPath & """"
For i = 1 To WScript.Arguments.Count - 1
  command = command & " """ & Replace(WScript.Arguments(i), """""", """""""""") & """"
Next
shell.CurrentDirectory = fso.GetParentFolderName(scriptPath)
WScript.Quit shell.Run(command & " --no-pause", 0, True)
