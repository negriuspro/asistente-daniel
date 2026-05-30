from .commands import COMMAND_MODULES
from .commands.conversation import default_response


def route_command(text: str) -> str:
    if not text.strip():
        return "No escuché ningún comando."

    clean = text.lower().strip()
    if clean.startswith("jarvis"):
        clean = clean[6:].strip()

    for module in COMMAND_MODULES:
        result = module.match(clean)
        if result is not None:
            return result

    return default_response(clean)
