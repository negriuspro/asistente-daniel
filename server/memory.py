import json
import logging
from datetime import datetime
from pathlib import Path
from threading import Lock

log = logging.getLogger("jarvis.memory")

_PATH = Path(__file__).parent.parent / "data" / "memory.json"
_lock = Lock()

_EMPTY = lambda: {"identity": {}, "preferences": {}, "notes": {}, "projects": {}}


def _load() -> dict:
    if not _PATH.exists():
        return _EMPTY()
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except Exception:
        return _EMPTY()


def _save(mem: dict) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        _PATH.write_text(json.dumps(mem, indent=2, ensure_ascii=False), encoding="utf-8")


def remember(key: str, value: str, category: str = "notes") -> str:
    mem = _load()
    if category not in mem:
        mem[category] = {}
    mem[category][key.lower().strip()] = {
        "value": value,
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    _save(mem)
    log.info("Memoria guardada: [%s] %s = %s", category, key, value)
    return f"Recordado: {value}"


def forget(key: str) -> str:
    mem = _load()
    key_l = key.lower().strip()
    for cat in mem.values():
        if isinstance(cat, dict) and key_l in cat:
            del cat[key_l]
            _save(mem)
            return f"Olvidado: {key}"
    return f"No encontré '{key}' en la memoria."


def get_context() -> str:
    """Returns a short memory summary to inject into every LLM prompt."""
    mem = _load()
    lines: list[str] = []
    for cat, items in mem.items():
        if not isinstance(items, dict):
            continue
        for key, entry in items.items():
            if isinstance(entry, dict) and entry.get("value"):
                lines.append(f"- {key}: {entry['value']}")
    if not lines:
        return ""
    return "Lo que sé del usuario:\n" + "\n".join(lines)


def recall(key: str) -> str:
    mem = _load()
    key_l = key.lower().strip()
    for cat in mem.values():
        if isinstance(cat, dict) and key_l in cat:
            return cat[key_l].get("value", "Sin valor")
    return f"No tengo información sobre '{key}'."
