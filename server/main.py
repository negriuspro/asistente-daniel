import asyncio
import json
import logging
from pathlib import Path

import groq as _groq
import psutil
from fastapi import FastAPI, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import battery_monitor as bm
from .ai_agent import clear_history, process
from .battery_monitor import monitor as _bm_monitor
from .conversation_log import get_history, log_conversation
from .docker_control import router as docker_router
from .smarthome import control_device, get_device_status, list_devices
from .stt import transcribe
from .tts import speak

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("jarvis")

CLIENT_DIR = Path(__file__).parent.parent / "client"

app = FastAPI()
app.include_router(docker_router)


class _CtrlBody(BaseModel):
    on: bool


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})


@app.on_event("startup")
async def startup() -> None:
    psutil.cpu_percent()  # initialize CPU sampling counter
    asyncio.create_task(_bm_monitor())


# ── REST API ────────────────────────────────────────────────────

@app.get("/api/devices")
async def api_devices():
    devs = list_devices()
    out = []
    for d in devs:
        out.append({
            "id":      d["id"],
            "name":    d.get("name", "?"),
            "online":  d.get("online", False),
            "switch":  get_device_status(d["id"]),
            "product": d.get("product_name", ""),
        })
    return JSONResponse({"devices": out})


@app.post("/api/devices/{device_id}")
async def api_device_ctrl(device_id: str, body: _CtrlBody):
    ok = control_device(device_id, body.on)
    return JSONResponse({"ok": ok})


@app.get("/api/history")
async def api_history(n: int = 100):
    return JSONResponse({"history": get_history(n)})


@app.get("/api/battery")
async def api_battery():
    batt = psutil.sensors_battery()
    if batt is None:
        return JSONResponse({"available": False})
    return JSONResponse({
        "available": True,
        "percent":   round(batt.percent, 1),
        "plugged":   batt.power_plugged,
        "auto":      bm._plug_on,
        "low":       bm._LOW,
        "high":      bm._HIGH,
    })


@app.get("/api/system")
async def api_system():
    mem = psutil.virtual_memory()
    try:
        disk = psutil.disk_usage("C:/").percent
    except Exception:
        disk = 0
    return JSONResponse({
        "cpu":       round(psutil.cpu_percent(interval=None), 1),
        "ram":       round(mem.percent, 1),
        "ram_used":  round(mem.used  / 1024 ** 3, 1),
        "ram_total": round(mem.total / 1024 ** 3, 1),
        "disk":      round(disk, 1),
    })


# ── Shape detection ─────────────────────────────────────────────

_SHAPE_MAP = {
    'galaxia': 'galaxy', 'galaxy': 'galaxy',
    'cerebro': 'brain',  'brain': 'brain',  'mente': 'brain',
    'música':  'wave',   'musica': 'wave',   'onda': 'wave',   'wave': 'wave',
    'adn':     'dna',    'dna': 'dna',       'espiral': 'dna',
    'anillo':  'ring',   'ring': 'ring',
    'estrella':'star',   'star': 'star',
    'árbol':   'tree',   'arbol': 'tree',    'tree': 'tree',
}


def _detect_shape(text: str):
    lower = text.lower()
    for kw, shape in _SHAPE_MAP.items():
        if kw in lower:
            return shape
    return None


# ── WebSocket + STT ─────────────────────────────────────────────

@app.post("/transcribe")
async def transcribe_endpoint(audio: UploadFile):
    data = await audio.read()
    text = await transcribe(data, audio.filename or "audio.webm")
    return JSONResponse({"text": text})


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    log.info("Cliente conectado: %s", websocket.client)
    try:
        while True:
            text = await websocket.receive_text()

            # PC mic mode: tablet detected wake word, server records from PC mic
            if text == "__activate__":
                log.info("Wake word recibido — grabando desde micrófono del PC...")
                try:
                    from .mic import record_command
                    audio_bytes = await record_command()
                    if not audio_bytes:
                        await websocket.send_text("No detecté audio en el micrófono.")
                        continue
                    text = await transcribe(audio_bytes, "audio.wav")
                    if not text:
                        await websocket.send_text("No entendí. Habla más fuerte.")
                        continue
                    # Strip wake word from start of transcription
                    import re
                    text = re.sub(
                        r'(?i)^[\s,.]*(jarvis|jarvi|harvis|harvi|jarbis|yarvis|yarbis|harvey|barral|barel|yarbiss|jarviz)[\s,.]*',
                        '', text
                    ).strip()
                    if not text:
                        await websocket.send_text("No entendí el comando.")
                        continue
                    log.info("PC mic transcribió: %s", text)
                except Exception as e:
                    log.error("PC mic error: %s", e)
                    await websocket.send_text("__tablet_mic__")
                    continue

            log.info("RECIBIDO: %s", text)
            try:
                response = await asyncio.wait_for(process(text), timeout=25.0)
                log.info("RESPUESTA: %s", response)
            except asyncio.TimeoutError:
                response = "Tardé demasiado. Intenta de nuevo."
                log.warning("TIMEOUT procesando: %s", text)
            except _groq.RateLimitError as e:
                response = "Límite de solicitudes. Intenta en unos minutos."
                log.warning("Rate limit Groq: %s", e)
            except Exception as e:
                response = "Error interno. Intenta de nuevo."
                log.error("ERROR en process(): %s", e, exc_info=True)
            if not response:
                response = "Listo."
            try:
                log_conversation(text, response)
            except Exception as e:
                log.warning("No se pudo guardar conversación: %s", e)
            shape = _detect_shape(text)
            ws_payload = (
                json.dumps({"reply": response, "shape": shape}, ensure_ascii=False)
                if shape else response
            )
            await websocket.send_text(ws_payload)
            try:
                speak(response)
            except Exception as e:
                log.warning("TTS error: %s", e)
    except WebSocketDisconnect:
        log.info("Cliente desconectado: %s", websocket.client)
        clear_history()


app.mount("/", StaticFiles(directory=str(CLIENT_DIR), html=True), name="static")
