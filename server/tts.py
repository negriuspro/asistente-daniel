"""
TTS (Text-to-Speech) para Jarvis.

En modo servidor headless (Ubuntu sin audio), el TTS se deshabilita
automáticamente: sin pygame → sin ElevenLabs playback, sin espeak device
→ pyttsx3 no habla. Los logs indican el texto que se hablaría.
El cliente (navegador) maneja su propio TTS via Web Speech API.
"""

import io
import logging
import os
import queue
import threading
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

log = logging.getLogger("jarvis.tts")

_q: queue.Queue = queue.Queue()

_ELEVEN_KEY   = os.environ.get("ELEVENLABS_API_KEY", "")
_ELEVEN_VOICE = os.environ.get("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")
_ELEVEN_MODEL = "eleven_multilingual_v2"

_ELEVEN_SETTINGS = {
    "stability":         0.50,
    "similarity_boost":  0.75,
    "style":             0.20,
    "use_speaker_boost": True,
}
_ELEVEN_SPEED = 0.92

# Try to initialize pygame for audio playback (optional — fails gracefully on headless)
try:
    import pygame as _pygame
    _pygame.mixer.init()
    _pygame_ok = True
    log.info("TTS: pygame audio inicializado.")
except Exception as _e:
    log.info("TTS: pygame no disponible (%s) — audio del servidor desactivado.", _e)
    _pygame_ok = False


def _speak_elevenlabs(text: str) -> bool:
    if not _pygame_ok:
        log.info("TTS ElevenLabs omitido (sin audio en servidor): %s", text[:60])
        return False
    try:
        import httpx
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{_ELEVEN_VOICE}"
        headers = {
            "xi-api-key":   _ELEVEN_KEY,
            "Content-Type": "application/json",
            "Accept":       "audio/mpeg",
        }
        body = {
            "text":           text,
            "model_id":       _ELEVEN_MODEL,
            "voice_settings": _ELEVEN_SETTINGS,
            "speed":          _ELEVEN_SPEED,
        }
        with httpx.Client(timeout=30) as client:
            r = client.post(url, json=body, headers=headers)
            r.raise_for_status()

        buf = io.BytesIO(r.content)
        _pygame.mixer.music.load(buf)
        _pygame.mixer.music.play()
        while _pygame.mixer.music.get_busy():
            _pygame.time.Clock().tick(10)
        _pygame.mixer.music.unload()
        return True

    except Exception as e:
        log.error("ElevenLabs TTS error: %s", e)
        return False


def _worker():
    engine = None

    if not _ELEVEN_KEY:
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty("rate", 165)
            engine.setProperty("volume", 1.0)
            voices = engine.getProperty("voices")
            spanish = next(
                (v for v in voices
                 if "spanish" in v.name.lower()
                 or "es_" in v.id.lower()
                 or "helena" in v.name.lower()
                 or "sabina" in v.name.lower()
                 or "es" in v.id.lower()),
                None,
            )
            if spanish:
                engine.setProperty("voice", spanish.id)
                log.info("TTS pyttsx3: voz española '%s'", spanish.name)
            else:
                log.info("TTS pyttsx3: sin voz española encontrada, usando default")
            log.info("TTS fallback (pyttsx3 + espeak) listo.")
        except Exception as e:
            log.info("TTS pyttsx3 no disponible (%s) — servidor sin audio.", e)
    else:
        log.info("TTS: ElevenLabs activo — voz %s", _ELEVEN_VOICE)

    while True:
        text = _q.get()
        if text is None:
            break

        if _ELEVEN_KEY:
            _speak_elevenlabs(text)
        elif engine:
            try:
                engine.say(text)
                engine.runAndWait()
            except Exception as e:
                log.error("pyttsx3 error: %s", e)
        else:
            log.info("TTS (sin audio): %s", text[:80])


threading.Thread(target=_worker, daemon=True).start()


def speak(text: str) -> None:
    _q.put(text)
