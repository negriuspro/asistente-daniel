"""
Módulo de controladores infrarrojos.
Soporta: Broadlink, RM4 mini, dispositivos IR genéricos.
Permite aprender y ejecutar códigos IR para AC, TV, audio.
"""

from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path

import httpx

_IR_CODES_FILE = (
    Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent.parent / "data"))
    / "ir_codes.json"
)


def _load_ir_codes() -> dict:
    if not _IR_CODES_FILE.exists():
        return {}
    try:
        return json.loads(_IR_CODES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_ir_codes(data: dict) -> None:
    _IR_CODES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _IR_CODES_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ─── Broadlink HTTP Proxy ─────────────────────────────────────────────────────
# Algunos firmwares de Broadlink exponen un servidor HTTP local.


async def broadlink_detect(ip: str) -> dict:
    """Detecta Broadlink RM via HTTP o puerto 80."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"http://{ip}/")
            if r.status_code in (200, 401, 403):
                return {
                    "brand": "Broadlink",
                    "model": "RM",
                    "supported": True,
                    "protocol": "broadlink_http",
                }
    except Exception:
        pass
    # Intentar detección por puerto 80 abierto + hostname broadlink
    return {"supported": False}


async def broadlink_send(ip: str, code_b64: str) -> dict:
    """Envía código IR codificado en base64 via Broadlink HTTP proxy."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.post(f"http://{ip}/send_ir", json={"code": code_b64})
            return {"ok": r.status_code == 200}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── ESPHome IR Transmitter ───────────────────────────────────────────────────


async def esphome_ir_send(
    ip: str, port: int, protocol: str, data: int, nbits: int = 32
) -> dict:
    """Envía código IR via ESPHome remote_transmitter."""
    payload = {
        "command": {
            "protocol": protocol,
            "data": data,
            "nbits": nbits,
        }
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.post(
                f"http://{ip}:{port}/remote_transmitter/send_raw", json=payload
            )
            return {"ok": r.status_code == 200}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Almacenamiento de códigos IR ────────────────────────────────────────────


def list_ir_codes(device_id: str | None = None) -> dict:
    """Lista códigos IR guardados. Si device_id, filtra por dispositivo."""
    codes = _load_ir_codes()
    if device_id:
        return codes.get(device_id, {})
    return codes


def save_ir_code(
    device_id: str,
    action: str,
    code: str,
    protocol: str = "raw",
    metadata: dict | None = None,
) -> None:
    """Guarda un código IR para un dispositivo y acción."""
    codes = _load_ir_codes()
    if device_id not in codes:
        codes[device_id] = {}
    codes[device_id][action] = {
        "code": code,
        "protocol": protocol,
        "metadata": metadata or {},
    }
    _save_ir_codes(codes)


def delete_ir_code(device_id: str, action: str) -> bool:
    codes = _load_ir_codes()
    if device_id in codes and action in codes[device_id]:
        del codes[device_id][action]
        _save_ir_codes(codes)
        return True
    return False


async def send_ir_code(
    controller_ip: str,
    control_method: str,
    device_id: str,
    action: str,
    extra: dict | None = None,
) -> dict:
    """Busca el código IR guardado y lo envía al controlador."""
    codes = _load_ir_codes()
    entry = codes.get(device_id, {}).get(action)
    if not entry:
        return {"ok": False, "error": f"Código IR no encontrado: {device_id}/{action}"}

    code = entry["code"]
    protocol = entry.get("protocol", "raw")

    if control_method == "broadlink_http":
        return await broadlink_send(controller_ip, code)

    if control_method == "esphome_ir":
        extra = extra or {}
        return await esphome_ir_send(
            controller_ip,
            extra.get("port", 6052),
            protocol,
            int(code) if code.isdigit() else 0,
        )

    return {"ok": False, "error": f"Método IR no soportado: {control_method}"}


# ─── Plantillas de códigos IR comunes ────────────────────────────────────────
# Base de datos de acciones estándar por tipo de dispositivo.

IR_DEVICE_TEMPLATES = {
    "ac": [
        "power_on",
        "power_off",
        "temp_up",
        "temp_down",
        "mode_cool",
        "mode_heat",
        "mode_fan",
        "mode_auto",
        "fan_low",
        "fan_medium",
        "fan_high",
        "fan_auto",
        "swing_on",
        "swing_off",
    ],
    "tv": [
        "power",
        "power_on",
        "power_off",
        "volume_up",
        "volume_down",
        "mute",
        "channel_up",
        "channel_down",
        "input_hdmi1",
        "input_hdmi2",
        "input_av",
        "menu",
        "home",
        "back",
        "ok",
        "arrow_up",
        "arrow_down",
        "arrow_left",
        "arrow_right",
    ],
    "audio": [
        "power",
        "volume_up",
        "volume_down",
        "mute",
        "play",
        "pause",
        "stop",
        "next",
        "prev",
        "input_optical",
        "input_bluetooth",
        "input_aux",
    ],
}


async def detect_ir_controller(ip: str) -> dict:
    """Detecta controlador IR disponible en la IP."""
    broadlink = await broadlink_detect(ip)
    if broadlink.get("supported"):
        return {**broadlink, "control_method": "broadlink_http"}

    # Intentar ESPHome con transmissor IR
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"http://{ip}:6052/")
            if r.status_code == 200 and "remote" in r.text.lower():
                return {
                    "brand": "ESPHome IR",
                    "supported": True,
                    "control_method": "esphome_ir",
                    "port": 6052,
                }
    except Exception:
        pass

    return {"supported": False}
