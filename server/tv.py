import logging
import threading

import pychromecast

log = logging.getLogger("jarvis.tv")

# Nombres posibles de la TV en la red (insensible a mayúsculas)
_TV_NAMES = {"tv de dormitorio", "dormitorio"}

_cast = None
_lock = threading.Lock()


def _discover_tv():
    """Busca la TV en la red por nombre. Devuelve (host, port) o (None, None)."""
    try:
        services, browser = pychromecast.discovery.discover_chromecasts(timeout=6)
        pychromecast.discovery.stop_discovery(browser)
        for s in services:
            if any(n in s.friendly_name.lower() for n in _TV_NAMES):
                log.info("TV descubierta: %s @ %s", s.friendly_name, s.host)
                return s.host, s.port
        # Fallback: primer dispositivo encontrado si solo hay uno
        if len(services) == 1:
            s = services[0]
            log.info("Un solo dispositivo Chromecast: %s @ %s", s.friendly_name, s.host)
            return s.host, s.port
    except Exception as e:
        log.error("Error descubriendo TV: %s", e)
    return None, None


def _get_cast():
    global _cast
    with _lock:
        if _cast is not None:
            try:
                if _cast.socket_client and _cast.socket_client.is_connected:
                    return _cast
            except Exception:
                pass
        host, port = _discover_tv()
        if not host:
            log.error("No se encontró la TV en la red.")
            return None
        try:
            cast = pychromecast.get_chromecast_from_host(
                (host, port, None, None, None),
                timeout=5,
            )
            cast.wait(timeout=5)
            _cast = cast
            log.info("TV conectada: %s @ %s", cast.cast_info.friendly_name, host)
            return _cast
        except Exception as e:
            log.error("No se pudo conectar a la TV: %s", e)
            return None


def tv_control(command: str, value: str = "") -> str:
    cast = _get_cast()
    if not cast:
        return "No pude conectarme a la TV. Verifica que esté encendida y en la misma red."

    cmd = command.lower().strip()

    try:
        # ── Volumen ─────────────────────────────────────────────
        if cmd == "volume_up":
            steps = int(value) if str(value).isdigit() else 2
            vol = min(1.0, (cast.status.volume_level or 0.5) + steps * 0.05)
            cast.set_volume(vol)
            return f"Volumen TV subido a {int(vol * 100)}%."

        if cmd == "volume_down":
            steps = int(value) if str(value).isdigit() else 2
            vol = max(0.0, (cast.status.volume_level or 0.5) - steps * 0.05)
            cast.set_volume(vol)
            return f"Volumen TV bajado a {int(vol * 100)}%."

        if cmd == "mute":
            cast.set_volume_muted(not cast.status.volume_muted)
            estado = "silenciada" if not cast.status.volume_muted else "activada"
            return f"TV {estado}."

        if cmd == "volume_set":
            pct = max(0, min(100, int(value or 50)))
            cast.set_volume(pct / 100)
            return f"Volumen TV al {pct}%."

        # ── Reproducción ─────────────────────────────────────────
        if cmd == "pause":
            cast.media_controller.pause()
            return "TV pausada."

        if cmd == "play":
            cast.media_controller.play()
            return "TV reproduciendo."

        if cmd == "stop":
            cast.media_controller.stop()
            return "TV detenida."

        # ── Apps ─────────────────────────────────────────────────
        if cmd == "youtube":
            from pychromecast.controllers.youtube import YouTubeController
            yt = YouTubeController()
            cast.register_handler(yt)
            if value:
                # value puede ser video_id o búsqueda de texto
                if len(value) == 11 and " " not in value:
                    yt.play_video(value)
                    return f"Reproduciendo en TV."
                else:
                    # Buscar en YouTube y reproducir primer resultado
                    from .tools import _youtube_first_video
                    url = _youtube_first_video(value)
                    if url:
                        vid_id = url.split("v=")[-1]
                        yt.play_video(vid_id)
                        return f"Reproduciendo '{value}' en la TV."
                    yt.launch()
                    return f"No encontré '{value}', YouTube abierto en la TV."
            else:
                yt.launch()
                return "YouTube abierto en la TV."

        if cmd == "netflix":
            cast.quit_app()
            return "Ve a Netflix en la TV manualmente (no tiene API pública)."

        # ── Apagar ───────────────────────────────────────────────
        if cmd == "off":
            cast.quit_app()
            return "TV apagada (aplicación cerrada)."

        if cmd == "status":
            vol = int((cast.status.volume_level or 0) * 100)
            app = cast.status.display_name or "inactiva"
            muted = "silenciada" if cast.status.volume_muted else "con sonido"
            return f"TV: app={app}, volumen={vol}%, {muted}."

    except Exception as e:
        log.error("TV error: %s", e)
        return f"Error controlando la TV: {e}"

    return f"Comando de TV '{command}' no reconocido."
