Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

' Starts Backend and Frontend in completely hidden background mode (isolated from IDE)
WshShell.Run "cmd /c """ & scriptDir & "\backend\start_backend.bat""", 0, False
WshShell.Run "cmd /c """ & scriptDir & "\frontend\start_frontend.bat""", 0, False
WshShell.Popup "TransM 백엔드(8000) 및 프론트엔드(5173)가 백그라운드에서 실행되었습니다." & vbCrLf & "브라우저(http://localhost:5173)로 이동합니다.", 3, "TransM 백그라운드 실행", 64
WScript.Sleep 2000
WshShell.Run "http://localhost:5173"

