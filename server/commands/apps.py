import subprocess

_APPS: dict[str, str] = {
    "notepad":      "notepad.exe",
    "calculadora":  "calc.exe",
    "explorador":   "explorer.exe",
    "discord":      "Discord.exe",
    "spotify":      "Spotify.exe",
    "chrome":       "chrome.exe",
    "vscode":       "code",
    "paint":        "mspaint.exe",
    "excel":        "EXCEL.EXE",
    "word":         "WINWORD.EXE",
    "teams":        "Teams.exe",
}


def match(text: str) -> str | None:
    if not text.startswith("abre "):
        return None
    name = text[5:].strip()
    exe = _APPS.get(name)
    if not exe:
        return None
    try:
        subprocess.Popen(exe, shell=True)
        return f"Abriendo {name}"
    except Exception:
        return f"No pude abrir {name}"
