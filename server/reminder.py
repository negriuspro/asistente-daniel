import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("jarvis.reminder")

_SCRIPTS_DIR = Path(__file__).parent.parent / "data" / "reminders"


def _notification_script(message: str) -> str:
    safe = message.replace('"', "'").replace("\n", " ")
    return (
        "Add-Type -AssemblyName System.Windows.Forms; "
        f'[System.Windows.Forms.MessageBox]::Show("{safe}", "Jarvis", '
        "[System.Windows.Forms.MessageBoxButtons]::OK, "
        "[System.Windows.Forms.MessageBoxIcon]::Information)"
    )


def _parse_time(time_str: str, date_str: str = "today") -> datetime | None:
    """Parse time like '17:00', '5pm', '5:30pm'."""
    now = datetime.now()
    t = time_str.strip().lower().replace(" ", "")

    try:
        # 24h format HH:MM
        if ":" in t and ("am" not in t and "pm" not in t):
            h, m = t.split(":")
            dt = now.replace(hour=int(h), minute=int(m), second=0, microsecond=0)

        # 12h with am/pm
        elif "pm" in t:
            t = t.replace("pm", "")
            if ":" in t:
                h, m = t.split(":")
            else:
                h, m = t, "0"
            h = int(h) % 12 + 12
            dt = now.replace(hour=h, minute=int(m), second=0, microsecond=0)

        elif "am" in t:
            t = t.replace("am", "")
            if ":" in t:
                h, m = t.split(":")
            else:
                h, m = t, "0"
            h = int(h) % 12
            dt = now.replace(hour=h, minute=int(m), second=0, microsecond=0)

        else:
            return None

        # If time already passed today, schedule tomorrow
        if dt <= now:
            dt += timedelta(days=1)

        return dt

    except Exception as e:
        log.error("Error parseando tiempo '%s': %s", time_str, e)
        return None


def set_reminder(message: str, time_str: str, date_str: str = "today") -> str:
    dt = _parse_time(time_str, date_str)
    if not dt:
        return f"No entendí la hora '{time_str}'. Usa formato como '5pm' o '17:00'."

    _SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    task_name = f"JarvisReminder_{dt.strftime('%Y%m%d%H%M%S')}"
    time_fmt  = dt.strftime("%H:%M")
    date_fmt  = dt.strftime("%m/%d/%Y")

    ps_cmd = _notification_script(message)
    cmd = (
        f'schtasks /create /tn "{task_name}" '
        f'/tr "powershell -WindowStyle Hidden -Command \\"{ps_cmd}\\"" '
        f"/sc once /st {time_fmt} /sd {date_fmt} /f"
    )

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)

    if result.returncode == 0:
        log.info("Recordatorio creado: '%s' a las %s", message, time_fmt)
        hora_legible = dt.strftime("%I:%M %p").lstrip("0")
        return f"Recordatorio configurado: '{message}' a las {hora_legible}."
    else:
        log.error("Error creando recordatorio: %s", result.stderr)
        return f"No pude crear el recordatorio: {result.stderr.strip()}"
