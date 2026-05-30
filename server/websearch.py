import logging
import os

from groq import AsyncGroq

log = logging.getLogger("jarvis.search")

_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY", ""))


def _ddg_search(query: str, max_results: int = 5) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            return list(ddgs.text(query, max_results=max_results))
    except Exception as e:
        log.error("DuckDuckGo error: %s", e)
        return []


async def search(query: str) -> str:
    results = _ddg_search(query)
    if not results:
        return f"No encontré resultados para: {query}"

    snippets = "\n".join(
        f"- {r.get('title','')}: {r.get('body','')}" for r in results
    )

    log.info("Resumiendo %d resultados para: %s", len(results), query)

    response = await _client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": (
                    "Resume la siguiente información en 2 oraciones cortas en español, "
                    "como si fuera una respuesta de voz de un asistente. "
                    "Sin markdown, sin listas, solo texto natural."
                ),
            },
            {
                "role": "user",
                "content": f"Pregunta: {query}\n\nResultados:\n{snippets}",
            },
        ],
        max_tokens=180,
    )
    return response.choices[0].message.content or "No pude resumir los resultados."
