Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\Praashu\.gemini\antigravity\scratch\laptop-remote-hub"
WshShell.Run """C:\Users\Praashu\AppData\Local\Programs\Python\Python312\python.exe"" supervisor.py", 0, False
