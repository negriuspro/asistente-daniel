"""
main_pc_agent.py — Agente de monitoreo para la Computadora Principal.

Ejecutar en Windows:
    pip install psutil requests
    python main_pc_agent.py

Variables de entorno (o editar directamente las constantes de abajo):
    DANIEL_SERVER_URL   URL base del servidor Daniel  (ej: http://192.168.1.10:3002)
    SYSTEM_AGENT_TOKEN  Token de autenticación (debe coincidir con el del servidor)
    AGENT_INTERVAL      Segundos entre envíos (default: 60)
"""

import logging
import os
import platform
import socket
import time
from datetime import datetime, timezone

import psutil
import requests

# ── Configuración ─────────────────────────────────────────────────────────────

SERVER_URL = os.environ.get("DANIEL_SERVER_URL", "http://localhost:3002")
TOKEN      = os.environ.get("SYSTEM_AGENT_TOKEN", "")
INTERVAL   = int(os.environ.get("AGENT_INTERVAL", "60"))
ENDPOINT   = f"{SERVER_URL}/api/system/main-pc/update"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main_pc_agent")


# ── Recopilación de métricas ──────────────────────────────────────────────────

def collect_metrics() -> dict:
    hostname = socket.gethostname()

    # CPU (primer llamado inicializa el contador; el agente ya corrió antes)
    cpu = round(psutil.cpu_percent(interval=1), 1)

    # RAM
    mem = psutil.virtual_memory()
    ram = round(mem.percent, 1)

    # Disco (C: en Windows, / en Linux/Mac)
    disk_path = "C:\\" if platform.system() == "Windows" else "/"
    try:
        disk = round(psutil.disk_usage(disk_path).percent, 1)
    except Exception:
        disk = 0.0

    # Batería
    battery = plugged = None
    batt = psutil.sensors_battery()
    if batt:
        battery = round(batt.percent, 1)
        plugged  = batt.power_plugged

    # Uptime
    uptime = int(time.time() - psutil.boot_time())

    # Temperatura CPU
    temperature = None
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for key in ("coretemp", "cpu_thermal", "k10temp", "acpitz"):
                if key in temps and temps[key]:
                    temperature = round(temps[key][0].current, 1)
                    break
    except Exception:
        pass  # Windows no siempre expone temperaturas sin librerías extra

    return {
        "hostname":    hostname,
        "cpu":         cpu,
        "ram":         ram,
        "disk":        disk,
        "battery":     battery,
        "plugged":     plugged,
        "uptime":      uptime,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "temperature": temperature,
        "token":       TOKEN or None,
    }


# ── Envío al servidor ─────────────────────────────────────────────────────────

def send_metrics(metrics: dict) -> bool:
    try:
        resp = requests.post(ENDPOINT, json=metrics, timeout=10)
        if resp.status_code == 200:
            bat_str = f"{metrics['battery']:.0f}%" if metrics["battery"] is not None else "N/A"
            log.info(
                "OK — CPU:%.1f%% RAM:%.1f%% DISK:%.1f%% BAT:%s",
                metrics["cpu"], metrics["ram"], metrics["disk"], bat_str,
            )
            return True
        else:
            log.warning("Servidor respondió %d: %s", resp.status_code, resp.text[:200])
    except requests.exceptions.ConnectionError:
        log.warning("Sin conexión con %s — reintentando en %ds...", SERVER_URL, INTERVAL)
    except Exception as e:
        log.error("Error enviando métricas: %s", e)
    return False


# ── Bucle principal ───────────────────────────────────────────────────────────

def main():
    log.info("Agente Daniel iniciado → %s (cada %ds)", ENDPOINT, INTERVAL)
    log.info("Hostname: %s | Python psutil: %s", socket.gethostname(), psutil.__version__)

    # Warm-up: primer cpu_percent siempre devuelve 0.0
    psutil.cpu_percent()

    while True:
        try:
            metrics = collect_metrics()
            send_metrics(metrics)
        except Exception as e:
            log.error("Error inesperado: %s", e)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
