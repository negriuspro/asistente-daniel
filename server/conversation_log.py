import json
import logging
from datetime import datetime
from pathlib import Path
from threading import Lock

log = logging.getLogger("jarvis.conv_log")

_PATH = Path(__file__).parent.parent / "data" / "conversations.jsonl"
_lock = Lock()


def log_conversation(user: str, jarvis: str) -> None:
    _PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts":     datetime.now().isoformat(timespec="seconds"),
        "user":   user,
        "jarvis": jarvis,
    }
    with _lock:
        with _PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_history(n: int = 100) -> list[dict]:
    if not _PATH.exists():
        return []
    lines = _PATH.read_text(encoding="utf-8").strip().splitlines()
    result = []
    for line in lines[-n:]:
        try:
            result.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return result
