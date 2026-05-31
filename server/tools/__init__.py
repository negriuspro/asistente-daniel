"""
Jarvis tool executor — Linux/server-mode compatible.

PC-only features (key_press, open_app, volume control) return an informational
message instead of crashing, because Jarvis runs on a headless Ubuntu server.

open_website returns the resolved URL so that ai_agent.py can forward it to
the browser client via the WebSocket open_url field.
"""

import datetime
import logging
import urllib.parse
from pathlib import Path

log = logging.getLogger("jarvis.tools")

# ─── Tool schemas (Groq / OpenAI function-calling format) ────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "open_website",
            "description": (
                "Abre un sitio web en el navegador del cliente o hace una búsqueda. "
                "Usar cuando el usuario quiera ver YouTube, buscar algo, abrir redes "
                "sociales, ver Netflix, Twitch, noticias, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["open", "search", "youtube"],
                        "description": "'open' abre un sitio directo; 'search' busca en Google; 'youtube' busca video",
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
            "name": "get_datetime",
            "description": "Obtiene la fecha y hora actual del sistema.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

# ─── Sites directory ─────────────────────────────────────────────────────────

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

_YT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9",
}
_YT_VIDEO_FILTER = "EgIQAQ%3D%3D"  # Videos only, no shorts

_NOT_AVAILABLE = "Esta función no está disponible en modo servidor."


# ─── Execution ───────────────────────────────────────────────────────────────

def execute_tool(name: str, args: dict) -> str:
    if name == "open_website":
        return _open_website(args["action"], args["target"])
    if name == "open_app":
        app = args.get("app_name", "")
        log.info("open_app solicitado: '%s' — modo servidor", app)
        return _NOT_AVAILABLE
    if name == "open_folder":
        return _NOT_AVAILABLE
    if name == "get_datetime":
        return _get_datetime()
    if name == "system_control":
        return _system_control(args.get("command", ""), str(args.get("value", "")))
    if name == "take_screenshot":
        return _take_screenshot()
    if name == "key_press":
        log.info("key_press solicitado: '%s' — modo servidor", args.get("key"))
        return _NOT_AVAILABLE
    if name == "type_text":
        log.info("type_text solicitado — modo servidor")
        return _NOT_AVAILABLE
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
    if name == "system_info":
        return _system_info()
    return f"Herramienta '{name}' no encontrada."


# ─── open_website ────────────────────────────────────────────────────────────

def _youtube_first_video(query: str) -> str | None:
    """Scrape YouTube search to get first real video URL (no shorts)."""
    import re
    try:
        import httpx
        search_url = (
            f"https://www.youtube.com/results"
            f"?search_query={urllib.parse.quote_plus(query)}"
            f"&sp={_YT_VIDEO_FILTER}"
        )
        with httpx.Client(timeout=8, follow_redirects=True) as client:
            r = client.get(search_url, headers=_YT_HEADERS)
        video_ids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', r.text)
        seen: set[str] = set()
        for vid in video_ids:
            if vid in seen:
                continue
            seen.add(vid)
            if f"/shorts/{vid}" in r.text:
                continue
            return f"https://www.youtube.com/watch?v={vid}"
    except Exception as e:
        log.warning("YouTube scrape falló: %s", e)
    return None


def _open_website(action: str, target: str) -> str:
    """Returns the resolved URL. The caller (ai_agent) forwards it to the client."""
    target_lower = target.lower().strip()

    if action in ("youtube",) or (action == "search" and "youtube" in target_lower):
        query = target_lower.replace("youtube", "").replace("site:youtube.com", "").strip() or target_lower
        video_url = _youtube_first_video(query)
        url = video_url or (
            f"https://youtube.com/results?search_query={urllib.parse.quote_plus(query)}"
            f"&sp={_YT_VIDEO_FILTER}"
        )
        log.info("YouTube URL: %s", url)
        return url

    if action == "search":
        url = f"https://google.com/search?q={urllib.parse.quote(target)}"
        log.info("Búsqueda URL: %s", url)
        return url

    url = _SITES.get(target_lower)
    if not url:
        url = f"https://{target}" if "." in target else f"https://{target_lower}.com"
    log.info("Sitio URL: %s", url)
    return url


# ─── system_control ──────────────────────────────────────────────────────────

def _system_control(command: str, value: str = "") -> str:
    cmd = command.lower()

    if cmd in ("volume_up", "volume_down", "mute", "silenciar", "mutear",
               "subir volumen", "bajar volumen"):
        return (
            "Control de volumen del PC no disponible en modo servidor. "
            "Usa los comandos de TV o Google Home para controlar el volumen."
        )

    if cmd in ("shutdown", "apagar"):
        return "Apagado del sistema desactivado en modo servidor Docker."

    if cmd in ("restart", "reiniciar"):
        return "Reinicio del sistema desactivado en modo servidor Docker."

    if cmd in ("cancel_shutdown", "cancelar apagado"):
        return "No hay apagado pendiente."

    if cmd in ("lock", "bloquear"):
        return "Bloqueo de pantalla no disponible en modo servidor."

    if cmd in ("screenshot", "captura"):
        return _take_screenshot()

    return f"Comando '{command}' no disponible en modo servidor."


# ─── screenshot ──────────────────────────────────────────────────────────────

def _take_screenshot() -> str:
    try:
        from PIL import ImageGrab
        path = Path("/tmp") / f"jarvis_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        img = ImageGrab.grab()
        img.save(str(path))
        return f"Captura guardada en: {path.name}"
    except Exception as e:
        return f"Captura de pantalla no disponible en modo servidor: {e}"


# ─── datetime ────────────────────────────────────────────────────────────────

def _system_info() -> str:
    import psutil
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory()
    try:
        disk = psutil.disk_usage("/").percent
    except Exception:
        disk = 0
    batt = psutil.sensors_battery()
    batt_str = ""
    if batt:
        plug = "enchufado" if batt.power_plugged else "en batería"
        batt_str = f", batería {batt.percent:.0f}% ({plug})"
    return (
        f"CPU: {cpu}% | RAM: {mem.percent:.0f}% ({mem.used/1024**3:.1f}/{mem.total/1024**3:.1f} GB)"
        f" | Disco: {disk:.0f}%{batt_str}"
    )


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
