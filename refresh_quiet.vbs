' Runs refresh_quiet.bat with no console window, so the hourly scheduled task
' does not flash a black box over whatever you are doing.
Dim shell, fso, here
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = here
shell.Run """" & here & "\refresh_quiet.bat""", 0, False
