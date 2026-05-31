"""
Daniel AI Assistant — Interactive setup wizard.
Run: python -m server.setup_wizard  (from the project root)
"""
import os
import sys
from pathlib import Path

_ENV_PATH = Path(__file__).parent.parent / ".env"

_STEPS = [
    {
        "key": "GEMINI_API_KEY",
        "label": "Google Gemini API Key (IA principal — REQUERIDA)",
        "help": "Obtén tu key GRATIS en: https://aistudio.google.com/apikey",
        "required": True,
    },
    {
        "key": "GROQ_API_KEY",
        "label": "Groq API Key (IA de respaldo — recomendada)",
        "help": "Obtén tu key GRATIS en: https://console.groq.com/keys",
        "required": False,
    },
    {
        "key": "ELEVENLABS_API_KEY",
        "label": "ElevenLabs API Key (voz premium — opcional)",
        "help": "10,000 chars/mes gratis en: https://elevenlabs.io",
        "required": False,
    },
    {
        "key": "SPOTIFY_CLIENT_ID",
        "label": "Spotify Client ID (control de Spotify — opcional)",
        "help": "Crea una app en: https://developer.spotify.com/dashboard",
        "required": False,
    },
    {
        "key": "SPOTIFY_CLIENT_SECRET",
        "label": "Spotify Client Secret",
        "help": "Del mismo panel de Spotify Developer",
        "required": False,
        "depends_on": "SPOTIFY_CLIENT_ID",
    },
    {
        "key": "TMDB_API_KEY",
        "label": "TMDB API Key (películas y series — opcional)",
        "help": "Key gratuita en: https://www.themoviedb.org/settings/api",
        "required": False,
    },
    {
        "key": "TUYA_ACCESS_ID",
        "label": "Tuya Access ID (smart home — opcional)",
        "help": "Obtén tus credenciales en: https://iot.tuya.com",
        "required": False,
    },
    {
        "key": "TUYA_ACCESS_SECRET",
        "label": "Tuya Access Secret",
        "help": "Del mismo panel de Tuya IoT",
        "required": False,
        "depends_on": "TUYA_ACCESS_ID",
    },
]


def _read_env() -> dict:
    env = {}
    if _ENV_PATH.exists():
        for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def _write_env(env: dict) -> None:
    lines = []
    for k, v in sorted(env.items()):
        lines.append(f"{k}={v}")
    _ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _mask(value: str) -> str:
    if not value:
        return "(vacío)"
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


def run_wizard() -> None:
    print("\n" + "═" * 60)
    print("  D.A.N.I.E.L — Asistente de Configuración")
    print("═" * 60)
    print("Presiona Enter para mantener el valor actual.\n")

    current = _read_env()
    updates = {}
    skipped = set()

    for step in _STEPS:
        key = step["key"]

        # Skip if dependency not set
        dep = step.get("depends_on")
        if dep and dep in skipped:
            skipped.add(key)
            continue

        current_val = current.get(key, "")
        label = step["label"]
        help_text = step["help"]
        required = step["required"]

        print(f"{'[REQUERIDA]' if required else '[opcional]'} {label}")
        print(f"  → {help_text}")
        if current_val:
            print(f"  Valor actual: {_mask(current_val)}")

        prompt = "  Nuevo valor (Enter para saltar): " if current_val else "  Valor: "
        try:
            val = input(prompt).strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nConfiguración cancelada.")
            return

        if val:
            updates[key] = val
        elif not current_val and required:
            print("  ⚠ Esta clave es requerida. Puedes agregarla manualmente en el archivo .env")
            skipped.add(key)
        elif not current_val:
            skipped.add(key)

        print()

    if not updates and not current:
        print("No se configuró nada. El archivo .env no fue modificado.")
        return

    # Merge with existing
    merged = {**current, **updates}

    # Set defaults
    merged.setdefault("APP_PORT", "3000")
    merged.setdefault("BATTERY_LOW", "20")
    merged.setdefault("BATTERY_HIGH", "80")
    merged.setdefault("GOOGLE_HOME_PORT", "8009")
    merged.setdefault("DOCKER_LOG_LINES", "200")
    merged.setdefault("DOCKER_STOP_TIMEOUT", "10")
    if "SPOTIFY_CLIENT_ID" in merged:
        merged.setdefault("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback")

    _write_env(merged)

    print("─" * 60)
    print(f"✓ Configuración guardada en: {_ENV_PATH}")
    print("\nPróximos pasos:")
    print("  1. Reinicia el servidor:  docker compose restart backend")
    print("  2. O con Python directo:  uvicorn server.main:app --reload")
    print("─" * 60 + "\n")


if __name__ == "__main__":
    run_wizard()
