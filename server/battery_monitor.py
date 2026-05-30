import asyncio
import logging
import os

import psutil

from .smarthome import control_device, get_device_status

log = logging.getLogger("jarvis.battery")

_LOW  = int(os.environ.get("BATTERY_LOW",  "20"))
_HIGH = int(os.environ.get("BATTERY_HIGH", "80"))
_PLUG = os.environ.get("TUYA_PLUG_PC_ID", "")

_plug_on: bool | None = None


async def monitor() -> None:
    global _plug_on

    if not _PLUG:
        log.warning("TUYA_PLUG_PC_ID no configurado — monitor de batería desactivado.")
        return

    batt = psutil.sensors_battery()
    if batt is None:
        log.warning("No se detectó batería — monitor desactivado.")
        return

    log.info("Monitor de batería iniciado (LOW=%d%% → ON  |  HIGH=%d%% → OFF)", _LOW, _HIGH)

    while True:
        try:
            batt = psutil.sensors_battery()
            if batt:
                pct     = batt.percent
                plugged = batt.power_plugged

                # Read actual plug state (detects manual changes by user)
                actual = get_device_status(_PLUG)
                if actual is not None:
                    _plug_on = actual

                if pct <= _LOW and _plug_on is not True:
                    if control_device(_PLUG, True):
                        _plug_on = True
                        log.info("Batería %d%% — enchufe ENCENDIDO (cargando)", int(pct))

                elif pct >= _HIGH and plugged and _plug_on is not False:
                    if control_device(_PLUG, False):
                        _plug_on = False
                        log.info("Batería %d%% — enchufe APAGADO (protección batería)", int(pct))

        except Exception as e:
            log.error("Error en monitor de batería: %s", e)

        await asyncio.sleep(60)
