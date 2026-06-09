"""
Persistencia JSON para dispositivos inteligentes.
Guarda en daniel/data/smart_devices.json
"""

from __future__ import annotations
import json
import os
import threading
from pathlib import Path
from .models import SmartDevice

_DATA_DIR = Path(
    os.environ.get("DATA_DIR", Path(__file__).parent.parent.parent / "data")
)
_DB_FILE = _DATA_DIR / "smart_devices.json"
_lock = threading.Lock()


def _load_raw() -> dict:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _DB_FILE.exists():
        return {}
    try:
        return json.loads(_DB_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_raw(data: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _DB_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def get_all() -> list[SmartDevice]:
    with _lock:
        raw = _load_raw()
    return [SmartDevice.from_dict(v) for v in raw.values()]


def get(device_id: str) -> SmartDevice | None:
    with _lock:
        raw = _load_raw()
    d = raw.get(device_id)
    return SmartDevice.from_dict(d) if d else None


def save(device: SmartDevice) -> None:
    with _lock:
        raw = _load_raw()
        raw[device.id] = device.to_dict_full()
        _save_raw(raw)


def delete(device_id: str) -> bool:
    with _lock:
        raw = _load_raw()
        if device_id not in raw:
            return False
        del raw[device_id]
        _save_raw(raw)
    return True


def get_by_type(device_type: str) -> list[SmartDevice]:
    return [d for d in get_all() if d.device_type == device_type]
