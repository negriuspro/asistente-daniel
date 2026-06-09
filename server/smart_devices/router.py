"""
Router FastAPI para el módulo Dispositivos Inteligentes.
Todos los endpoints bajo /api/smart/
"""

from __future__ import annotations
import asyncio
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Any

from . import database as db
from .models import SmartDevice
from .discovery import scan_network, get_scan_state, probe_compatibility
from .cameras import probe_onvif, probe_rtsp, find_rtsp_stream, discover_onvif
from .tvs import detect_tv, control_tv
from .plugs import detect_plug, control_plug
from .ir_controllers import (
    detect_ir_controller,
    send_ir_code,
    save_ir_code,
    delete_ir_code,
    list_ir_codes,
    IR_DEVICE_TEMPLATES,
)

router = APIRouter(prefix="/api/smart", tags=["smart_devices"])


# ─── Modelos de entrada ──────────────────────────────────────────────────────


class DeviceSave(BaseModel):
    id: str = ""
    ip: str
    device_type: str = "unknown"
    name: str = ""
    manufacturer: str = ""
    model: str = ""
    hostname: str = ""
    mac: str = ""
    open_ports: list[int] = []
    protocols: list[str] = []
    capabilities: dict[str, Any] = {}
    credentials: dict[str, str] = {}
    control_method: str = ""
    state: dict[str, Any] = {}
    notes: str = ""


class ControlCmd(BaseModel):
    command: str
    value: str = ""
    extra: dict[str, Any] = {}


class IRCodeSave(BaseModel):
    device_id: str
    action: str
    code: str
    protocol: str = "raw"
    metadata: dict[str, Any] = {}


class ScanRequest(BaseModel):
    subnet: str = ""


# ─── Dispositivos (CRUD) ─────────────────────────────────────────────────────


@router.get("/devices")
async def list_devices():
    devices = db.get_all()
    return {"devices": [d.to_dict() for d in devices]}


@router.get("/devices/{device_id}")
async def get_device(device_id: str):
    d = db.get(device_id)
    if not d:
        raise HTTPException(404, "Dispositivo no encontrado")
    return d.to_dict()


@router.post("/devices")
async def save_device(body: DeviceSave):
    data = body.model_dump()
    if not data["id"]:
        data["id"] = data.get("mac") or data["ip"].replace(".", "_")
    device = SmartDevice.from_dict(data)
    device.last_seen = time.time()
    db.save(device)
    return {"ok": True, "id": device.id}


@router.delete("/devices/{device_id}")
async def delete_device(device_id: str):
    ok = db.delete(device_id)
    if not ok:
        raise HTTPException(404, "Dispositivo no encontrado")
    return {"ok": True}


@router.get("/devices/type/{device_type}")
async def list_by_type(device_type: str):
    devices = db.get_by_type(device_type)
    return {"devices": [d.to_dict() for d in devices]}


# ─── Escaneo de red ──────────────────────────────────────────────────────────

_scan_task: asyncio.Task | None = None


@router.post("/scan/start")
async def start_scan(body: ScanRequest, background_tasks: BackgroundTasks):
    global _scan_task
    state = get_scan_state()
    if state["running"]:
        return {"ok": False, "message": "Escaneo en curso"}

    async def _run():
        results = await scan_network(subnet=body.subnet)
        # Auto-guardar dispositivos encontrados
        for r in results:
            existing = db.get(r.mac or r.ip.replace(".", "_"))
            if not existing:
                device = SmartDevice(
                    id=r.mac or r.ip.replace(".", "_"),
                    ip=r.ip,
                    mac=r.mac,
                    hostname=r.hostname,
                    manufacturer=r.manufacturer,
                    device_type=r.device_type,
                    open_ports=r.open_ports,
                    protocols=r.protocols,
                )
                db.save(device)

    background_tasks.add_task(_run)
    return {"ok": True, "message": "Escaneo iniciado"}


@router.get("/scan/status")
async def scan_status():
    return get_scan_state()


# ─── Compatibilidad ──────────────────────────────────────────────────────────


@router.get("/compatibility/{ip}")
async def check_compatibility(ip: str):
    result = await probe_compatibility(ip)
    return {"ip": ip, "compatibility": result}


# ─── Cámaras ─────────────────────────────────────────────────────────────────


@router.get("/cameras")
async def list_cameras():
    cameras = db.get_by_type("camera")
    return {"cameras": [c.to_dict() for c in cameras]}


@router.post("/cameras/discover/onvif")
async def discover_onvif_cameras():
    results = await discover_onvif(timeout=3.0)
    return {"found": results}


@router.post("/cameras/{device_id}/probe")
async def probe_camera(device_id: str):
    device = db.get(device_id)
    if not device:
        raise HTTPException(404, "Cámara no encontrada")

    ip = device.ip
    creds = device.credentials
    user = creds.get("username", "")
    password = creds.get("password", "")

    onvif = await probe_onvif(ip, user=user, password=password)
    rtsp = await probe_rtsp(ip)
    rtsp_url = ""
    if rtsp.get("available"):
        rtsp_url = await find_rtsp_stream(ip, user=user, password=password)

    caps = {
        "onvif": onvif.get("supported", False),
        "rtsp": rtsp.get("available", False),
        "rtsp_url": rtsp_url,
        "manufacturer": onvif.get("manufacturer", device.manufacturer),
        "model": onvif.get("model", device.model),
    }

    device.capabilities.update(caps)
    if caps["manufacturer"]:
        device.manufacturer = caps["manufacturer"]
    if caps["model"]:
        device.model = caps["model"]
    if rtsp_url:
        device.state["rtsp_url"] = rtsp_url
    db.save(device)

    return {"ok": True, "capabilities": caps}


@router.post("/cameras/{device_id}/credentials")
async def set_camera_credentials(device_id: str, body: dict):
    device = db.get(device_id)
    if not device:
        raise HTTPException(404, "Cámara no encontrada")
    device.credentials.update(body)
    db.save(device)
    return {"ok": True}


# ─── Televisores ─────────────────────────────────────────────────────────────


@router.get("/tvs")
async def list_tvs():
    tvs = db.get_by_type("tv")
    return {"tvs": [t.to_dict() for t in tvs]}


@router.post("/tvs/{device_id}/detect")
async def detect_tv_api(device_id: str):
    device = db.get(device_id)
    if not device:
        raise HTTPException(404, "TV no encontrado")

    info = await detect_tv(device.ip)
    if info.get("supported"):
        device.manufacturer = info.get("brand", device.manufacturer)
        device.model = info.get("model", device.model)
        device.name = info.get("name", device.name) or device.name
        device.control_method = info.get("control_method", "")
        device.capabilities["tv_api"] = info
        db.save(device)

    return {"ok": info.get("supported", False), "info": info}


@router.post("/tvs/{device_id}/control")
async def control_tv_api(device_id: str, body: ControlCmd):
    device = db.get(device_id)
    if not device:
        raise HTTPException(404, "TV no encontrado")
    if not device.control_method:
        raise HTTPException(
            400, "TV sin método de control detectado. Ejecuta /detect primero."
        )

    result = await control_tv(
        device.ip, device.control_method, body.command, body.value
    )
    return result


# ─── Enchufes ─────────────────────────────────────────────────────────────────


@router.get("/plugs")
async def list_plugs():
    plugs = db.get_by_type("plug")
    return {"plugs": [p.to_dict() for p in plugs]}


@router.post("/plugs/{device_id}/detect")
async def detect_plug_api(device_id: str):
    device = db.get(device_id)
    if not device:
        raise HTTPException(404, "Enchufe no encontrado")

    info = await detect_plug(device.ip)
    if info.get("supported"):
        device.manufacturer = info.get("brand", device.manufacturer)
        device.control_method = info.get("control_method", "")
        device.capabilities["plug_api"] = info
        db.save(device)

    return {"ok": info.get("supported", False), "info": info}


@router.post("/plugs/{device_id}/control")
async def control_plug_api(device_id: str, body: ControlCmd):
    device = db.get(device_id)
    if not device:
        raise HTTPException(404, "Enchufe no encontrado")
    if not device.control_method:
        raise HTTPException(
            400, "Enchufe sin método de control. Ejecuta /detect primero."
        )

    result = await control_plug(
        device.ip,
        device.control_method,
        body.command,
        body.extra or device.capabilities.get("plug_api"),
    )
    if result.get("ok"):
        device.state["power"] = body.command
        device.last_seen = time.time()
        db.save(device)
    return result


# ─── Controladores IR ────────────────────────────────────────────────────────


@router.get("/ir")
async def list_ir():
    controllers = db.get_by_type("ir_controller")
    return {"controllers": [c.to_dict() for c in controllers]}


@router.post("/ir/{device_id}/detect")
async def detect_ir_api(device_id: str):
    device = db.get(device_id)
    if not device:
        raise HTTPException(404, "Controlador IR no encontrado")

    info = await detect_ir_controller(device.ip)
    if info.get("supported"):
        device.manufacturer = info.get("brand", device.manufacturer)
        device.control_method = info.get("control_method", "")
        device.capabilities["ir_api"] = info
        db.save(device)

    return {"ok": info.get("supported", False), "info": info}


@router.post("/ir/{device_id}/send")
async def send_ir(device_id: str, body: dict):
    """Envía código IR a un dispositivo registrado."""
    controller = db.get(device_id)
    if not controller:
        raise HTTPException(404, "Controlador IR no encontrado")

    target_device_id = body.get("target_device_id", "")
    action = body.get("action", "")

    result = await send_ir_code(
        controller.ip,
        controller.control_method,
        target_device_id,
        action,
        controller.capabilities.get("ir_api"),
    )
    return result


@router.get("/ir/codes")
async def get_ir_codes(device_id: str = ""):
    return {"codes": list_ir_codes(device_id or None)}


@router.post("/ir/codes")
async def save_ir_code_api(body: IRCodeSave):
    save_ir_code(body.device_id, body.action, body.code, body.protocol, body.metadata)
    return {"ok": True}


@router.delete("/ir/codes/{device_id}/{action}")
async def delete_ir_code_api(device_id: str, action: str):
    ok = delete_ir_code(device_id, action)
    return {"ok": ok}


@router.get("/ir/templates")
async def get_ir_templates():
    return {"templates": IR_DEVICE_TEMPLATES}


# ─── Auto-detección rápida por IP ────────────────────────────────────────────


@router.post("/autodetect")
async def autodetect(body: dict):
    """Detecta automáticamente el tipo y protocolo de un dispositivo por IP."""
    ip = body.get("ip", "")
    if not ip:
        raise HTTPException(400, "IP requerida")

    tasks = [
        detect_tv(ip),
        detect_plug(ip),
        detect_ir_controller(ip),
    ]
    tv_info, plug_info, ir_info = await asyncio.gather(*tasks)

    if tv_info.get("supported"):
        return {"type": "tv", "info": tv_info}
    if plug_info.get("supported"):
        return {"type": "plug", "info": plug_info}
    if ir_info.get("supported"):
        return {"type": "ir_controller", "info": ir_info}

    compat = await probe_compatibility(ip)
    if compat.get("rtsp") or compat.get("onvif"):
        return {"type": "camera", "info": compat}

    return {"type": "unknown", "info": compat}
