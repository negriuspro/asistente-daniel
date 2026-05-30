import re

from ..smarthome import smart_control

_RULES = [
    (r"(?:enciende|prende|activa)\s+(?:el\s+|la\s+)?(.+)", "on"),
    (r"(?:apaga|desactiva)\s+(?:el\s+|la\s+)?(.+)", "off"),
]


def match(text: str) -> str | None:
    for pattern, action in _RULES:
        m = re.search(pattern, text)
        if m:
            return smart_control(m.group(1).strip(), action)
    return None
