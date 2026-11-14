Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
WshShell.CurrentDirectory = scriptDir

backendBat = fso.BuildPath(scriptDir, "backend\start_backend.bat")
frontendBat = fso.BuildPath(scriptDir, "frontend\start_frontend.bat")
nodeModulesDir = fso.BuildPath(scriptDir, "frontend\node_modules")

' Starts Backend and Frontend in completely hidden background mode (safe for Korean/space paths)
WshShell.Run "cmd.exe /c " & Chr(34) & Chr(34) & backendBat & Chr(34) & Chr(34), 0, False

targetUrl = "http://localhost:8000"
If fso.FolderExists(nodeModulesDir) Then
    WshShell.Run "cmd.exe /c " & Chr(34) & Chr(34) & frontendBat & Chr(34) & Chr(34), 0, False
    targetUrl = "http://localhost:5173"
End If

WshShell.Popup "TransM 백엔드(8000) 및 프론트엔드(5173)가 백그라운드에서 실행되었습니다." & vbCrLf & "브라우저(" & targetUrl & ")로 이동합니다.", 3, "TransM 백그라운드 실행", 64
WScript.Sleep 2500
WshShell.Run targetUrl

