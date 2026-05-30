_SERVER_MODE_MSG = (
    "Las aplicaciones de escritorio no están disponibles en modo servidor. "
    "Jarvis está corriendo en Ubuntu Server."
)

_APPS = {
    "notepad", "calculadora", "explorador", "discord", "spotify",
    "chrome", "vscode", "paint", "excel", "word", "teams",
}


def match(text: str) -> str | None:
    if not text.startswith("abre "):
        return None
    name = text[5:].strip()
    if name not in _APPS:
        return None
    return _SERVER_MODE_MSG
