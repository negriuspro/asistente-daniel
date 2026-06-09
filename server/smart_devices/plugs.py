"""
Control de enchufes inteligentes.
Soporta: Tasmota, ESPHome, HTTP genérico, Tuya Local.
Prioridad: local siempre primero.
"""

from __future__ import annotations
import asyncio
import json

import httpx


# ─── Tasmota ─────────────────────────────────────────────────────────────────


async def tasmota_get_info(ip: str) -> dict:
    """Detecta y obtiene info de un enchufe Tasmota."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"http://{ip}/cm?cmnd=Status%200")
            if r.status_code == 200:
                data = r.json()
                status = data.get("Status", {})
                net = data.get("StatusNET", {})
                return {
                    "brand": "Tasmota",
                    "model": status.get("Module", ""),
                    "name": status.get("FriendlyName", ["Tasmota"])[0],
                    "firmware": data.get("StatusFWR", {}).get("Version", ""),
                    "mac": net.get("Mac", ""),
                    "supported": True,
                    "protocol": "tasmota",
                }
    except Exception:
        pass
    return {"supported": False}


async def tasmota_control(ip: str, action: str) -> dict:
    """
    Controla enchufe Tasmota.
    action: on | off | toggle | status
    """
    cmd_map = {
        "on": "Power%20On",
        "off": "Power%20Off",
        "toggle": "Power%20Toggle",
        "status": "Power",
    }
    cmd = cmd_map.get(action, "Power")
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"http://{ip}/cm?cmnd={cmd}")
            data = r.json()
            state = data.get("POWER", "").lower()
            return {"ok": True, "state": state}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── ESPHome ──────────────────────────────────────────────────────────────────


async def esphome_get_info(ip: str, port: int = 6052) -> dict:
    """Detecta dispositivo ESPHome via API nativa."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"http://{ip}:{port}/")
            if r.status_code == 200 and "esphome" in r.text.lower():
                return {
                    "brand": "ESPHome",
                    "model": "",
                    "name": "ESPHome Device",
                    "supported": True,
                    "protocol": "esphome",
                    "port": port,
                }
    except Exception:
        pass
    # Puerto alternativo 80
    if port != 80:
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.get(f"http://{ip}/")
                if r.status_code == 200 and "esphome" in r.text.lower():
                    return {
                        "brand": "ESPHome",
                        "model": "",
                        "name": "ESPHome Device",
                        "supported": True,
                        "protocol": "esphome",
                        "port": 80,
                    }
        except Exception:
            pass
    return {"supported": False}


async def esphome_control(ip: str, port: int, entity: str, action: str) -> dict:
    """
    Controla entidad ESPHome via REST.
    entity: switch/plug, action: turn_on | turn_off | toggle
    """
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.post(f"http://{ip}:{port}/switch/{entity}/{action}")
            return {"ok": r.status_code == 200}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── HTTP Genérico (Shelly, Sonoff, etc.) ────────────────────────────────────

_HTTP_PROFILES = [
    # Shelly Gen1
    {
        "name": "shelly",
        "detect_url": "/shelly",
        "detect_key": "type",
        "on_url": "/relay/0?turn=on",
        "off_url": "/relay/0?turn=off",
        "status_url": "/relay/0",
        "status_key": "ison",
    },
    # Shelly Gen2
    {
        "name": "shelly_gen2",
        "detect_url": "/rpc/Shelly.GetDeviceInfo",
        "detect_key": "model",
        "on_url": "/rpc/Switch.Set?id=0&on=true",
        "off_url": "/rpc/Switch.Set?id=0&on=false",
        "status_url": "/rpc/Switch.GetStatus?id=0",
        "status_key": "output",
    },
    # Sonoff DIY
    {
        "name": "sonoff_diy",
        "detect_url": "/zeroconf/info",
        "detect_key": "deviceid",
        "on_url": "/zeroconf/switch",
        "off_url": "/zeroconf/switch",
        "status_url": "/zeroconf/info",
        "status_key": "switch",
    },
]


async def http_generic_detect(ip: str) -> dict:
    """Detecta enchufe via perfiles HTTP comunes."""
    async with httpx.AsyncClient(timeout=3.0) as c:
        for profile in _HTTP_PROFILES:
            try:
                r = await c.get(f"http://{ip}{profile['detect_url']}")
                if r.status_code == 200:
                    data = (
                        r.json() if "json" in r.headers.get("content-type", "") else {}
                    )
                    if profile["detect_key"] in data or r.status_code == 200:
                        return {
                            "brand": profile["name"].capitalize(),
                            "profile": profile["name"],
                            "supported": True,
                            "protocol": "http",
                        }
            except Exception:
                continue
    return {"supported": False}


async def http_generic_control(ip: str, profile_name: str, action: str) -> dict:
    """Controla enchufe HTTP genérico."""
    profile = next((p for p in _HTTP_PROFILES if p["name"] == profile_name), None)
    if not profile:
        return {"ok": False, "error": "Perfil no encontrado"}

    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            if action == "on":
                r = await c.get(f"http://{ip}{profile['on_url']}")
            elif action == "off":
                r = await c.get(f"http://{ip}{profile['off_url']}")
            else:
                r = await c.get(f"http://{ip}{profile['status_url']}")
            return {"ok": r.status_code == 200, "raw": r.text[:200]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Tuya Local (via tinytuya) ───────────────────────────────────────────────


async def tuya_local_control(
    device_id: str, local_key: str, ip: str, action: str, dp: int = 1
) -> dict:
    """Controla enchufe Tuya directamente en LAN (sin nube)."""
    try:
        import tinytuya

        d = tinytuya.OutletDevice(
            dev_id=device_id, address=ip, local_key=local_key, version=3.3
        )
        d.set_socketTimeout(3)

        def _run():
            if action == "on":
                d.turn_on(switch=dp)
            elif action == "off":
                d.turn_off(switch=dp)
            return d.status()

        status = await asyncio.to_thread(_run)
        dps = status.get("dps", {})
        return {"ok": True, "state": dps.get(str(dp), None), "dps": dps}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Detector unificado ──────────────────────────────────────────────────────


async def detect_plug(ip: str) -> dict:
    """Prueba Tasmota → ESPHome → HTTP genérico en orden de prioridad."""
    tasmota = await tasmota_get_info(ip)
    if tasmota.get("supported"):
        return {**tasmota, "control_method": "tasmota"}

    esphome = await esphome_get_info(ip)
    if esphome.get("supported"):
        return {**esphome, "control_method": "esphome"}

    http = await http_generic_detect(ip)
    if http.get("supported"):
        return {**http, "control_method": "http_generic"}

    return {"supported": False}


async def control_plug(
    ip: str, control_method: str, action: str, extra: dict | None = None
) -> dict:
    extra = extra or {}
    if control_method == "tasmota":
        return await tasmota_control(ip, action)
    if control_method == "esphome":
        return await esphome_control(
            ip, extra.get("port", 6052), extra.get("entity", "plug"), action
        )
    if control_method == "http_generic":
        return await http_generic_control(ip, extra.get("profile", "shelly"), action)
    if control_method == "tuya_local":
        return await tuya_local_control(
            extra["device_id"], extra["local_key"], ip, action
        )
    return {"ok": False, "error": f"Método no soportado: {control_method}"}
