' Abre o Recuperador de Tributos sem janela de console.
Set fso = CreateObject("Scripting.FileSystemObject")
pasta = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = pasta
sh.Run """" & pasta & "\python\pythonw.exe"" """ & pasta & "\sistema\launcher.py""", 0, False
