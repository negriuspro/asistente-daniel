"""Weather via Open-Meteo (free, no API key needed)."""
import asyncio
import logging

import httpx

log = logging.getLogger("jarvis.weather")

_GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
_WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

_WMO_CODES = {
    0: "despejado", 1: "mayormente despejado", 2: "parcialmente nublado", 3: "nublado",
    45: "neblina", 48: "neblina con escarcha",
    51: "llovizna leve", 53: "llovizna moderada", 55: "llovizna densa",
    61: "lluvia leve", 63: "lluvia moderada", 65: "lluvia fuerte",
    71: "nieve leve", 73: "nieve moderada", 75: "nieve fuerte",
    80: "chubascos leves", 81: "chubascos moderados", 82: "chubascos fuertes",
    95: "tormenta", 96: "tormenta con granizo", 99: "tormenta fuerte",
}


async def get_weather(location: str) -> str:
    if not location or location.lower() in ("mi ubicación", "aquí", "aqui", "acá", "aca"):
        location = await _detect_city_by_ip()

    try:
        lat, lon, city_name = await _geocode(location)
    except Exception as e:
        log.warning("Geocoding falló para '%s': %s", location, e)
        return f"No encontré la ciudad '{location}'."

    try:
        data = await _fetch_weather(lat, lon)
    except Exception as e:
        log.warning("Weather API falló: %s", e)
        return "No pude obtener el clima en este momento."

    current = data.get("current", {})
    temp = current.get("temperature_2m", "?")
    feels = current.get("apparent_temperature", "?")
    humidity = current.get("relative_humidity_2m", "?")
    wind = current.get("wind_speed_10m", "?")
    code = current.get("weather_code", 0)
    desc = _WMO_CODES.get(code, "condición desconocida")

    return (
        f"En {city_name}: {desc}, {temp}°C (sensación {feels}°C). "
        f"Humedad {humidity}%, viento {wind} km/h."
    )


async def _geocode(location: str) -> tuple[float, float, str]:
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(_GEO_URL, params={"name": location, "count": 1, "language": "es"})
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            raise ValueError(f"Sin resultados para '{location}'")
        first = results[0]
        return first["latitude"], first["longitude"], first.get("name", location)


async def _fetch_weather(lat: float, lon: float) -> dict:
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": [
            "temperature_2m", "apparent_temperature", "relative_humidity_2m",
            "wind_speed_10m", "weather_code",
        ],
        "timezone": "auto",
    }
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(_WEATHER_URL, params=params)
        r.raise_for_status()
        return r.json()


async def _detect_city_by_ip() -> str:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("https://ipapi.co/json/")
            data = r.json()
            return data.get("city", "Buenos Aires")
    except Exception:
        return "Buenos Aires"
