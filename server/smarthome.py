import json
import logging
import os
from pathlib import Path

import tinytuya

log = logging.getLogger("daniel.smarthome")

_DEVICES_JSON = Path(os.environ.get("DATA_DIR", "/app/data")) / "devices.json"
# Fallback a la raíz del proyecto (desarrollo local)
if not _DEVICES_JSON.exists():
    _DEVICES_JSON = Path(__file__).parent.parent / "devices.json"
_devices_cache: list[dict] | None = None
_cloud = None

# Categories controllable locally over WiFi
_LOCAL_CATEGORIES = {"cz", "kg", "dlq", "dj", "dd", "tgkg"}
# IR categories – need cloud API
_IR_CATEGORIES    = {"infrared_diy", "infrared_ac", "wnykq"}

# AC mode names → numeric code
_AC_MODES = {"frio": 0, "frío": 0, "cool": 0, "calor": 1, "heat": 1,
             "auto": 2, "ventilacion": 3, "ventilación": 3, "fan": 3, "seco": 4, "dry": 4}
# Fan speed names → numeric code
_AC_FAN   = {"auto": 0, "bajo": 1, "low": 1, "medio": 2, "mid": 2,
             "medium": 2, "alto": 3, "high": 3}


# ── Device list ─────────────────────────────────────────────────

def _load_devices() -> list[dict]:
    global _devices_cache
    if _devices_cache is not None:
        return _devices_cache

    if _DEVICES_JSON.exists():
        try:
            _devices_cache = json.loads(_DEVICES_JSON.read_text(encoding="utf-8"))
            log.info("Dispositivos cargados: %d", len(_devices_cache))
            return _devices_cache
        except Exception as e:
            log.error("Error leyendo devices.json: %s", e)

    raw = os.environ.get("TUYA_DEVICES", "")
    _devices_cache = []
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" in entry:
            name, did = entry.split(":", 1)
            _devices_cache.append({"name": name.strip(), "id": did.strip()})
    return _devices_cache


def list_devices() -> list[dict]:
    return _load_devices()


# ── Cloud (for IR devices) ───────────────────────────────────────

def _get_cloud():
    global _cloud
    if _cloud is not None:
        return _cloud
    access_id     = os.environ.get("TUYA_ACCESS_ID", "")
    access_secret = os.environ.get("TUYA_ACCESS_SECRET", "")
    if not access_id or not access_secret:
        return None
    try:
        _cloud = tinytuya.Cloud(
            apiRegion="us",
            apiKey=access_id,
            apiSecret=access_secret,
        )
        log.info("Tuya Cloud conectado (para dispositivos IR)")
    except Exception as e:
        log.error("Cloud init error: %s", e)
    return _cloud


def _cloud_control(device_id: str, turn_on: bool) -> bool:
    """Control via cloud API (for IR sub-devices)."""
    cloud = _get_cloud()
    if not cloud:
        return False

    dev = next((d for d in _load_devices() if d.get("id") == device_id), {})
    cat = dev.get("category", "")

    try:
        # IR AC uses PowerOn / PowerOff codes
        if cat == "infrared_ac":
            cmd = "PowerOn" if turn_on else "PowerOff"
            res = cloud.sendcommand(device_id, {"commands": [{"code": cmd, "value": cmd}]})
            log.info("IR AC %s → %s", cmd, res)
            return bool(res.get("success") if isinstance(res, dict) else False)

        # IR DIY (custom learned remote — LED strip, fan, etc.)
        if cat == "infrared_diy":
            parent_id = dev.get("parent", "")
            action_code = "power_on" if turn_on else "power_off"
            # Use the specific IR endpoint when parent hub is known
            if parent_id:
                try:
                    res = cloud.cloudrequest(
                        f"v1.0/infrareds/{parent_id}/remotes/{device_id}/command",
                        post={"code": action_code},
                    )
                    if isinstance(res, dict) and res.get("result"):
                        log.info("IR DIY %s via endpoint (code=%s)", dev.get("name"), action_code)
                        return True
                except Exception as e:
                    log.warning("IR DIY endpoint falló: %s", e)
            # Fallback: standard sendcommand with common code names
            for code_name in ("power_on" if turn_on else "power_off",
                              "switch_1", "power",
                              "on" if turn_on else "off"):
                try:
                    res = cloud.sendcommand(device_id, {"commands": [{"code": code_name, "value": turn_on}]})
                    if isinstance(res, dict) and res.get("success"):
                        log.info("IR DIY %s via sendcommand (code=%s)", dev.get("name"), code_name)
                        return True
                except Exception:
                    pass
            log.warning("IR DIY %s: ningún código funcionó — verifica los nombres en Smart Life", dev.get("name"))
            return False

        # Generic fallback
        res = cloud.sendcommand(device_id, {"commands": [{"code": "switch_1", "value": turn_on}]})
        return bool(res.get("success") if isinstance(res, dict) else False)

    except Exception as e:
        log.error("Cloud control %s: %s", device_id, e)
    return False


# ── Local WiFi control ───────────────────────────────────────────

def _make_local_device(dev: dict):
    ip  = dev.get("ip", "")
    key = dev.get("key", "")
    did = dev.get("id", "")
    ver = float(dev.get("version") or "3.5")
    if not ip or not key:
        return None
    if dev.get("category") == "cz":
        d = tinytuya.OutletDevice(dev_id=did, address=ip, local_key=key, version=ver)
    else:
        d = tinytuya.Device(dev_id=did, address=ip, local_key=key, version=ver)
    d.set_socketTimeout(5)
    return d


# ── Public API ───────────────────────────────────────────────────

def get_device_status(device_id: str) -> bool | None:
    dev = next((d for d in _load_devices() if d.get("id") == device_id), None)
    if not dev or dev.get("sub") or dev.get("category") in _IR_CATEGORIES:
        return None
    d = _make_local_device(dev)
    if not d:
        return None
    try:
        status = d.status()
        dps = status.get("dps", {})
        return bool(dps.get("1", dps.get("switch_1", False)))
    except Exception as e:
        log.error("Estado %s: %s", device_id, e)
    return None


def control_device(device_id: str, turn_on: bool) -> bool:
    dev = next((d for d in _load_devices() if d.get("id") == device_id), None)
    if not dev:
        log.warning("Dispositivo no encontrado: %s", device_id)
        return False

    cat = dev.get("category", "")

    # Local WiFi control
    if cat in _LOCAL_CATEGORIES and not dev.get("sub"):
        d = _make_local_device(dev)
        if d:
            try:
                result = d.turn_on() if turn_on else d.turn_off()
                log.info("%s → %s (local) | %s", dev.get("name"), "ON" if turn_on else "OFF", result)
                return True
            except Exception as e:
                log.error("Local control %s: %s", device_id, e)

    # Cloud control (IR devices)
    return _cloud_control(device_id, turn_on)


def ac_control(device_name: str, power: str = "", temp: int = 0,
               mode: str = "", fan: str = "") -> str:
    """Control de aire acondicionado IR: encender/apagar, temperatura, modo y ventilador."""
    dev = next(
        (d for d in _load_devices()
         if device_name.lower() in d.get("name", "").lower()
         and d.get("category") == "infrared_ac"),
        None,
    )
    if not dev:
        # Fallback: buscar cualquier AC aunque no coincida el nombre exacto
        dev = next((d for d in _load_devices() if d.get("category") == "infrared_ac"), None)
    if not dev:
        return f"No encontré un aire acondicionado en los dispositivos."

    cloud = _get_cloud()
    if not cloud:
        return "Cloud API no configurado (falta TUYA_ACCESS_ID/SECRET en .env)."

    device_id = dev["id"]
    commands = []
    summary = []

    if power.lower() in ("on", "encender", "encendido", "prender", "activar"):
        commands.append({"code": "PowerOn", "value": "PowerOn"})
        summary.append("encendido")
    elif power.lower() in ("off", "apagar", "apagado", "desactivar"):
        commands.append({"code": "PowerOff", "value": "PowerOff"})
        summary.append("apagado")

    if temp:
        t = max(16, min(30, int(temp)))
        commands.append({"code": "T", "value": t})
        summary.append(f"{t}°C")

    if mode:
        m = _AC_MODES.get(mode.lower())
        if m is not None:
            commands.append({"code": "M", "value": m})
            mode_names = ["frío", "calor", "auto", "ventilación", "seco"]
            summary.append(mode_names[m])

    if fan:
        f = _AC_FAN.get(fan.lower())
        if f is not None:
            commands.append({"code": "F", "value": f})
            fan_names = ["auto", "bajo", "medio", "alto"]
            summary.append(f"ventilador {fan_names[f]}")

    if not commands:
        return "No entendí qué cambiar en el aire. Especifica: encender/apagar, temperatura, modo o ventilador."

    try:
        res = cloud.sendcommand(device_id, {"commands": commands})
        ok = bool(res.get("success") if isinstance(res, dict) else False)
        if ok:
            return f"Aire: {', '.join(summary)}."
        log.warning("AC cloud resp: %s", res)
        return f"Aire ajustado ({', '.join(summary)})."
    except Exception as e:
        log.error("AC control error: %s", e)
        return f"Error controlando el aire: {e}"


def find_device_by_name(name: str) -> str | None:
    name_lower = name.lower()
    for dev in _load_devices():
        if name_lower in dev.get("name", "").lower():
            return dev["id"]
    return None


def smart_control(device_name: str, action: str) -> str:
    device_id = find_device_by_name(device_name)
    if not device_id:
        names = ", ".join(d.get("name", "?") for d in _load_devices())
        return f"No encontré '{device_name}'. Dispositivos: {names}" if names else f"No encontré '{device_name}'."
    turn_on = action.lower() in ("on", "encender", "encendido", "activar", "prender")
    ok = control_device(device_id, turn_on)
    estado = "encendido" if turn_on else "apagado"
    return f"{device_name} {estado}." if ok else f"No pude controlar {device_name}."
