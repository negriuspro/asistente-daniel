"""
post_flight_check.py — Gate obligatorio antes de cualquier despliegue que toque
routing, auth o clientes singleton (Fase 1 y cualquier absorción futura de
capacidades externas dentro de Daniel Core).

Uso (desde la carpeta daniel/, con el venv/Python que tenga las deps del server):
    python -m server.post_flight_check

Verifica:
  1. Rutas FastAPI registradas sin duplicados (path + método/WS).
  2. Un único punto de auth para control Docker (server.core.auth no debe existir).
  3. Un único cliente Docker (un solo módulo expone un getter de cliente Docker).

Sale con código != 0 si detecta cualquier problema — debe bloquear el despliegue.
No sustituye a un linter; es una verificación de arquitectura, no de estilo.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from collections import Counter


def _flatten_routes(routes) -> list:
    """
    Expande recursivamente routers incluidos. FastAPI >= ~0.136 envuelve los routers
    incluidos en un objeto interno (actualmente `_IncludedRouter`) que expone el
    router original via `.original_router`. Se recursa sobre `original_router.routes`
    directamente — esas rutas YA tienen el path final con el prefix aplicado (se
    aplica al momento de `router.add_api_route`, no al incluirse), así que no hace
    falta reconstruir paths ni depender de la API interna de contexto efectivo
    (que además no resuelve bien `.path` para rutas WebSocket en esta versión).
    Se detecta por duck-typing (`hasattr`), no por nombre de clase privada, para
    no acoplarse a un símbolo interno que puede cambiar entre versiones.
    """
    flat = []
    for route in routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            flat.extend(_flatten_routes(original_router.routes))
        else:
            flat.append(route)
    return flat


def check_routes() -> list[str]:
    from .main import app

    problems: list[str] = []
    seen: Counter[tuple[str, str]] = Counter()
    for route in _flatten_routes(app.routes):
        methods = getattr(route, "methods", None) or {"WS"}
        # Algunas rutas (notablemente WebSocket dentro de _EffectiveRouteContext)
        # dejan `.path` vacío y resuelven el path real en `.path_format`.
        path = getattr(route, "path", None) or getattr(route, "path_format", None)
        if not path:
            continue
        for method in methods:
            seen[(path, method)] += 1

    for (path, method), count in seen.items():
        if count > 1:
            problems.append(f"Ruta duplicada: {method} {path} ({count} registros)")
    return problems


def check_single_docker_client() -> list[str]:
    """Solo cuenta funciones DEFINIDAS (no re-exportadas via import) cuyo nombre
    sugiere que crean/obtienen un cliente Docker, fuera de docker_layer.client."""
    problems: list[str] = []
    candidates: list[str] = []
    for modname in ("server.docker_control", "server.docker_layer.containers", "server.docker_layer.metrics"):
        try:
            mod = importlib.import_module(modname)
        except ImportError:
            continue
        for name, obj in inspect.getmembers(mod, inspect.isfunction):
            if obj.__module__ != mod.__name__:
                continue  # re-exportada via import, no es una implementación nueva
            if "client" in name.lower() and "docker" in name.lower():
                candidates.append(f"{modname}.{name}")
    if candidates:
        problems.append(f"Getter(s) de cliente Docker fuera de docker_layer.client: {candidates}")
    return problems


def check_single_auth() -> list[str]:
    problems: list[str] = []
    try:
        importlib.import_module("server.core.auth")
        problems.append("server.core.auth todavía existe — la auth debe vivir solo en docker_control.py")
    except ImportError:
        pass

    try:
        importlib.import_module("server.docker_api")
        problems.append("server.docker_api todavía existe — router duplicado, debía eliminarse")
    except ImportError:
        pass

    return problems


def main() -> int:
    problems: list[str] = []
    problems += check_routes()
    problems += check_single_docker_client()
    problems += check_single_auth()

    if problems:
        print("POST-FLIGHT FAILED — despliegue bloqueado:\n")
        for p in problems:
            print(f"  x {p}")
        return 1

    print("POST-FLIGHT OK — sin rutas duplicadas, auth unica, cliente Docker unico.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
