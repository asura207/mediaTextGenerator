Set oWS = WScript.CreateObject("WScript.Shell")
sLinkFile = oWS.SpecialFolders("Desktop") & "\TransM - AI Subtitle Studio.lnk"
Set oLink = oWS.CreateShortcut(sLinkFile)

' Get Project Root directory
Set fso = CreateObject("Scripting.FileSystemObject")
sScriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
sRootDir = fso.GetParentFolderName(sScriptDir)

oLink.TargetPath = sRootDir & "\start.bat"
oLink.WorkingDirectory = sRootDir
oLink.Description = "TransM - AI Subtitle Studio Launcher"
oLink.WindowStyle = 1
oLink.Save

WScript.Echo "[OK] 바탕화면에 'TransM - AI Subtitle Studio' 바로가기가 생성되었습니다."
