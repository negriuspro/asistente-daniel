import logging
import os
import threading
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

log = logging.getLogger("jarvis.google_home")

_GH_HOST = os.environ.get("GOOGLE_HOME_HOST", "")
_GH_PORT = int(os.environ.get("GOOGLE_HOME_PORT", "8009"))

_cast = None
_lock = threading.Lock()


def _get_cast():
    global _cast
    if not _GH_HOST:
        return None
    with _lock:
        if _cast is not None:
            try:
                if _cast.socket_client and _cast.socket_client.is_connected:
                    return _cast
            except Exception:
                pass
        try:
            import pychromecast
            cast = pychromecast.get_chromecast_from_host(
                (_GH_HOST, _GH_PORT, None, None, None),
                timeout=5,
            )
            cast.wait(timeout=5)
            _cast = cast
            log.info("Google Home conectado: %s", cast.cast_info)
            return _cast
        except Exception as e:
            log.error("No se pudo conectar a Google Home: %s", e)
            return None


def google_home_control(command: str, value: str = "") -> str:
    if not _GH_HOST:
        return "Google Home no configurado. Agrega GOOGLE_HOME_HOST en el archivo .env."

    cast = _get_cast()
    if not cast:
        return "No pude conectarme al Google Home. Verifica que esté encendido y en la misma red."

    cmd = command.lower().strip()

    try:
        if cmd == "volume_up":
            steps = int(value) if str(value).isdigit() else 2
            vol = min(1.0, (cast.status.volume_level or 0.5) + steps * 0.05)
            cast.set_volume(vol)
            return f"Volumen Google Home subido a {int(vol * 100)}%."

        if cmd == "volume_down":
            steps = int(value) if str(value).isdigit() else 2
            vol = max(0.0, (cast.status.volume_level or 0.5) - steps * 0.05)
            cast.set_volume(vol)
            return f"Volumen Google Home bajado a {int(vol * 100)}%."

        if cmd == "volume_set":
            pct = max(0, min(100, int(value or 50)))
            cast.set_volume(pct / 100)
            return f"Volumen Google Home al {pct}%."

        if cmd == "mute":
            cast.set_volume_muted(not cast.status.volume_muted)
            estado = "silenciado" if not cast.status.volume_muted else "con sonido"
            return f"Google Home {estado}."

        if cmd == "pause":
            cast.media_controller.pause()
            return "Google Home pausado."

        if cmd == "play":
            cast.media_controller.play()
            return "Google Home reproduciendo."

        if cmd == "stop":
            cast.media_controller.stop()
            return "Google Home detenido."

        if cmd == "youtube":
            from pychromecast.controllers.youtube import YouTubeController
            yt = YouTubeController()
            cast.register_handler(yt)
            if value:
                from .tools import _youtube_first_video
                url = _youtube_first_video(value)
                if url:
                    vid_id = url.split("v=")[-1]
                    yt.play_video(vid_id)
                    return f"Reproduciendo '{value}' en Google Home."
            yt.launch()
            return "YouTube abierto en Google Home."

        if cmd == "spotify":
            try:
                from pychromecast.controllers.spotify import SpotifyController
                sp = SpotifyController()
                cast.register_handler(sp)
                sp.launch_app()
                return "Spotify abierto en Google Home."
            except ImportError:
                return "Spotify Controller no disponible. Instala pychromecast[spotify]."

        if cmd == "status":
            vol = int((cast.status.volume_level or 0) * 100)
            app = cast.status.display_name or "inactivo"
            muted = "silenciado" if cast.status.volume_muted else "con sonido"
            return f"Google Home: {app}, volumen {vol}%, {muted}."

    except Exception as e:
        log.error("Google Home error: %s", e)
        return f"Error controlando Google Home: {e}"

    return f"Comando de Google Home '{command}' no reconocido."
