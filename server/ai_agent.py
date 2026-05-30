import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from groq import AsyncGroq, RateLimitError

from .tools import execute_tool
from .memory import get_context as _mem_context

load_dotenv(Path(__file__).parent.parent / ".env")

log = logging.getLogger("jarvis.ai")

_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY", ""))
_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "llama3-8b-8192",
]

# Conversational history — keeps last 3 turns for context
_history: list[dict] = []
_MAX_HIST = 6


def clear_history() -> None:
    _history.clear()

_SYSTEM = """Eres Jarvis. Asistente personal de IA. No eres un chatbot — eres el asistente de confianza de quien te habla.

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
- system_control: {"command": "volume_up/volume_down/mute/lock/shutdown/restart/screenshot", "value": N} — para volumen N es el número de pasos (default 2)
- smart_home: {"device": "nombre", "action": "on/off"}
- ac_control: {"device": "aire acondicionado", "power": "on/off", "temp": 16-30, "mode": "frio/calor/auto/ventilacion/seco", "fan": "auto/bajo/medio/alto"} — para el aire: temperatura, modo y ventilador. Campos opcionales.
- tv_control: {"command": "volume_up/volume_down/mute/volume_set/pause/play/stop/off/status", "value": "N o video_id"}
- google_home: {"command": "volume_up/volume_down/mute/volume_set/pause/play/stop/youtube/spotify/status", "value": "N o búsqueda"}
- web_search: {"query": "búsqueda"} — busca en internet y resume
- remember: {"key": "nombre", "value": "valor", "category": "identity/preferences/notes/projects"}
- forget: {"key": "nombre"}
- reminder: {"message": "qué recordar", "time": "17:00 o 5pm", "date": "today"}
- screen_vision: {"question": "pregunta sobre la pantalla"}
- get_datetime: {}
- chat: {} — solo para conversación sin acción

YouTube: l=+10s, j=-10s, k=pausa, f=pantalla completa, m=mute. 10 minutos = 60 veces "l".

EJEMPLOS:
"abre youtube y pon el primer video" → {"reply": "Ahí va.", "actions": [{"action": "open_website", "params": {"type": "open", "target": "youtube"}}, {"action": "wait", "params": {"ms": 4000}}, {"action": "key_press", "params": {"key": "tab", "times": 4}}, {"action": "key_press", "params": {"key": "enter", "times": 1}}]}
"pon reggaeton" → {"reply": "", "actions": [{"action": "open_website", "params": {"type": "youtube", "target": "reggaeton"}}]}
"busca videos de Roblox" → {"reply": "", "actions": [{"action": "open_website", "params": {"type": "youtube", "target": "roblox"}}]}
"sube el volumen" → {"reply": "", "actions": [{"action": "system_control", "params": {"command": "volume_up"}}]}
"baja el volumen" → {"reply": "", "actions": [{"action": "system_control", "params": {"command": "volume_down"}}]}
"silencio" → {"reply": "Mute.", "actions": [{"action": "system_control", "params": {"command": "mute"}}]}
"qué hora es" → {"reply": "", "actions": [{"action": "get_datetime", "params": {}}]}
"apaga el pc" → {"reply": "Apagando en 10 segundos.", "actions": [{"action": "system_control", "params": {"command": "shutdown"}}]}
"sube el volumen de la tv" → {"reply": "", "actions": [{"action": "tv_control", "params": {"command": "volume_up", "value": "2"}}]}
"baja el volumen de la tv 5" → {"reply": "", "actions": [{"action": "tv_control", "params": {"command": "volume_down", "value": "5"}}]}
"apaga la tv" → {"reply": "Listo.", "actions": [{"action": "tv_control", "params": {"command": "off"}}]}
"pausa la tv" → {"reply": "", "actions": [{"action": "tv_control", "params": {"command": "pause"}}]}
"pon youtube en la tv" → {"reply": "", "actions": [{"action": "tv_control", "params": {"command": "youtube"}}]}
"pon netflix en la tv" → {"reply": "", "actions": [{"action": "tv_control", "params": {"command": "netflix"}}]}
"sube el volumen de la televisión" → {"reply": "", "actions": [{"action": "tv_control", "params": {"command": "volume_up", "value": "3"}}]}

IMPORTANTE: cualquier mención de "tv", "televisión", "televisor" → usar tv_control, NO open_website.
"google home", "altavoz", "bocina" → usar google_home.
"enciende el enchufe" → {"reply": "Hecho.", "actions": [{"action": "smart_home", "params": {"device": "enchufe", "action": "on"}}]}
"apaga la lámpara" → {"reply": "Listo.", "actions": [{"action": "smart_home", "params": {"device": "lámpara", "action": "off"}}]}
"enciende el aire" → {"reply": "", "actions": [{"action": "ac_control", "params": {"device": "aire acondicionado", "power": "on"}}]}
"apaga el aire" → {"reply": "", "actions": [{"action": "ac_control", "params": {"device": "aire acondicionado", "power": "off"}}]}
"pon el aire a 22 grados" → {"reply": "", "actions": [{"action": "ac_control", "params": {"device": "aire acondicionado", "power": "on", "temp": 22}}]}
"pon el aire en frío a 20" → {"reply": "", "actions": [{"action": "ac_control", "params": {"device": "aire acondicionado", "power": "on", "temp": 20, "mode": "frio"}}]}
"pon el ventilador del aire en alto" → {"reply": "", "actions": [{"action": "ac_control", "params": {"device": "aire acondicionado", "fan": "alto"}}]}
"busca el precio del iPhone" → {"reply": "Buscando.", "actions": [{"action": "web_search", "params": {"query": "precio iPhone 16 2025"}}]}
"qué es la IA" → {"reply": "Buscando.", "actions": [{"action": "web_search", "params": {"query": "qué es la inteligencia artificial"}}]}
"recuerda que me llamo Juan" → {"reply": "Anotado.", "actions": [{"action": "remember", "params": {"key": "nombre", "value": "Juan", "category": "identity"}}]}
"me gusta el rock" → {"reply": "Anotado.", "actions": [{"action": "remember", "params": {"key": "música favorita", "value": "rock", "category": "preferences"}}]}
"recuérdame a las 5pm la reunión" → {"reply": "Recordatorio a las 5.", "actions": [{"action": "reminder", "params": {"message": "Tienes una reunión", "time": "5pm"}}]}
"qué hay en mi pantalla" → {"reply": "Analizando.", "actions": [{"action": "screen_vision", "params": {"question": "¿Qué hay en la pantalla?"}}]}
"qué dice ese texto" → {"reply": "", "actions": [{"action": "screen_vision", "params": {"question": "¿Qué texto hay en la pantalla?"}}]}
"hola" → {"reply": "¿Qué necesita?", "actions": [{"action": "chat", "params": {}}]}
"cómo estás" → {"reply": "Operativo al 100%. ¿Qué necesita?", "actions": [{"action": "chat", "params": {}}]}

REGLA FINAL: Solo JSON. Sin texto antes ni después. Reply máximo 6 palabras."""


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


async def _run(tool: str, args: dict) -> str:
    return await asyncio.to_thread(execute_tool, tool, args)


async def process(text: str) -> str:
    global _history
    mem = _mem_context()
    system = _SYSTEM + (f"\n\n{mem}" if mem else "")

    _history.append({"role": "user", "content": text})
    messages = [{"role": "system", "content": system}] + _history[-_MAX_HIST:]

    raw = ""
    for model in _MODELS:
        try:
            resp = await _client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=512,
                temperature=0.1,
            )
            raw = resp.choices[0].message.content or ""
            break
        except RateLimitError:
            log.warning("Rate limit en %s — probando modelo de respaldo", model)
    else:
        _history.pop()  # don't record the failed attempt
        return "Límite de solicitudes alcanzado. Intenta en unos minutos."

    data = _first_json(raw)
    if not data:
        result = raw or "No entendí eso."
        _history.append({"role": "assistant", "content": result})
        if len(_history) > _MAX_HIST * 2:
            _history = _history[-_MAX_HIST:]
        return result

    reply = data.get("reply", "Listo.")
    actions = data.get("actions", [])

    for act in actions:
        action = act.get("action", "")
        params = act.get("params", {})

        if action == "wait":
            await asyncio.sleep(params.get("ms", 1000) / 1000)

        elif action == "open_website":
            await _run("open_website", {
                "action": params.get("type", "search"),
                "target": params.get("target", ""),
            })

        elif action == "open_app":
            await _run("open_app", {"app_name": params.get("name", "")})

        elif action == "open_folder":
            await _run("open_folder", {"path": params.get("path", "")})

        elif action == "key_press":
            await _run("key_press", {
                "key": params.get("key", ""),
                "times": params.get("times", 1),
            })

        elif action == "type_text":
            await _run("type_text", {"text": params.get("text", "")})

        elif action == "system_control":
            return await _run("system_control", {
                "command": params.get("command", ""),
                "value": params.get("value", ""),
            })

        elif action == "get_datetime":
            return await _run("get_datetime", {})

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

    result = reply or "Listo."
    _history.append({"role": "assistant", "content": result})
    if len(_history) > _MAX_HIST * 2:
        _history = _history[-_MAX_HIST:]
    return result
