import asyncio
import json
import logging
import os
import re
import tempfile
from pathlib import Path

import psutil
from fastapi import (
    FastAPI,
    File,
    Form,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import battery_monitor as bm
from .ai_agent import clear_history, process
from .battery_monitor import monitor as _bm_monitor
from .conversation_log import get_history, log_conversation
from .docker_control import router as docker_router
from .docker_control import ws_router as docker_ws_router
from .system_monitor import router as system_monitor_router
from .smart_devices.router import router as smart_devices_router
from .smarthome import control_device, get_device_status, list_devices
from .stt import transcribe
from .tts import speak

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("daniel")

CLIENT_DIR = Path(__file__).parent.parent / "client"

app = FastAPI(title="Daniel AI Assistant")

# CORS — necesario para que AngelOS (otro origen) consuma /api/* desde el navegador
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "CORS_ORIGINS", "http://localhost:5004,http://192.168.100.6:3005"
    ).split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(docker_router)
app.include_router(docker_ws_router)
app.include_router(system_monitor_router)
app.include_router(smart_devices_router)


class _CtrlBody(BaseModel):
    on: bool


# ─── Wake-word pattern (responds to "Daniel" and common mishearings) ──────────
_WAKE_RE = re.compile(
    r"(?i)^[\s,.]*(daniel|danial|danie|danielle|danil|daniyel|danieel|daniele|dani)[\s,.]*",
)


def _strip_wake_word(text: str) -> str:
    return _WAKE_RE.sub("", text).strip()


def _has_wake_word(text: str) -> bool:
    return bool(_WAKE_RE.match(text))


# ─── Shape detection ──────────────────────────────────────────────────────────

_SHAPE_MAP = {
    "galaxia": "galaxy",
    "galaxy": "galaxy",
    "cerebro": "brain",
    "brain": "brain",
    "mente": "brain",
    "música": "wave",
    "musica": "wave",
    "onda": "wave",
    "wave": "wave",
    "adn": "dna",
    "dna": "dna",
    "espiral": "dna",
    "anillo": "ring",
    "ring": "ring",
    "estrella": "star",
    "star": "star",
    "árbol": "tree",
    "arbol": "tree",
    "tree": "tree",
}


def _detect_shape(text: str):
    lower = text.lower()
    for kw, shape in _SHAPE_MAP.items():
        if kw in lower:
            return shape
    return None


# ─── Startup ──────────────────────────────────────────────────────────────────


@app.on_event("startup")
async def startup() -> None:
    psutil.cpu_percent()
    asyncio.create_task(_bm_monitor())


# ─── Health ───────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "assistant": "Daniel"})


# ─── REST API ─────────────────────────────────────────────────────────────────


@app.get("/api/devices")
async def api_devices():
    devs = list_devices()
    out = []
    for d in devs:
        out.append(
            {
                "id": d["id"],
                "name": d.get("name", "?"),
                "online": d.get("online", False),
                "switch": get_device_status(d["id"]),
                "product": d.get("product_name", ""),
            }
        )
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
    return JSONResponse(
        {
            "available": True,
            "percent": round(batt.percent, 1),
            "plugged": batt.power_plugged,
            "auto": bm._plug_on,
            "low": bm._LOW,
            "high": bm._HIGH,
        }
    )


@app.get("/api/system")
async def api_system():
    mem = psutil.virtual_memory()
    try:
        disk = psutil.disk_usage("/").percent
    except Exception:
        disk = 0
    batt = psutil.sensors_battery()
    return JSONResponse(
        {
            "cpu": round(psutil.cpu_percent(interval=None), 1),
            "ram": round(mem.percent, 1),
            "ram_used": round(mem.used / 1024**3, 1),
            "ram_total": round(mem.total / 1024**3, 1),
            "disk": round(disk, 1),
            "battery": round(batt.percent, 1) if batt else None,
            "plugged": batt.power_plugged if batt else None,
        }
    )


@app.get("/api/weather")
async def api_weather(location: str = Query(default="")):
    from .weather import get_weather

    result = await get_weather(location)
    return JSONResponse({"result": result})


@app.get("/api/movies")
async def api_movies(query: str = Query(...), type: str = Query(default="movie")):
    from .tmdb_client import search_content

    result = await asyncio.to_thread(search_content, query, type)
    return JSONResponse({"result": result})


@app.post("/api/process-file")
async def api_process_file(
    file: UploadFile = File(...),
    instruction: str = Form(default=""),
):
    from .file_processor import process_file

    suffix = Path(file.filename or "file").suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name
    try:
        result = await asyncio.to_thread(process_file, tmp_path, instruction)
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except Exception:
            pass
    return JSONResponse({"result": result, "filename": file.filename})


# ─── Transcribe endpoint ─────────────────────────────────────────────────────


@app.post("/transcribe")
async def transcribe_endpoint(audio: UploadFile):
    data = await audio.read()
    text = await transcribe(data, audio.filename or "audio.webm")
    return JSONResponse({"text": text})


# ─── WebSocket — always-listening mode ───────────────────────────────────────


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    log.info("Cliente conectado: %s", websocket.client)
    try:
        while True:
            msg = await websocket.receive_text()

            # Client sends raw audio blob path or special signals
            if msg == "__activate__":
                # PC mic fallback: client detected wake word, record from server mic
                log.info("Wake word recibido — grabando desde micrófono del PC...")
                try:
                    from .mic import record_command

                    audio_bytes = await record_command()
                    if not audio_bytes:
                        await websocket.send_text("No detecté audio.")
                        continue
                    transcribed = await transcribe(audio_bytes, "audio.wav")
                    if not transcribed:
                        await websocket.send_text("No entendí. Habla más fuerte.")
                        continue
                    text = _strip_wake_word(transcribed)
                    if not text:
                        await websocket.send_text("¿Qué necesitás?")
                        continue
                    log.info("PC mic: %s", text)
                except Exception as e:
                    log.error("PC mic error: %s", e)
                    await websocket.send_text("__tablet_mic__")
                    continue
            else:
                text = msg

            # Always-listening: strip wake word if present, process anyway
            text = _strip_wake_word(text) if _has_wake_word(text) else text
            if not text:
                await websocket.send_text("¿Qué necesitás?")
                continue

            log.info("COMANDO: %s", text)
            try:
                response = await asyncio.wait_for(process(text), timeout=30.0)
                log.info("RESPUESTA: %s", response)
            except asyncio.TimeoutError:
                response = "Tardé demasiado. Intenta de nuevo."
                log.warning("TIMEOUT: %s", text)
            except Exception as e:
                response = "Error interno. Intenta de nuevo."
                log.error("ERROR: %s", e, exc_info=True)

            if not response:
                response = "Listo."
            try:
                log_conversation(text, response)
            except Exception as e:
                log.warning("No se pudo guardar conversación: %s", e)

            shape = _detect_shape(text)
            try:
                payload = json.loads(response)
                if not isinstance(payload, dict):
                    raise ValueError
            except (json.JSONDecodeError, ValueError):
                payload = {"reply": response}
            if shape:
                payload["shape"] = shape

            ws_payload = (
                json.dumps(payload, ensure_ascii=False)
                if len(payload) > 1
                else response
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
