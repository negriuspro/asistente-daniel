import base64
import io
import logging
import os

from groq import AsyncGroq

log = logging.getLogger("jarvis.vision")

_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY", ""))
_MODEL  = "llama-3.2-11b-vision-preview"


def _screenshot_b64() -> str:
    from PIL import ImageGrab
    img = ImageGrab.grab()
    img.thumbnail((1280, 720))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


async def see_screen(question: str = "¿Qué hay en la pantalla?") -> str:
    try:
        img_b64 = _screenshot_b64()
    except Exception as e:
        return f"No pude tomar captura de pantalla: {e}"

    log.info("Enviando pantalla a Groq Vision: %s", question)

    try:
        response = await _client.chat.completions.create(
            model=_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                        },
                        {
                            "type": "text",
                            "text": (
                                f"{question}\n\n"
                                "Responde en español, de forma corta y directa, "
                                "como si fuera la respuesta de voz de un asistente. "
                                "Sin markdown, máximo 3 oraciones."
                            ),
                        },
                    ],
                }
            ],
            max_tokens=256,
        )
        return response.choices[0].message.content or "No pude analizar la pantalla."
    except Exception as e:
        log.error("Error en Groq Vision: %s", e)
        return f"Error al analizar la pantalla: {e}"
