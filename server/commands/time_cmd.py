from datetime import datetime

_DAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MONTHS = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def match(text: str) -> str | None:
    if not any(k in text for k in ["hora", "fecha", "día", "dia", "tiempo"]):
        return None
    now = datetime.now()
    if "fecha" in text or "día" in text or "dia" in text:
        day = _DAYS[now.weekday()]
        month = _MONTHS[now.month - 1]
        return f"Hoy es {day} {now.day} de {month} de {now.year}"
    return f"Son las {now.strftime('%H:%M')}"
