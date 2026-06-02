"""
battery_monitor.py — Automatización del enchufe inteligente.

Fuente de datos de batería: Computadora Principal (vía system_monitor).
El servidor Ubuntu no tiene batería; usa exclusivamente los datos
recibidos del agente remoto.

Lógica:
  batería <= LOW  → enciende enchufe (carga)
  batería >= HIGH → apaga enchufe (protección)
"""

import asyncio
import logging
import os

from .smarthome import control_device, get_device_status

log = logging.getLogger("daniel.battery")

_LOW  = int(os.environ.get("BATTERY_LOW",  "20"))
_HIGH = int(os.environ.get("BATTERY_HIGH", "80"))
_PLUG = os.environ.get("TUYA_PLUG_PC_ID", "")

_plug_on: bool | None = None


async def monitor() -> None:
    """
    Bucle principal de monitoreo de batería.
    Lee datos de la Computadora Principal publicados por system_monitor.
    """
    global _plug_on

    if not _PLUG:
        log.warning("[BATTERY_AUTOMATION] TUYA_PLUG_PC_ID no configurado — automatización desactivada.")
        return

    log.info(
        "[BATTERY_AUTOMATION] Iniciado — usando batería de PC principal (LOW=%d%% → ON | HIGH=%d%% → OFF)",
        _LOW, _HIGH,
    )

    while True:
        try:
            # Importar aquí para evitar ciclo de importación en startup
            from .system_monitor import get_main_pc_battery

            batt = get_main_pc_battery()

            if batt is None or batt.get("percent") is None:
                log.debug("[BATTERY_AUTOMATION] Sin datos de PC principal aún — esperando agente...")
                await asyncio.sleep(60)
                continue

            if not batt.get("online"):
                log.warning(
                    "[BATTERY_AUTOMATION] PC principal OFFLINE — automatización pausada hasta reconexión."
                )
                await asyncio.sleep(60)
                continue

            pct     = batt["percent"]
            plugged = batt.get("plugged")

            # Leer estado real del enchufe (detecta cambios manuales)
            actual = get_device_status(_PLUG)
            if actual is not None:
                _plug_on = actual

            if pct <= _LOW and _plug_on is not True:
                if control_device(_PLUG, True):
                    _plug_on = True
                    log.info(
                        "[BATTERY_AUTOMATION] Batería PC %.0f%% — enchufe ENCENDIDO (cargando)",
                        pct,
                    )

            elif pct >= _HIGH and plugged and _plug_on is not False:
                if control_device(_PLUG, False):
                    _plug_on = False
                    log.info(
                        "[BATTERY_AUTOMATION] Batería PC %.0f%% — enchufe APAGADO (protección batería)",
                        pct,
                    )

        except Exception as e:
            log.error("[BATTERY_AUTOMATION] Error en monitor: %s", e)

        await asyncio.sleep(60)
