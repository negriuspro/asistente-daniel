import asyncio
import json
import logging
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

from .tools import execute_tool
from .memory import get_context as _mem_context

load_dotenv(Path(__file__).parent.parent / ".env")

log = logging.getLogger("daniel.ai")

# ─── Conversation history ─────────────────────────────────────────────────────
_history: list[dict] = []
_MAX_HIST = 6


def clear_history() -> None:
    _history.clear()


# ─── System prompt ────────────────────────────────────────────────────────────
_SYSTEM = """Eres Daniel. Asistente personal de IA. No eres un chatbot — eres el asistente de confianza de quien te habla.

IDENTIDAD: Directo. Competente. Leal. Seco. Ejecutás primero, comentás después. Nunca al revés.
NUNCA digas: "claro que sí", "por supuesto", "entendido", "con gusto", "¡Perfecto!", "¡Claro!".
Frases naturales: "Listo." / "Hecho." / "Ahí está." / "Como guste." / "Consideralo resuelto."

HUMOR (opcional, después de ejecutar, uno solo, nunca lo expliques):
- 2 AM → "Las 2 de la mañana. Hecho. No voy a preguntar."
- Mismo pedido dos veces → "Tengo memoria perfecta. Pero lo hago igual."
- Abrir app → "Abierto. Existen los accesos directos, ¿sabía?"
- YouTube → "Listo. Va a ver algo que después va a lamentar."
- Búsqueda → "Buscado. La información existía en internet, en efecto."
- Error técnico → "Fascinante. El error es nuevo. No mejor, pero nuevo."
Si el contexto es urgente o serio → sin humor.

FORMATO DE RESPUESTA — SIEMPRE un único JSON válido:
{"reply": "texto corto o vacío", "actions": [{"action": "nombre", "params": {...}}]}

El "reply" debe ser MUY corto (2-6 palabras máximo). Si la acción habla por sí sola, reply puede ser "".
Para múltiples acciones en secuencia incluir wait entre ellas.

ACCIONES DISPONIBLES:
- open_website: {"type": "open"/"search"/"youtube", "target": "sitio o tema"}
  type="youtube" → busca y abre el primer video directamente
- open_app: {"name": "app"} — notepad, calculadora, explorador, discord, spotify, chrome, steam, vscode, paint, excel, word, terminal
- open_folder: {"path": "descargas/documentos/escritorio/música/videos/nombre"}
- key_press: {"key": "tecla", "times": N} — tab, enter, l, j, k, f, m, space, left, right, up, down, escape, 0-9
- type_text: {"text": "texto"}
- wait: {"ms": N}
- system_control: {"command": "volume_up/volume_down/mute/lock/shutdown/restart/suspend/screenshot", "value": N}
- smart_home: {"device": "nombre", "action": "on/off"}
- ac_control: {"device": "aire acondicionado", "power": "on/off", "temp": 16-30, "mode": "frio/calor/auto/ventilacion/seco", "fan": "auto/bajo/medio/alto"}
- tv_control: {"command": "volume_up/volume_down/mute/volume_set/pause/play/stop/off/status", "value": "N"}
- google_home: {"command": "volume_up/volume_down/mute/volume_set/pause/play/stop/youtube/spotify/status", "value": "N"}
- spotify_control: {"action": "play/pause/next/prev/search/volume/now_playing", "query": "canción o artista", "volume": 0-100}
- get_weather: {"location": "ciudad o 'mi ubicación'"}
- movies_info: {"query": "película o serie", "type": "movie/tv/trending"}
- web_search: {"query": "búsqueda"} — busca en internet y resume
- remember: {"key": "nombre", "value": "valor", "category": "identity/preferences/notes/projects"}
- forget: {"key": "nombre"}
- reminder: {"message": "qué recordar", "time": "17:00 o 5pm", "date": "today"}
- screen_vision: {"question": "pregunta sobre la pantalla"}
- get_datetime: {}
- system_info: {} — CPU, RAM, disco, batería del servidor
- server_status: {"target": "server/pc/both"} — estado real del servidor Ubuntu y/o PC principal (CPU, RAM, disco, batería, docker, temperatura)
- scan_network: {"subnet": ""} — escanea la red local y lista todos los dispositivos encontrados con su tipo, IP, fabricante y puertos abiertos. Dejar subnet vacío para auto-detectar.
- chat: {} — solo para conversación sin acción

YouTube: l=+10s, j=-10s, k=pausa, f=pantalla completa, m=mute.

EJEMPLOS:
"abre youtube y pon el primer video" → {"reply": "Ahí va.", "actions": [{"action": "open_website", "params": {"type": "open", "target": "youtube"}}, {"action": "wait", "params": {"ms": 4000}}, {"action": "key_press", "params": {"key": "tab", "times": 4}}, {"action": "key_press", "params": {"key": "enter", "times": 1}}]}
"pon reggaeton" → {"reply": "", "actions": [{"action": "open_website", "params": {"type": "youtube", "target": "reggaeton"}}]}
"sube el volumen" → {"reply": "", "actions": [{"action": "system_control", "params": {"command": "volume_up"}}]}
"silencio" → {"reply": "Mute.", "actions": [{"action": "system_control", "params": {"command": "mute"}}]}
"qué hora es" → {"reply": "", "actions": [{"action": "get_datetime", "params": {}}]}
"apaga el pc" → {"reply": "Apagando en 10 segundos.", "actions": [{"action": "system_control", "params": {"command": "shutdown"}}]}
"suspende el pc" → {"reply": "Suspendiendo.", "actions": [{"action": "system_control", "params": {"command": "suspend"}}]}
"sube el volumen de la tv" → {"reply": "", "actions": [{"action": "tv_control", "params": {"command": "volume_up", "value": "2"}}]}
"apaga la tv" → {"reply": "Listo.", "actions": [{"action": "tv_control", "params": {"command": "off"}}]}
"pausa spotify" → {"reply": "", "actions": [{"action": "spotify_control", "params": {"action": "pause"}}]}
"siguiente canción" → {"reply": "", "actions": [{"action": "spotify_control", "params": {"action": "next"}}]}
"pon a Bad Bunny en spotify" → {"reply": "", "actions": [{"action": "spotify_control", "params": {"action": "search", "query": "Bad Bunny"}}]}
"qué clima hace en Madrid" → {"reply": "", "actions": [{"action": "get_weather", "params": {"location": "Madrid"}}]}
"qué tiempo hace" → {"reply": "", "actions": [{"action": "get_weather", "params": {"location": "mi ubicación"}}]}
"recomiéndame una película de terror" → {"reply": "", "actions": [{"action": "movies_info", "params": {"query": "terror", "type": "movie"}}]}
"qué hay de trending en series" → {"reply": "", "actions": [{"action": "movies_info", "params": {"query": "trending", "type": "tv"}}]}
"información del sistema" → {"reply": "", "actions": [{"action": "system_info", "params": {}}]}
"cómo está el servidor" → {"reply": "", "actions": [{"action": "server_status", "params": {"target": "server"}}]}
"cómo está la pc principal" → {"reply": "", "actions": [{"action": "server_status", "params": {"target": "pc"}}]}
"cómo están los sistemas" → {"reply": "", "actions": [{"action": "server_status", "params": {"target": "both"}}]}
"analiza la red" → {"reply": "Escaneando.", "actions": [{"action": "scan_network", "params": {"subnet": ""}}]}
"qué dispositivos hay en la red" → {"reply": "Escaneando.", "actions": [{"action": "scan_network", "params": {"subnet": ""}}]}
"escanea la red" → {"reply": "Escaneando.", "actions": [{"action": "scan_network", "params": {"subnet": ""}}]}
"cuánta batería tiene la pc" → {"reply": "", "actions": [{"action": "server_status", "params": {"target": "pc"}}]}
"cuántos contenedores están corriendo" → {"reply": "", "actions": [{"action": "server_status", "params": {"target": "server"}}]}
"cuánta RAM tengo" → {"reply": "", "actions": [{"action": "system_info", "params": {}}]}
"busca el precio del iPhone" → {"reply": "Buscando.", "actions": [{"action": "web_search", "params": {"query": "precio iPhone 16 2025"}}]}
"recuerda que me llamo Juan" → {"reply": "Anotado.", "actions": [{"action": "remember", "params": {"key": "nombre", "value": "Juan", "category": "identity"}}]}
"recuérdame a las 5pm la reunión" → {"reply": "Recordatorio a las 5.", "actions": [{"action": "reminder", "params": {"message": "Tienes una reunión", "time": "5pm"}}]}
"qué hay en mi pantalla" → {"reply": "Analizando.", "actions": [{"action": "screen_vision", "params": {"question": "¿Qué hay en la pantalla?"}}]}
"hola" → {"reply": "¿Qué necesita?", "actions": [{"action": "chat", "params": {}}]}

IMPORTANTE: cualquier mención de "tv", "televisión", "televisor" → usar tv_control.
"google home", "altavoz", "bocina" → usar google_home.
"spotify", "pausa", "siguiente canción", "anterior" → usar spotify_control.

REGLA FINAL: Solo JSON. Sin texto antes ni después. Reply máximo 6 palabras."""


# ─── JSON extractor ───────────────────────────────────────────────────────────


def _first_json(text: str) -> dict | None:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# ─── Multi-provider LLM router ───────────────────────────────────────────────
# Orden: más rápido primero. Salta al siguiente si falla (cooldown 60s).

_PROVIDERS = [
    {
        "name": "cerebras",
        "env": "CEREBRAS_API_KEY",
        "type": "openai_compat",
        "base_url": "https://api.cerebras.ai/v1",
        "model": "llama-3.3-70b",
    },
    {
        "name": "groq",
        "env": "GROQ_API_KEY",
        "type": "groq",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "llama3-8b-8192"],
    },
    {
        "name": "sambanova",
        "env": "SAMBANOVA_API_KEY",
        "type": "openai_compat",
        "base_url": "https://api.sambanova.ai/v1",
        "model": "Meta-Llama-3.3-70B-Instruct",
    },
    {
        "name": "gemini",
        "env": "GEMINI_API_KEY",
        "type": "gemini",
        "model": "gemini-2.0-flash",
    },
    {
        "name": "openrouter",
        "env": "OPENROUTER_API_KEY",
        "type": "openai_compat",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "meta-llama/llama-3.3-70b-instruct:free",
    },
]

_failed: dict[str, float] = {}
_last_ok: str | None = None
_COOLDOWN = 60.0


async def _call_openai_compat(
    base_url: str, api_key: str, model: str, system: str, messages: list[dict]
) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
        "max_tokens": 512,
        "temperature": 0.1,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"] or ""


async def _call_groq_provider(
    api_key: str, models: list[str], system: str, messages: list[dict]
) -> str:
    from groq import AsyncGroq, RateLimitError

    client = AsyncGroq(api_key=api_key)
    full = [{"role": "system", "content": system}] + messages
    for model in models:
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=full,
                max_tokens=512,
                temperature=0.1,
            )
            return resp.choices[0].message.content or ""
        except RateLimitError:
            log.warning("Groq rate limit en %s", model)
    raise RuntimeError("Todos los modelos Groq agotaron su límite.")


async def _call_gemini_provider(
    api_key: str, model: str, system: str, history: list[dict], user_msg: str
) -> str:
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(
        model_name=model,
        system_instruction=system,
        generation_config=genai.types.GenerationConfig(
            temperature=0.1, max_output_tokens=512
        ),
    )
    gemini_hist = [
        {
            "role": "model" if msg["role"] == "assistant" else "user",
            "parts": [msg["content"]],
        }
        for msg in history
    ]

    def _sync() -> str:
        chat = m.start_chat(history=gemini_hist)
        return chat.send_message(user_msg).text

    try:
        return await asyncio.wait_for(asyncio.to_thread(_sync), timeout=8.0)
    except asyncio.TimeoutError:
        raise RuntimeError("Gemini timeout — cuota agotada o red lenta")


async def _llm(system: str, history: list[dict], user_msg: str) -> str:
    global _last_ok
    now = time.time()
    messages = history + [{"role": "user", "content": user_msg}]

    available = [p for p in _PROVIDERS if os.environ.get(p["env"], "")]
    ordered = [p for p in available if p["name"] == _last_ok] + [
        p
        for p in available
        if p["name"] != _last_ok and now - _failed.get(p["name"], 0) > _COOLDOWN
    ]

    if not ordered:
        raise RuntimeError("Ningún proveedor LLM configurado.")

    for provider in ordered:
        name = provider["name"]
        key = os.environ.get(provider["env"], "")
        try:
            if provider["type"] == "openai_compat":
                result = await _call_openai_compat(
                    provider["base_url"], key, provider["model"], system, messages
                )
            elif provider["type"] == "groq":
                result = await _call_groq_provider(
                    key, provider["models"], system, messages
                )
            else:
                result = await _call_gemini_provider(
                    key, provider["model"], system, history, user_msg
                )

            if _last_ok != name:
                log.info("LLM activo: %s", name)
            _last_ok = name
            return result

        except Exception as e:
            _failed[name] = now
            log.warning(
                "Provider %s falló (%s) — probando siguiente", name, type(e).__name__
            )

    raise RuntimeError("Todos los proveedores LLM fallaron.")


# ─── Tool runner ─────────────────────────────────────────────────────────────


async def _run(tool: str, args: dict) -> str:
    return await asyncio.to_thread(execute_tool, tool, args)


# ─── Server / PC status helper ───────────────────────────────────────────────


def _fmt_uptime(secs):
    if not secs:
        return "?"
    d, r = divmod(int(secs), 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return str(d) + "d " + str(h) + "h " + str(m) + "m"
    if h:
        return str(h) + "h " + str(m) + "m"
    return str(m) + "m"


async def _get_server_status(target):
    from .system_monitor import _main_pc_state, _is_online, _server_metrics

    parts = []

    if target in ("pc", "both"):
        pc = _main_pc_state
        if pc:
            online = _is_online(pc)
            bat = pc.get("battery_percent")
            plugged = pc.get("power_plugged")
            bat_str = (str(round(bat)) + "%") if bat is not None else "N/A"
            plug_str = " (cargando)" if plugged else " (descargando)"
            tv = pc.get("temperature")
            temp_str = (" | Temp " + str(tv) + "C") if tv else ""
            estado = "Online" if online else "Offline"
            parts.append(
                "PC Principal ("
                + str(pc.get("hostname", "?"))
                + ") - "
                + estado
                + "\n"
                + "  CPU "
                + str(pc.get("cpu_percent", "?"))
                + "% | "
                + "RAM "
                + str(pc.get("ram_percent", "?"))
                + "% | "
                + "Disco "
                + str(pc.get("disk_percent", "?"))
                + "%"
                + temp_str
                + "\n"
                + "  Bateria "
                + bat_str
                + plug_str
                + " | Uptime "
                + _fmt_uptime(pc.get("uptime"))
            )
        else:
            parts.append("PC Principal: sin datos - agente no conectado.")

    if target in ("server", "both"):
        sv = await asyncio.to_thread(_server_metrics)
        tv = sv.get("temperature")
        temp_str = (" | Temp " + str(tv) + "C") if tv else ""
        parts.append(
            "Servidor ("
            + str(sv.get("hostname", "?"))
            + ") - Online\n"
            + "  CPU "
            + str(sv["cpu_percent"])
            + "% | "
            + "RAM "
            + str(sv["ram_percent"])
            + "% | "
            + "Disco "
            + str(sv["disk_percent"])
            + "%"
            + temp_str
            + "\n"
            + "  Docker "
            + str(sv["docker_containers_running"])
            + " contenedores"
            + " | IP "
            + str(sv["ip_address"])
            + " | Uptime "
            + _fmt_uptime(sv.get("uptime"))
        )

    return "\n\n".join(parts) if parts else "Sin datos de monitoreo disponibles."


# ─── Network scan summary ────────────────────────────────────────────────────

_TYPE_LABELS = {
    "camera": "Cámara IP",
    "tv": "Televisor",
    "plug": "Enchufe inteligente",
    "ir_controller": "Controlador IR",
    "router": "Router/AP",
    "computer": "Computadora",
    "nas": "NAS / servidor",
    "printer": "Impresora",
    "unknown": "Desconocido",
}

_TYPE_ICONS = {
    "camera": "📷",
    "tv": "📺",
    "plug": "🔌",
    "ir_controller": "🔴",
    "router": "📡",
    "computer": "💻",
    "nas": "🗄️",
    "printer": "🖨️",
    "unknown": "❓",
}


async def _scan_network_summary(subnet: str = "") -> str:
    from .smart_devices.discovery import scan_network

    log.info("Escaneo de red solicitado por voz — subred: %s", subnet or "auto")
    try:
        results = await asyncio.wait_for(
            scan_network(subnet=subnet or ""),
            timeout=45.0,
        )
    except asyncio.TimeoutError:
        return "El escaneo tardó demasiado. Intenta de nuevo."
    except Exception as e:
        log.error("scan_network error: %s", e)
        return "No pude escanear la red. Verifica la conexión."

    if not results:
        return "No encontré dispositivos en la red local."

    lines = [f"Encontré {len(results)} dispositivo(s):"]
    for r in sorted(results, key=lambda x: x.ip):
        icon = _TYPE_ICONS.get(r.device_type, "❓")
        label = _TYPE_LABELS.get(r.device_type, r.device_type)
        name = r.hostname or r.manufacturer or "Sin nombre"
        proto = ", ".join(r.protocols[:3]) if r.protocols else "—"
        lines.append(f"  {icon} {r.ip} — {label} ({name}) [{proto}]")

    return "\n".join(lines)


# ─── Main process ─────────────────────────────────────────────────────────────


async def process(text: str) -> str:
    global _history
    mem = _mem_context()
    system = _SYSTEM + (f"\n\n{mem}" if mem else "")

    # History passed to LLM (without current message — added below)
    hist_for_llm = list(_history[-_MAX_HIST:])

    raw = ""
    try:
        raw = await _llm(system, hist_for_llm, text)
    except Exception as e:
        log.error("LLM error: %s", e)
        return "Sin conexión con la IA. Verifica tus API keys."

    # Record this turn
    _history.append({"role": "user", "content": text})
    _history.append({"role": "assistant", "content": raw})
    if len(_history) > _MAX_HIST * 2:
        _history = _history[-_MAX_HIST * 2 :]

    data = _first_json(raw)
    if not data:
        return raw or "No entendí eso."

    reply = data.get("reply", "Listo.")
    actions = data.get("actions", [])
    _pending_url: str | None = None

    for act in actions:
        action = act.get("action", "")
        params = act.get("params", {})

        if action == "wait":
            await asyncio.sleep(params.get("ms", 1000) / 1000)

        elif action == "open_website":
            url = await _run(
                "open_website",
                {
                    "action": params.get("type", "search"),
                    "target": params.get("target", ""),
                },
            )
            if url and url.startswith("http"):
                _pending_url = url

        elif action == "open_app":
            await _run("open_app", {"app_name": params.get("name", "")})

        elif action == "open_folder":
            await _run("open_folder", {"path": params.get("path", "")})

        elif action == "key_press":
            await _run(
                "key_press",
                {"key": params.get("key", ""), "times": params.get("times", 1)},
            )

        elif action == "type_text":
            await _run("type_text", {"text": params.get("text", "")})

        elif action == "system_control":
            return await _run(
                "system_control",
                {
                    "command": params.get("command", ""),
                    "value": params.get("value", ""),
                },
            )

        elif action == "get_datetime":
            return await _run("get_datetime", {})

        elif action == "system_info":
            return await _run("system_info", {})

        elif action == "take_screenshot":
            return await _run("take_screenshot", {})

        elif action == "smart_home":
            return await _run(
                "smart_home",
                {
                    "device": params.get("device", ""),
                    "action": params.get("action", "on"),
                },
            )

        elif action == "ac_control":
            from .smarthome import ac_control

            return await asyncio.to_thread(
                ac_control,
                params.get("device", "aire acondicionado"),
                params.get("power", ""),
                int(params.get("temp", 0)),
                params.get("mode", ""),
                params.get("fan", ""),
            )

        elif action == "web_search":
            from .websearch import search

            return await search(params.get("query", text))

        elif action == "remember":
            return await _run(
                "remember",
                {
                    "key": params.get("key", "dato"),
                    "value": params.get("value", ""),
                    "category": params.get("category", "notes"),
                },
            )

        elif action == "forget":
            return await _run("forget", {"key": params.get("key", "")})

        elif action == "recall":
            return await _run("recall", {"key": params.get("key", "")})

        elif action == "reminder":
            return await _run(
                "reminder",
                {
                    "message": params.get("message", ""),
                    "time": params.get("time", ""),
                    "date": params.get("date", "today"),
                },
            )

        elif action == "tv_control":
            from .tv import tv_control

            return await asyncio.to_thread(
                tv_control,
                params.get("command", "status"),
                str(params.get("value", "")),
            )

        elif action == "screen_vision":
            from .vision import see_screen

            return await see_screen(params.get("question", "¿Qué hay en la pantalla?"))

        elif action == "google_home":
            from .google_home import google_home_control

            return await asyncio.to_thread(
                google_home_control,
                params.get("command", "status"),
                str(params.get("value", "")),
            )

        elif action == "spotify_control":
            from .spotify_control import handle_spotify

            return await asyncio.to_thread(
                handle_spotify,
                params.get("action", "now_playing"),
                params.get("query", ""),
                int(params.get("volume", -1)),
            )

        elif action == "get_weather":
            from .weather import get_weather

            return await get_weather(params.get("location", ""))

        elif action == "server_status":
            return await _get_server_status(params.get("target", "both"))

        elif action == "movies_info":
            from .tmdb_client import search_content

            return await asyncio.to_thread(
                search_content,
                params.get("query", ""),
                params.get("type", "movie"),
            )

        elif action == "scan_network":
            return await _scan_network_summary(params.get("subnet", ""))

    result = reply or "Listo."
    if _pending_url:
        return json.dumps(
            {"reply": result, "open_url": _pending_url}, ensure_ascii=False
        )
    return result
