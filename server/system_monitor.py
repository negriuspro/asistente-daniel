"""
system_monitor.py — Módulo de monitoreo distribuido para Daniel.

Gestiona métricas de dos sistemas:
  · Computadora Principal  — agente remoto (POST desde Windows)
  · Servidor Ubuntu        — métricas locales (psutil + docker)

Endpoints:
  POST /api/system/main-pc/update   Recibe métricas del agente
  GET  /api/system/status           Retorna estado de ambos sistemas
"""

import json
import logging
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

import psutil
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

log = logging.getLogger("daniel.system_monitor")

_DATA_DIR     = Path(os.environ.get("DATA_DIR", "/app/data"))
_STATE_FILE   = _DATA_DIR / "main_pc_state.json"
_AGENT_TOKEN  = os.environ.get("SYSTEM_AGENT_TOKEN", "")
_OFFLINE_SECS = 10 * 60   # 10 minutos

router = APIRouter(prefix="/api/system", tags=["system-monitor"])

# ── Estado en memoria ────────────────────────────────────────────────────────

_main_pc_state: dict = {}


def _load_persisted() -> None:
    global _main_pc_state
    try:
        if _STATE_FILE.exists():
            _main_pc_state = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            log.info("[SYSTEM_MAIN_PC] Estado cargado desde disco (%s)", _STATE_FILE)
    except Exception as e:
        log.warning("[SYSTEM_MAIN_PC] No se pudo leer estado persistido: %s", e)


def _persist(state: dict) -> None:
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception as e:
        log.warning("[SYSTEM_MAIN_PC] No se pudo persistir estado: %s", e)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_online(state: dict) -> bool:
    ts = state.get("timestamp")
    if not ts:
        return False
    try:
        last = datetime.fromisoformat(ts)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        delta = (datetime.now(timezone.utc) - last).total_seconds()
        return delta < _OFFLINE_SECS
    except Exception:
        return False


def get_main_pc_battery() -> dict | None:
    """
    Devuelve los datos de batería de la PC principal.
    Usado por battery_monitor para la automatización del enchufe.
    """
    if not _main_pc_state:
        return None
    return {
        "percent": _main_pc_state.get("battery_percent"),
        "plugged":  _main_pc_state.get("power_plugged"),
        "online":   _is_online(_main_pc_state),
    }


# ── Métricas del servidor ────────────────────────────────────────────────────

def _server_metrics() -> dict:
    mem  = psutil.virtual_memory()

    try:
        disk = psutil.disk_usage("/").percent
    except Exception:
        disk = 0.0

    # Uptime en segundos
    uptime_s = int(datetime.now().timestamp() - psutil.boot_time())

    # Temperatura CPU
    temp = None
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for key in ("coretemp", "cpu_thermal", "k10temp", "acpitz"):
                if key in temps and temps[key]:
                    temp = round(temps[key][0].current, 1)
                    break
    except Exception:
        pass

    # Contenedores Docker activos
    docker_running = 0
    try:
        import docker as _docker
        client = _docker.from_env()
        docker_running = len(client.containers.list())
        client.close()
    except Exception:
        pass

    # IP del servidor
    ip = "N/A"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        pass

    return {
        "hostname":                  socket.gethostname(),
        "cpu_percent":               round(psutil.cpu_percent(interval=None), 1),
        "ram_percent":               round(mem.percent, 1),
        "disk_percent":              round(disk, 1),
        "uptime":                    uptime_s,
        "temperature":               temp,
        "docker_containers_running": docker_running,
        "ip_address":                ip,
        "timestamp":                 datetime.now(timezone.utc).isoformat(),
    }


# ── Modelo de payload del agente ─────────────────────────────────────────────

class MainPCPayload(BaseModel):
    hostname:    str
    cpu:         float
    ram:         float
    disk:        float
    battery:     float | None = None
    plugged:     bool  | None = None
    uptime:      int   | None = None
    timestamp:   str
    temperature: float | None = None
    token:       str   | None = None  # autenticación opcional


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/main-pc/update")
async def update_main_pc(payload: MainPCPayload):
    """Recibe métricas del agente instalado en la Computadora Principal."""
    global _main_pc_state

    if _AGENT_TOKEN and payload.token != _AGENT_TOKEN:
        log.warning("[SYSTEM_MAIN_PC] Token inválido recibido desde %s", payload.hostname)
        raise HTTPException(status_code=403, detail="Token inválido")

    state = {
        "hostname":        payload.hostname,
        "cpu_percent":     payload.cpu,
        "ram_percent":     payload.ram,
        "disk_percent":    payload.disk,
        "battery_percent": payload.battery,
        "power_plugged":   payload.plugged,
        "uptime":          payload.uptime,
        "timestamp":       payload.timestamp,
        "temperature":     payload.temperature,
    }

    _main_pc_state = state
    _persist(state)

    bat_str = f"{payload.battery:.0f}%" if payload.battery is not None else "N/A"
    log.info(
        "[SYSTEM_MAIN_PC] %s — CPU:%.1f%% RAM:%.1f%% DISK:%.1f%% BAT:%s PLUGGED:%s",
        payload.hostname,
        payload.cpu,
        payload.ram,
        payload.disk,
        bat_str,
        payload.plugged,
    )
    return JSONResponse({"ok": True})


@router.get("/status")
async def system_status():
    """Retorna el estado completo de ambos sistemas monitoreados."""
    main_pc = {
        **_main_pc_state,
        "online": _is_online(_main_pc_state),
    } if _main_pc_state else {"online": False}

    server = _server_metrics()
    log.info("[SYSTEM_SERVER] CPU:%.1f%% RAM:%.1f%% DISK:%.1f%%",
             server["cpu_percent"], server["ram_percent"], server["disk_percent"])

    return JSONResponse({"main_pc": main_pc, "server": server})


# ── Carga inicial ────────────────────────────────────────────────────────────

_load_persisted()
