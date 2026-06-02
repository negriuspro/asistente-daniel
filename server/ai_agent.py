import asyncio
import json
import logging
import os
from pathlib import Path

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
                    return json.loads(text[start: i + 1])
                except json.JSONDecodeError:
                    return None
    return None


# ─── LLM calls ───────────────────────────────────────────────────────────────

async def _call_gemini(system: str, history: list[dict], user_msg: str) -> str:
    """Gemini 2.0 Flash — primary LLM."""
    import google.generativeai as genai
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY no configurada")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=system,
        generation_config=genai.types.GenerationConfig(
            temperature=0.1,
            max_output_tokens=512,
        ),
    )

    # Build Gemini-format history (must be alternating user/model pairs)
    gemini_history = []
    for msg in history:
        role = "model" if msg["role"] == "assistant" else "user"
        gemini_history.append({"role": role, "parts": [msg["content"]]})

    def _sync() -> str:
        chat = model.start_chat(history=gemini_history)
        resp = chat.send_message(user_msg)
        return resp.text

    return await asyncio.to_thread(_sync)


async def _call_groq(system: str, messages: list[dict]) -> str:
    """Groq Llama — fallback LLM."""
    from groq import AsyncGroq, RateLimitError
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise ValueError("GROQ_API_KEY no configurada")

    client = AsyncGroq(api_key=api_key)
    models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "llama3-8b-8192"]
    full_messages = [{"role": "system", "content": system}] + messages

    for model in models:
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=full_messages,
                max_tokens=512,
                temperature=0.1,
            )
            return resp.choices[0].message.content or ""
        except RateLimitError:
            log.warning("Rate limit en %s — probando siguiente modelo", model)
    raise RuntimeError("Todos los modelos Groq agotaron su límite.")


async def _llm(system: str, history: list[dict], user_msg: str) -> str:
    """Try Gemini first, fall back to Groq."""
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if gemini_key:
        try:
            return await _call_gemini(system, history, user_msg)
        except Exception as e:
            log.warning("Gemini falló (%s) — usando Groq como respaldo", e)

    groq_messages = history + [{"role": "user", "content": user_msg}]
    return await _call_groq(system, groq_messages)


# ─── Tool runner ─────────────────────────────────────────────────────────────

async def _run(tool: str, args: dict) -> str:
    return await asyncio.to_thread(execute_tool, tool, args)



# ─── Server / PC status helper ───────────────────────────────────────────────

def _fmt_uptime(secs: int | None) -> str:
    if not secs:
        return "?"
    d, r = divmod(int(secs), 86400)
    h, r = divmod(r, 3600)
    m    = r // 60
    return f"{d}d {h}h {m}m" if d else (f"{h}h {m}m" if h else f"{m}m")


async def _get_server_status(target: str) -> str:
    from .system_monitor import _main_pc_state, _is_online, _server_metrics

    parts: list[str] = []

    if target in ("pc", "both"):
        pc = _main_pc_state
        if pc:
            online  = _is_online(pc)
            bat     = pc.get("battery_percent")
            plugged = pc.get("power_plugged")
            bat_str = f"{bat:.0f}%" if bat is not None else "N/A"
            plug_str = " ⚡cargando" if plugged else " 🔋descargando"
            temp_str = f" | Temp {pc['temperature']}°C" if pc.get("temperature") else ""
            parts.append(
                f"🖥 PC Principal ({pc.get('hostname','?')}) — {'🟢 Online' if online else '🔴 Offline'}
"
                f"  CPU {pc.get('cpu_percent','?')}% | RAM {pc.get('ram_percent','?')}% | "
                f"Disco {pc.get('disk_percent','?')}%{temp_str}
"
                f"  Batería {bat_str}{plug_str} | Uptime {_fmt_uptime(pc.get('uptime'))}"
            )
        else:
            parts.append("🖥 PC Principal: sin datos — agente no conectado.")

    if target in ("server", "both"):
        sv = await asyncio.to_thread(_server_metrics)
        temp_str = f" | Temp {sv['temperature']}°C" if sv.get("temperature") else ""
        parts.append(
            f"🐧 Servidor ({sv.get('hostname','?')}) — 🟢 Online
"
            f"  CPU {sv['cpu_percent']}% | RAM {sv['ram_percent']}% | "
            f"Disco {sv['disk_percent']}%{temp_str}
"
            f"  Docker {sv['docker_containers_running']} contenedores | "
            f"IP {sv['ip_address']} | Uptime {_fmt_uptime(sv.get('uptime'))}"
        )

    return "

".join(parts) if parts else "Sin datos de monitoreo disponibles."


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
        _history = _history[-_MAX_HIST * 2:]

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
            url = await _run("open_website", {
                "action": params.get("type", "search"),
                "target": params.get("target", ""),
            })
            if url and url.startswith("http"):
                _pending_url = url

        elif action == "open_app":
            await _run("open_app", {"app_name": params.get("name", "")})

        elif action == "open_folder":
            await _run("open_folder", {"path": params.get("path", "")})

        elif action == "key_press":
            await _run("key_press", {"key": params.get("key", ""), "times": params.get("times", 1)})

        elif action == "type_text":
            await _run("type_text", {"text": params.get("text", "")})

        elif action == "system_control":
            return await _run("system_control", {
                "command": params.get("command", ""),
                "value": params.get("value", ""),
            })

        elif action == "get_datetime":
            return await _run("get_datetime", {})

        elif action == "system_info":
            return await _run("system_info", {})

        elif action == "take_screenshot":
            return await _run("take_screenshot", {})

        elif action == "smart_home":
            return await _run("smart_home", {
                "device": params.get("device", ""),
                "action": params.get("action", "on"),
            })

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
            return await _run("remember", {
                "key": params.get("key", "dato"),
                "value": params.get("value", ""),
                "category": params.get("category", "notes"),
            })

        elif action == "forget":
            return await _run("forget", {"key": params.get("key", "")})

        elif action == "recall":
            return await _run("recall", {"key": params.get("key", "")})

        elif action == "reminder":
            return await _run("reminder", {
                "message": params.get("message", ""),
                "time": params.get("time", ""),
                "date": params.get("date", "today"),
            })

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

    result = reply or "Listo."
    if _pending_url:
        return json.dumps({"reply": result, "open_url": _pending_url}, ensure_ascii=False)
    return result
