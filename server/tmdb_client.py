"""TMDB client — movies and TV shows search."""
import logging
import os

import httpx

log = logging.getLogger("jarvis.tmdb")

_BASE = "https://api.themoviedb.org/3"


def _key() -> str:
    return os.environ.get("TMDB_API_KEY", "")


def search_content(query: str, content_type: str = "movie") -> str:
    api_key = _key()
    if not api_key:
        return "TMDB_API_KEY no configurada. Agrégala en el archivo .env."

    if content_type == "trending" or query.lower() == "trending":
        return _get_trending(api_key)

    endpoint = "/search/tv" if content_type == "tv" else "/search/movie"
    try:
        with httpx.Client(timeout=8) as client:
            r = client.get(
                f"{_BASE}{endpoint}",
                params={"api_key": api_key, "query": query, "language": "es-ES", "page": 1},
            )
            r.raise_for_status()
            results = r.json().get("results", [])[:5]
    except Exception as e:
        log.warning("TMDB búsqueda falló: %s", e)
        return "No pude conectar con TMDB."

    if not results:
        return f"No encontré resultados para '{query}'."

    label = "series" if content_type == "tv" else "películas"
    lines = [f"Top {label} para '{query}':"]
    for item in results:
        title = item.get("title") or item.get("name", "?")
        year = (item.get("release_date") or item.get("first_air_date") or "????")[:4]
        score = round(item.get("vote_average", 0), 1)
        overview = (item.get("overview") or "Sin descripción.")[:120]
        lines.append(f"• {title} ({year}) ★{score} — {overview}")

    return "\n".join(lines)


def _get_trending(api_key: str) -> str:
    try:
        with httpx.Client(timeout=8) as client:
            r = client.get(
                f"{_BASE}/trending/all/week",
                params={"api_key": api_key, "language": "es-ES"},
            )
            r.raise_for_status()
            results = r.json().get("results", [])[:6]
    except Exception as e:
        log.warning("TMDB trending falló: %s", e)
        return "No pude obtener tendencias de TMDB."

    lines = ["Trending esta semana:"]
    for item in results:
        title = item.get("title") or item.get("name", "?")
        media = "🎬" if item.get("media_type") == "movie" else "📺"
        score = round(item.get("vote_average", 0), 1)
        lines.append(f"{media} {title} ★{score}")

    return "\n".join(lines)
