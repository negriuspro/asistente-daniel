import logging
import os

from groq import AsyncGroq

log = logging.getLogger("jarvis.stt")

_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY", ""))


_PROMPT = (
    "Jarvis, apaga, enciende, enchufe, bombillo, lámpara, aire acondicionado, "
    "abre, cierra, sube, baja, volumen, YouTube, Spotify, Discord, Chrome, "
    "calculadora, notepad, escritorio, descargas, documentos, música, "
    "qué hora es, qué fecha es, busca, recuerda, recuérdame, pantalla, "
    "screenshot, reinicia, apaga el PC, bloquea"
)

async def transcribe(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    """Transcribe audio bytes using Groq Whisper."""
    try:
        result = await _client.audio.transcriptions.create(
            file=(filename, audio_bytes),
            model="whisper-large-v3-turbo",
            language="es",
            response_format="json",
            prompt=_PROMPT,
        )
        text = result.text.strip()
        log.info("Whisper: %s", text)
        return text
    except Exception as e:
        log.error("Whisper error: %s", e)
        return ""
