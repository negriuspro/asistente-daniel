import io
import logging
import os
import queue
import tempfile
import threading
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

log = logging.getLogger("jarvis.tts")

_q: queue.Queue = queue.Queue()

_ELEVEN_KEY   = os.environ.get("ELEVENLABS_API_KEY", "")
_ELEVEN_VOICE = os.environ.get("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")  # Daniel — british, deep
_ELEVEN_MODEL = "eleven_multilingual_v2"

# Jarvis voice settings — calm, sophisticated, cinematic
_ELEVEN_SETTINGS = {
    "stability":        0.50,   # 45-60%: natural variance without instability
    "similarity_boost": 0.75,   # 70-85%: clear, well-defined voice
    "style":            0.20,   # 15-25%: subtle style expression
    "use_speaker_boost": True,
}
_ELEVEN_SPEED = 0.92  # slightly slower than default — more deliberate, intelligent feel

# Initialize pygame mixer once at module level
try:
    import pygame as _pygame
    _pygame.mixer.init()
    _pygame_ok = True
except Exception as _e:
    log.warning("pygame no disponible para TTS: %s", _e)
    _pygame_ok = False


def _speak_elevenlabs(text: str) -> bool:
    if not _pygame_ok:
        log.error("pygame no inicializado — no se puede reproducir audio ElevenLabs")
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
        # Fallback: pyttsx3
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
                 or "sabina" in v.name.lower()),
                None,
            )
            if spanish:
                engine.setProperty("voice", spanish.id)
                log.info("Voz española pyttsx3: %s", spanish.name)
            log.info("TTS fallback (pyttsx3) listo.")
        except Exception as e:
            log.error("pyttsx3 no pudo iniciar: %s", e)
    else:
        log.info("TTS: ElevenLabs activo — voz %s", _ELEVEN_VOICE)

    while True:
        text = _q.get()
        if text is None:
            break

        if _ELEVEN_KEY:
            if not _speak_elevenlabs(text):
                log.warning("ElevenLabs falló — sin audio de respaldo.")
        elif engine:
            try:
                log.info("TTS hablando: %s", text)
                engine.say(text)
                engine.runAndWait()
            except Exception as e:
                log.error("pyttsx3 error al hablar: %s", e)


threading.Thread(target=_worker, daemon=True).start()


def speak(text: str) -> None:
    _q.put(text)
