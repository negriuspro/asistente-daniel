import datetime
import os
import re
import subprocess
import urllib.parse
import webbrowser
from pathlib import Path

# ─── Tool schemas (Groq / OpenAI function calling format) ───────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_website",
            "description": (
                "Abre un sitio web en el navegador o hace una búsqueda en Google. "
                "Usar cuando el usuario quiera ver YouTube, buscar algo, abrir redes "
                "sociales, ver Netflix, Twitch, noticias, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["open", "search"],
                        "description": "'open' abre un sitio directo; 'search' busca en Google",
                    },
                    "target": {
                        "type": "string",
                        "description": "Nombre del sitio (youtube, discord…) o texto a buscar",
                    },
                },
                "required": ["action", "target"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_app",
            "description": (
                "Abre una aplicación instalada en el PC. Usar para Spotify, calculadora, "
                "bloc de notas, Paint, VS Code, Discord, Chrome, Word, Excel, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "Nombre de la aplicación a abrir",
                    }
                },
                "required": ["app_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_datetime",
            "description": "Obtiene la fecha y hora actual del sistema.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

# ─── Execution ───────────────────────────────────────────────────────────────

_SITES: dict[str, str] = {
    "google":     "https://google.com",
    "youtube":    "https://youtube.com",
    "discord":    "https://discord.com",
    "twitter":    "https://twitter.com",
    "x":          "https://x.com",
    "facebook":   "https://facebook.com",
    "instagram":  "https://instagram.com",
    "github":     "https://github.com",
    "netflix":    "https://netflix.com",
    "gmail":      "https://mail.google.com",
    "maps":       "https://maps.google.com",
    "wikipedia":  "https://wikipedia.org",
    "whatsapp":   "https://web.whatsapp.com",
    "chatgpt":    "https://chat.openai.com",
    "claude":     "https://claude.ai",
    "spotify":    "https://open.spotify.com",
    "twitch":     "https://twitch.tv",
    "reddit":     "https://reddit.com",
    "tiktok":     "https://tiktok.com",
    "amazon":     "https://amazon.com",
    "roblox":     "https://roblox.com",
}

_APPS: dict[str, str] = {
    "notepad":                  "notepad.exe",
    "bloc de notas":            "notepad.exe",
    "calculadora":              "calc.exe",
    "calculator":               "calc.exe",
    "explorador":               "explorer.exe",
    "explorador de archivos":   "explorer.exe",
    "explorador de windows":    "explorer.exe",
    "archivos":                 "explorer.exe",
    "carpetas":                 "explorer.exe",
    "discord":                  "Discord.exe",
    "spotify":                  "Spotify.exe",
    "chrome":                   "chrome.exe",
    "google chrome":            "chrome.exe",
    "vscode":                   "code",
    "vs code":                  "code",
    "visual studio code":       "code",
    "paint":                    "mspaint.exe",
    "excel":                    "EXCEL.EXE",
    "word":                     "WINWORD.EXE",
    "powerpoint":               "POWERPNT.EXE",
    "teams":                    "Teams.exe",
    "terminal":                 "wt.exe",
    "cmd":                      "cmd.exe",
    "consola":                  "cmd.exe",
    "task manager":             "taskmgr.exe",
    "administrador de tareas":  "taskmgr.exe",
    "steam":                    r"C:\Program Files (x86)\Steam\steam.exe",
    "epic":                     r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win32\EpicGamesLauncher.exe",
    "epic games":               r"C:\Program Files (x86)\Epic Games\Launcher\Portal\Binaries\Win32\EpicGamesLauncher.exe",
    "minecraft":                r"C:\Program Files (x86)\Minecraft Launcher\MinecraftLauncher.exe",
    "whatsapp":                 r"C:\Users\je416\AppData\Local\WhatsApp\WhatsApp.exe",
    "telegram":                 r"C:\Users\je416\AppData\Roaming\Telegram Desktop\Telegram.exe",
    "vlc":                      r"C:\Program Files\VideoLAN\VLC\vlc.exe",
    "reproductor":              r"C:\Program Files\VideoLAN\VLC\vlc.exe",
}


def execute_tool(name: str, args: dict) -> str:
    if name == "open_website":
        return _open_website(args["action"], args["target"])
    if name == "open_app":
        return _open_app(args["app_name"])
    if name == "open_folder":
        return _open_folder(args.get("path", ""))
    if name == "get_datetime":
        return _get_datetime()
    if name == "system_control":
        return _system_control(args.get("command", ""), args.get("value", ""))
    if name == "take_screenshot":
        return _take_screenshot()
    if name == "key_press":
        return _key_press(args.get("key", ""), args.get("times", 1))
    if name == "type_text":
        return _type_text(args.get("text", ""))
    if name == "smart_home":
        from ..smarthome import smart_control
        return smart_control(args.get("device", ""), args.get("action", "on"))
    if name == "remember":
        from ..memory import remember
        return remember(args.get("key", "dato"), args.get("value", ""), args.get("category", "notes"))
    if name == "forget":
        from ..memory import forget
        return forget(args.get("key", ""))
    if name == "recall":
        from ..memory import recall
        return recall(args.get("key", ""))
    if name == "reminder":
        from ..reminder import set_reminder
        return set_reminder(args.get("message", ""), args.get("time", ""), args.get("date", "today"))
    return f"Herramienta '{name}' no encontrada."


_YT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9",
}
_YT_VIDEO_FILTER = "EgIQAQ%3D%3D"  # Videos only, no shorts


def _youtube_first_video(query: str) -> str | None:
    """Scrape YouTube search to get first real video URL (no shorts)."""
    try:
        import requests
        search_url = (
            f"https://www.youtube.com/results"
            f"?search_query={urllib.parse.quote_plus(query)}"
            f"&sp={_YT_VIDEO_FILTER}"
        )
        r = requests.get(search_url, headers=_YT_HEADERS, timeout=8)
        video_ids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', r.text)
        seen: set[str] = set()
        for vid in video_ids:
            if vid in seen:
                continue
            seen.add(vid)
            if f"/shorts/{vid}" in r.text:
                continue
            return f"https://www.youtube.com/watch?v={vid}"
    except Exception:
        pass
    return None


def _open_website(action: str, target: str) -> str:
    target_lower = target.lower().strip()

    # YouTube search → get direct video URL
    if action == "youtube" or (action == "search" and "youtube" in target_lower):
        query = target_lower.replace("youtube", "").replace("site:youtube.com", "").strip()
        video_url = _youtube_first_video(query)
        if video_url:
            webbrowser.open(video_url)
            return f"Reproduciendo en YouTube: {query}"
        # Fallback to search page
        webbrowser.open(f"https://youtube.com/results?search_query={urllib.parse.quote_plus(query)}&sp={_YT_VIDEO_FILTER}")
        return f"Búsqueda en YouTube: {query}"

    if action == "search":
        url = f"https://google.com/search?q={urllib.parse.quote(target)}"
        webbrowser.open(url)
        return f"Búsqueda abierta: {target}"

    # Direct site open — check if youtube to play directly
    url = _SITES.get(target_lower)
    if not url:
        url = f"https://{target}" if "." in target else f"https://{target_lower}.com"
    webbrowser.open(url)
    return f"Sitio abierto: {target}"


def _open_app(app_name: str) -> str:
    name_lower = app_name.lower().strip()

    # Partial match against known dict
    exe = None
    for key, val in _APPS.items():
        if key in name_lower or name_lower in key:
            exe = val
            break
    if not exe:
        exe = _APPS.get(name_lower)

    try:
        if exe == "explorer.exe" or exe is None and ("explorador" in name_lower or "explorer" in name_lower):
            subprocess.Popen(["C:\\Windows\\explorer.exe"])
        elif exe:
            subprocess.Popen(exe, shell=True)
        else:
            # Fallback: Windows START finds installed apps by name
            subprocess.Popen(f'start "" "{app_name}"', shell=True)
        return f"Aplicación abierta: {app_name}"
    except Exception as e:
        return f"No pude abrir {app_name}: {e}"


_KNOWN_FOLDERS: dict[str, str] = {
    "descargas":    str(Path.home() / "Downloads"),
    "downloads":    str(Path.home() / "Downloads"),
    "documentos":   str(Path.home() / "Documents"),
    "documents":    str(Path.home() / "Documents"),
    "escritorio":   str(Path.home() / "Desktop"),
    "desktop":      str(Path.home() / "Desktop"),
    "imágenes":     str(Path.home() / "Pictures"),
    "imagenes":     str(Path.home() / "Pictures"),
    "música":       str(Path.home() / "Music"),
    "musica":       str(Path.home() / "Music"),
    "videos":       str(Path.home() / "Videos"),
}


def _open_folder(path: str) -> str:
    path_lower = path.lower().strip()
    resolved = _KNOWN_FOLDERS.get(path_lower)

    if not resolved:
        # Try Desktop, Documents, Downloads subfolder
        candidates = [
            Path.home() / "Desktop" / path,
            Path.home() / "Documents" / path,
            Path.home() / "Downloads" / path,
            Path(path),
        ]
        for c in candidates:
            if c.exists():
                resolved = str(c)
                break

    if not resolved:
        resolved = str(Path.home() / "Desktop")

    try:
        subprocess.Popen(["C:\\Windows\\explorer.exe", resolved])
        return f"Carpeta abierta: {path}"
    except Exception as e:
        return f"No pude abrir la carpeta: {e}"


def _system_control(command: str, value: str = "") -> str:
    cmd_lower = command.lower()

    if cmd_lower in ("shutdown", "apagar"):
        subprocess.Popen("shutdown /s /t 10", shell=True)
        return "Apagando el PC en 10 segundos."

    if cmd_lower in ("restart", "reiniciar"):
        subprocess.Popen("shutdown /r /t 10", shell=True)
        return "Reiniciando el PC en 10 segundos."

    if cmd_lower in ("cancel_shutdown", "cancelar apagado"):
        subprocess.Popen("shutdown /a", shell=True)
        return "Apagado cancelado."

    if cmd_lower in ("lock", "bloquear"):
        subprocess.Popen("rundll32.exe user32.dll,LockWorkStation", shell=True)
        return "PC bloqueado."

    if cmd_lower in ("volume_up", "subir volumen"):
        steps = int(value) if str(value).isdigit() else 2
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
            pyautogui.press("volumeup", presses=steps, interval=0.05)
        except Exception:
            for _ in range(steps):
                subprocess.Popen(
                    'powershell -c "(New-Object -ComObject WScript.Shell).SendKeys([char]175)"',
                    shell=True,
                )
        return f"Volumen subido {steps} paso{'s' if steps != 1 else ''}."

    if cmd_lower in ("volume_down", "bajar volumen"):
        steps = int(value) if str(value).isdigit() else 2
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
            pyautogui.press("volumedown", presses=steps, interval=0.05)
        except Exception:
            for _ in range(steps):
                subprocess.Popen(
                    'powershell -c "(New-Object -ComObject WScript.Shell).SendKeys([char]174)"',
                    shell=True,
                )
        return f"Volumen bajado {steps} paso{'s' if steps != 1 else ''}."

    if cmd_lower in ("mute", "silenciar", "mutear"):
        try:
            import pyautogui
            pyautogui.FAILSAFE = False
            pyautogui.press("volumemute")
        except Exception:
            subprocess.Popen(
                'powershell -c "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"',
                shell=True,
            )
        return "Audio silenciado."

    if cmd_lower in ("screenshot", "captura"):
        return _take_screenshot()

    return f"Comando '{command}' no reconocido."


def _take_screenshot() -> str:
    try:
        import PIL.ImageGrab as ig
        path = Path.home() / "Desktop" / f"jarvis_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        img = ig.grab()
        img.save(str(path))
        return f"Captura guardada en el escritorio: {path.name}"
    except ImportError:
        # Fallback: Windows Snipping Tool
        subprocess.Popen("snippingtool", shell=True)
        return "Abriendo herramienta de captura."
    except Exception as e:
        return f"No pude tomar captura: {e}"


def _key_press(key: str, times: int = 1) -> str:
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.press(key, presses=int(times), interval=0.05)
        return f"Tecla '{key}' presionada {times} veces."
    except Exception as e:
        return f"Error al presionar tecla: {e}"


def _type_text(text: str) -> str:
    try:
        import pyautogui
        pyautogui.FAILSAFE = False
        pyautogui.write(text, interval=0.04)
        return f"Texto escrito: {text}"
    except Exception as e:
        return f"Error al escribir: {e}"


def _get_datetime() -> str:
    now = datetime.datetime.now()
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    meses = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    dia_semana = dias[now.weekday()]
    mes = meses[now.month - 1]
    return f"Hoy es {dia_semana} {now.day} de {mes} de {now.year}, son las {now.strftime('%H:%M')}."
