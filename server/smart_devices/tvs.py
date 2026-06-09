"""
Control de Smart TVs.
Soporta: Samsung (WebSocket), LG webOS (WebSocket), Android TV (ADB via HTTP).
Prioriza APIs locales. Sin dependencia de nube del fabricante.
"""

from __future__ import annotations
import asyncio
import json

import httpx


# ─── Samsung SmartThings Local API ───────────────────────────────────────────

SAMSUNG_PORTS = [8001, 8002]


async def samsung_get_info(ip: str) -> dict:
    """Obtiene info del TV Samsung via REST local."""
    for port in SAMSUNG_PORTS:
        try:
            url = f"http://{ip}:{port}/api/v2/"
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.get(url)
                if r.status_code == 200:
                    data = r.json()
                    device = data.get("device", {})
                    return {
                        "brand": "Samsung",
                        "model": device.get("modelName", ""),
                        "name": device.get("name", "Samsung TV"),
                        "os": device.get("OS", "Tizen"),
                        "port": port,
                        "supported": True,
                    }
        except Exception:
            continue
    return {"supported": False}


async def samsung_control(ip: str, port: int, command: str, value: str = "") -> bool:
    """
    Envía comando al Samsung TV via WebSocket (sin SSL primero, luego con SSL).
    commands: KEY_POWER, KEY_VOLUMEUP, KEY_VOLUMEDOWN, KEY_MUTE,
              KEY_CHANNELUP, KEY_CHANNELDOWN, KEY_HOME, KEY_NETFLIX, KEY_YOUTUBE
    """
    import base64

    app_name = base64.b64encode(b"Daniel").decode()
    remote_name = base64.b64encode(b"DanielRemote").decode()

    ws_url = (
        f"ws://{ip}:{port}/api/v2/channels/samsung.remote.control?name={remote_name}"
    )

    payload = json.dumps(
        {
            "method": "ms.remote.control",
            "params": {
                "Cmd": "Click",
                "DataOfCmd": command,
                "Option": "false",
                "TypeOfRemote": "SendRemoteKey",
            },
        }
    )

    try:
        # httpx no soporta WebSocket nativo, usamos socket raw
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout=3.0
        )
        # Handshake HTTP → WS simplificado
        host = f"{ip}:{port}"
        request = (
            f"GET /api/v2/channels/samsung.remote.control?name={remote_name} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        writer.write(request.encode())
        await writer.drain()
        await asyncio.wait_for(reader.read(1024), timeout=2.0)  # leer handshake

        # Enviar frame WS (sin máscara para simplificar)
        data = payload.encode()
        frame = bytes([0x81, len(data)]) + data
        writer.write(frame)
        await writer.drain()
        writer.close()
        return True
    except Exception:
        return False


# ─── LG webOS ────────────────────────────────────────────────────────────────

LG_PORT = 3000


async def lg_get_info(ip: str) -> dict:
    """Detecta TV LG webOS."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"http://{ip}:{LG_PORT}", timeout=2.0)
            if r.status_code in (200, 400, 404):
                return {
                    "brand": "LG",
                    "model": "",
                    "name": "LG Smart TV",
                    "os": "webOS",
                    "port": LG_PORT,
                    "supported": True,
                }
    except Exception:
        pass
    return {"supported": False}


async def lg_control(ip: str, command: str, value: str = "") -> dict:
    """
    Controla LG TV via WebSocket (protocolo LGTV2).
    commands: power_off, volume_up, volume_down, mute, channel_up, channel_down
    """
    cmd_map = {
        "power_off": {"type": "request", "uri": "ssap://system/turnOff"},
        "volume_up": {"type": "request", "uri": "ssap://audio/volumeUp"},
        "volume_down": {"type": "request", "uri": "ssap://audio/volumeDown"},
        "mute": {
            "type": "request",
            "uri": "ssap://audio/setMute",
            "payload": {"mute": True},
        },
        "channel_up": {"type": "request", "uri": "ssap://tv/channelUp"},
        "channel_down": {"type": "request", "uri": "ssap://tv/channelDown"},
        "home": {
            "type": "request",
            "uri": "ssap://system.launcher/open",
            "payload": {"id": "com.webos.app.home"},
        },
        "netflix": {
            "type": "request",
            "uri": "ssap://system.launcher/launch",
            "payload": {"id": "netflix"},
        },
        "youtube": {
            "type": "request",
            "uri": "ssap://system.launcher/launch",
            "payload": {"id": "youtube.leanback.v4"},
        },
        "get_volume": {"type": "request", "uri": "ssap://audio/getVolume"},
    }
    cmd = cmd_map.get(command)
    if not cmd:
        return {"ok": False, "error": f"Comando desconocido: {command}"}

    payload = json.dumps({"id": "1", **cmd})
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, LG_PORT), timeout=3.0
        )
        request = (
            f"GET / HTTP/1.1\r\nHost: {ip}:{LG_PORT}\r\n"
            f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        writer.write(request.encode())
        await writer.drain()
        await asyncio.wait_for(reader.read(1024), timeout=2.0)

        data = payload.encode()
        frame = bytes([0x81, len(data)]) + data
        writer.write(frame)
        await writer.drain()
        writer.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ─── Android TV (ADB over TCP) ───────────────────────────────────────────────


async def android_tv_get_info(ip: str) -> dict:
    """Detecta Android TV / Google TV via ADB port 5555."""
    try:
        _, w = await asyncio.wait_for(asyncio.open_connection(ip, 5555), timeout=2.0)
        w.close()
        return {
            "brand": "Android TV",
            "model": "",
            "name": "Android TV",
            "os": "Android TV",
            "port": 5555,
            "supported": True,
            "note": "ADB disponible en puerto 5555",
        }
    except Exception:
        pass
    return {"supported": False}


# ─── Detector unificado ──────────────────────────────────────────────────────


async def detect_tv(ip: str) -> dict:
    """Prueba Samsung → LG → Android TV. Retorna info del primero que responda."""
    samsung = await samsung_get_info(ip)
    if samsung.get("supported"):
        return {**samsung, "control_method": "samsung_ws"}

    lg = await lg_get_info(ip)
    if lg.get("supported"):
        return {**lg, "control_method": "lg_webos"}

    android = await android_tv_get_info(ip)
    if android.get("supported"):
        return {**android, "control_method": "android_adb"}

    return {"supported": False}


async def control_tv(
    ip: str, control_method: str, command: str, value: str = ""
) -> dict:
    """Dispatcher unificado de control."""
    if control_method == "samsung_ws":
        # Mapear comandos genéricos a Samsung key codes
        key_map = {
            "power_off": "KEY_POWER",
            "power_on": "KEY_POWER",
            "volume_up": "KEY_VOLUMEUP",
            "volume_down": "KEY_VOLUMEDOWN",
            "mute": "KEY_MUTE",
            "channel_up": "KEY_CHANNELUP",
            "channel_down": "KEY_CHANNELDOWN",
            "home": "KEY_HOME",
            "netflix": "KEY_NETFLIX",
            "youtube": "KEY_YOUTUBE",
        }
        key = key_map.get(command, command.upper())
        ok = await samsung_control(ip, SAMSUNG_PORTS[0], key)
        return {"ok": ok}

    if control_method == "lg_webos":
        return await lg_control(ip, command, value)

    return {"ok": False, "error": f"Método de control no soportado: {control_method}"}
