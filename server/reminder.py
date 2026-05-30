import logging
import threading
from datetime import datetime, timedelta

log = logging.getLogger("jarvis.reminder")

_pending: list[dict] = []
_lock = threading.Lock()


def _parse_time(time_str: str) -> datetime | None:
    now = datetime.now()
    t = time_str.strip().lower().replace(" ", "")
    try:
        if ":" in t and "am" not in t and "pm" not in t:
            h, m = t.split(":")
            dt = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
        elif "pm" in t:
            t = t.replace("pm", "")
            h, m = t.split(":") if ":" in t else (t, "0")
            dt = now.replace(hour=int(h) % 12 + 12, minute=int(m), second=0, microsecond=0)
        elif "am" in t:
            t = t.replace("am", "")
            h, m = t.split(":") if ":" in t else (t, "0")
            dt = now.replace(hour=int(h) % 12, minute=int(m), second=0, microsecond=0)
        else:
            return None
        if dt <= now:
            dt += timedelta(days=1)
        return dt
    except Exception as e:
        log.error("Error parseando tiempo '%s': %s", time_str, e)
        return None


def _fire(message: str) -> None:
    with _lock:
        _pending.append({"message": message, "fired_at": datetime.now().isoformat()})
    log.info("RECORDATORIO DISPARADO: %s", message)


def pop_pending() -> list[dict]:
    """Drain and return all fired reminders (called by WebSocket loop)."""
    with _lock:
        items = list(_pending)
        _pending.clear()
        return items


def set_reminder(message: str, time_str: str, date_str: str = "today") -> str:
    dt = _parse_time(time_str)
    if not dt:
        return f"No entendí la hora '{time_str}'. Usa formato como '5pm' o '17:00'."

    delay = (dt - datetime.now()).total_seconds()
    timer = threading.Timer(delay, _fire, args=(message,))
    timer.daemon = True
    timer.start()

    hora_legible = dt.strftime("%I:%M %p").lstrip("0")
    log.info("Recordatorio programado: '%s' a las %s (en %.0fs)", message, hora_legible, delay)
    return f"Recordatorio configurado: '{message}' a las {hora_legible}."
