' Cria um atalho "Recuperador de Tributos" na Área de Trabalho.
Set fso = CreateObject("Scripting.FileSystemObject")
pasta = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
desktop = sh.SpecialFolders("Desktop")
Set lnk = sh.CreateShortcut(desktop & "\Recuperador de Tributos.lnk")
lnk.TargetPath = pasta & "\python\pythonw.exe"
lnk.Arguments = """" & pasta & "\sistema\launcher.py"""
lnk.WorkingDirectory = pasta
lnk.IconLocation = pasta & "\sistema\app\recuperador.ico,0"
lnk.Description = "Recuperador de Tributos"
lnk.Save
MsgBox "Atalho criado na Área de Trabalho.", 64, "Recuperador de Tributos"
